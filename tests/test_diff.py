import json, pathlib, shutil, subprocess
import pytest
from typer.testing import CliRunner
from ghostwalk import diff as D
from ghostwalk.cli import app

SNAP = pathlib.Path(__file__).parent / "snapshots" / "gw_diff_comment.md"
C1 = """\
services:
  web-edge:
    image: nginx
    depends_on: [checkout-api, search]
  checkout-api:
    image: acme/checkout
    depends_on: [payments, cart]
  payments:
    image: acme/payments
    depends_on: [postgres-pay, fraud-check]
  cart:
    image: acme/cart
    depends_on: [redis-main]
  fraud-check:
    image: acme/fraud
  search:
    image: acme/search
  config-svc:
    image: acme/config
  postgres-pay:
    image: postgres:16
  redis-main:
    image: redis:7
"""
C2 = C1.replace("    image: acme/fraud\n", "    image: acme/fraud\n    depends_on: [config-svc]\n").replace(
    "    image: acme/search\n", "    image: acme/search\n    depends_on: [redis-main]\n").replace("    depends_on: [redis-main]\n  fraud-check", "  fraud-check")
C2 = C2.replace("  cart:\n    image: acme/cart\n    depends_on: [redis-main]\n", "  cart:\n    image: acme/cart\n")


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *a], check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "acme"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "docker-compose.yml").write_text(C1)
    (r / "README.md").write_text("x")
    git(r, "add", "."); git(r, "commit", "-qm", "base")
    git(r, "checkout", "-qb", "feature")
    (r / "docker-compose.yml").write_text(C2)
    git(r, "commit", "-qam", "add config-svc dependency, move cart off redis")
    return r


NAMES = ["web-edge", "checkout-api", "payments", "cart", "fraud-check", "search", "config-svc", "postgres-pay", "redis-main"]
GRAPH = {"version": 1, "revision": 48, "components": {str(i): {"name": n, "kind": "service", "tier": 1} for i, n in enumerate(NAMES)},
         "names": {n: i for i, n in enumerate(NAMES)},
         "edges": [[0, 1, .7, "official", 0, -1], [0, 5, .7, "official", 0, -1], [1, 2, .7, "official", 0, -1], [1, 3, .7, "official", 0, -1], [2, 4, .7, "official", 0, -1],
                   [2, 7, .7, "official", 0, -1], [3, 8, .7, "official", 0, -1], [4, 6, .7, "learned", 2, 31]],
         "incidents": [{"id": "INC-0931", "root": "fraud-check", "confirmed_root": "config-svc", "status": "Resolved"},
                       {"id": "INC-1042", "root": "config-svc", "confirmed_root": "config-svc", "status": "Resolved"}]}


def test_edges_and_diff_between_two_commits(repo):
    base, head = D.edges_at(repo, "main"), D.edges_at(repo, "feature")
    added, removed = D.diff_edges(base, head)
    assert added == [("fraud-check", "config-svc"), ("search", "redis-main")]
    assert removed == [("cart", "redis-main")]
    assert head[("fraud-check", "config-svc")]["file"] == "docker-compose.yml"


def test_blast_radius_uses_the_current_graph_and_flags_learned_edges_and_incidents(repo):
    rep = D.build_report(repo, "main", "feature", GRAPH)
    a = {(x["src"], x["dst"]): x for x in rep["added"]}[("fraud-check", "config-svc")]
    assert a["known"] and set(a["blast"]) == {"fraud-check", "payments", "checkout-api", "web-edge"}
    assert a["touches_learned"] == ["fraud-check ⇢ config-svc"] and a["incidents"] == ["INC-0931", "INC-1042"]
    b = {(x["src"], x["dst"]): x for x in rep["added"]}[("search", "redis-main")]
    assert "search" in b["blast"] and not b["touches_learned"] and not b["incidents"]


def test_markdown_comment_snapshot(repo):
    md = D.to_markdown(D.build_report(repo, "main", "feature", GRAPH))
    if not SNAP.exists():                                   # first run writes the snapshot for review; afterwards it is a regression test
        SNAP.write_text(md, encoding="utf8")
    assert md == SNAP.read_text(encoding="utf8")
    assert md.startswith(D.MARKER) and md.count(D.MARKER) == 1


