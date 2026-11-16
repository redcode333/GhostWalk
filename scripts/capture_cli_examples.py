"""Run every `gw` command for real (in a throwaway workspace, and against the live deployment for `doctor` and `why-edge`) and save what it prints to docs/cli-examples/examples.json.
The README's CLI reference is rendered from that file, so no output in it is typed by hand.   python scripts/capture_cli_examples.py [--live https://api.example.com]"""
import argparse, json, os, pathlib, re, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "cli-examples" / "examples.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default="https://api.13-51-194-36.sslip.io")
    a = ap.parse_args()
    tmp = pathlib.Path(tempfile.mkdtemp())
    home = tmp / ".gw"
    env = {**os.environ, "GW_HOME": str(home), "NO_COLOR": "1", "COLUMNS": "100", "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
    for k in ("GW_URL", "GW_TOKEN", "GW_STORE"):
        env.pop(k, None)
    examples = []

    def gw(title, args, cwd=None, extra_env=None, keep=None, cmd_label=None):
        r = subprocess.run([sys.executable, "-c", "from ghostwalk.cli import main; main()", *args], cwd=cwd or tmp, env={**env, **(extra_env or {})}, text=True, encoding="utf8", capture_output=True)
        out = (r.stdout + r.stderr).rstrip()
        out = re.sub(r"[ \t]+$", "", out, flags=re.M)
        if keep:
            out = "\n".join(out.splitlines()[:keep])
        examples.append({"title": title, "cmd": cmd_label or "gw " + " ".join(args), "output": out, "exit": r.returncode})
        return out
    gw("the commands", ["--help"], keep=30)
    gw("a demo workspace and the next outage", ["demo"])
    out = gw("who broke it", ["why", "--alerts", "alerts.json"])
    inc = re.search(r"INC-\d+", out).group(0)
    table = out.split("rank  service")[1]
    root = re.search(r"1\s+(\S+)", table).group(1)
    other = re.search(r"2\s+(\S+)", table).group(1)
    # the postmortem says the real root was the runner-up, and that the top candidate depends on it: a dependency the map did not have
    gw("teach it what the postmortem found", ["learn", inc, "--root", other, "--path", f"{other} -> {root}", "--yes"])
    sys.path.insert(0, str(ROOT))
    from ghostwalk.api.samples import SAMPLE_FILES
    repos = tmp / "acme"
    for repo, path, text in SAMPLE_FILES:
        p = repos / repo.split("/")[1] / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf8")
    gw("import a dependency map from repos", ["map", "import", str(repos)], extra_env={"GW_HOME": str(tmp / ".gw-import")})
    gw("record a deploy the verdict can use", ["change", "add", root, "--kind", "deploy", "--ref", "#482"])
    gw("the held-out numbers", ["eval", "--split", "test"], cwd=ROOT)
    gw("export the graph (the input of `gw diff` in CI)", ["export", "--out", str(tmp / "graph.json")])
    # gw diff on a two-commit repo
    from tests.test_diff import C1, C2
    repo = tmp / "repo"
    repo.mkdir()
    g = lambda *x: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *x], check=True, capture_output=True)
    g("init", "-q", "-b", "main")
    (repo / "docker-compose.yml").write_text(C1, encoding="utf8")
    g("add", "."); g("commit", "-qm", "base")
    (repo / "docker-compose.yml").write_text(C2, encoding="utf8")
    g("commit", "-qam", "change")
    gw("pre-deploy blast radius of a change", ["diff", "--base", "HEAD~1", "--head", "HEAD", "--repo", str(repo)], keep=24)
    gw("the MCP server (stdio; started by Claude Code or Cursor)", ["mcp", "--help"], keep=12)
    if a.live:
        gw("check a running stack", ["doctor", "--url", a.live], cmd_label=f"gw doctor --url {a.live}")
        gw("why does the map say this?", ["why-edge", "experiment-svc", "ledger-db"], extra_env={"GW_URL": a.live}, cmd_label="GW_URL=https://<your-api> gw why-edge experiment-svc ledger-db")
    for e in examples:
        e["output"] = e["output"].replace(str(tmp), "/tmp/gw").replace(str(ROOT), "<repo>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(examples, indent=1), encoding="utf8")
    print([(e["cmd"][:40], e["exit"]) for e in examples])


if __name__ == "__main__":
    main()