def test_without_a_graph_export_it_still_lists_edges(repo):
    md = D.to_markdown(D.build_report(repo, "main", "feature", None))
    assert "no graph export" in md and "`fraud-check` → `config-svc`" in md


def test_no_changes_message(repo):
    md = D.to_markdown(D.build_report(repo, "main", "main", GRAPH))
    assert "No dependency changes" in md


def test_cli_markdown_json_and_export_roundtrip(repo, tmp_path):
    g = tmp_path / "graph.json"
    g.write_text(json.dumps(GRAPH))
    r = CliRunner().invoke(app, ["diff", "--repo", str(repo), "--base", "main", "--head", "feature", "--graph", str(g), "--format", "markdown"])
    assert r.exit_code == 0 and r.output == SNAP.read_text(encoding="utf8")
    j = json.loads(CliRunner().invoke(app, ["diff", "--repo", str(repo), "--base", "main", "--head", "feature", "--graph", str(g), "--format", "json"]).output)
    assert [x["dst"] for x in j["added"]] == ["config-svc", "redis-main"]
    t = CliRunner().invoke(app, ["diff", "--repo", str(repo), "--base", "main", "--head", "feature", "--graph", str(g)])
    assert "blast radius" in t.output and "caused INC-0931" in t.output
    bad = CliRunner().invoke(app, ["diff", "--repo", str(repo), "--base", "nope", "--head", "feature"])
    assert bad.exit_code == 1

    from ghostwalk.api.workspace import Workspace
    ws = Workspace(None, demo_incidents=3)
    d = D.export_graph(ws)
    g2, inc, rev = D.load_graph(json.loads(json.dumps(d)))
    assert g2.edges.keys() == ws.g.edges.keys() and len(inc) == len(ws.incidents)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_action_comment_is_updated_in_place_never_duplicated(tmp_path):
    js = pathlib.Path(__file__).parent.parent / ".github/actions/ghostwalk-diff/upsert.js"
    script = tmp_path / "t.js"
    script.write_text(f"""
const upsert = require({json.dumps(str(js))}); const assert = require("assert")
const M = "<!-- ghostwalk-diff -->"
function fake(initial) {{
  const calls = []; let comments = initial.slice()
  return {{ calls, github: {{ paginate: async () => comments, rest: {{ issues: {{ listComments: {{}},
    createComment: async (a) => {{ calls.push("create"); const c = {{ id: 100 + comments.length, body: a.body }}; comments.push(c); return {{ data: c }} }},
    updateComment: async (a) => {{ calls.push("update"); comments.find((c) => c.id === a.comment_id).body = a.body }},
    deleteComment: async (a) => {{ calls.push("delete"); comments = comments.filter((c) => c.id !== a.comment_id) }} }} }} }}, comments: () => comments }}
}}
const ctx = {{ repo: {{ owner: "o", repo: "r" }}, issue: {{ number: 7 }} }}
;(async () => {{
  const f = fake([{{ id: 1, body: "unrelated" }}])
  assert.strictEqual((await upsert({{ github: f.github, context: ctx, body: M + "v1" }})).action, "created")
  assert.strictEqual((await upsert({{ github: f.github, context: ctx, body: M + "v2" }})).action, "updated")
  assert.strictEqual((await upsert({{ github: f.github, context: ctx, body: M + "v2" }})).action, "unchanged")
  assert.strictEqual(f.comments().filter((c) => c.body.includes(M)).length, 1)
  const d = fake([{{ id: 5, body: M + "a" }}, {{ id: 9, body: M + "b" }}])
  await upsert({{ github: d.github, context: ctx, body: M + "c" }})
  assert.deepStrictEqual(d.comments().map((c) => c.id), [5]); assert.strictEqual(d.comments()[0].body, M + "c")
  await assert.rejects(() => upsert({{ github: f.github, context: ctx, body: "no marker" }}))
  console.log("ok")
}})().catch((e) => {{ console.error(e); process.exit(1) }})
""")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr
