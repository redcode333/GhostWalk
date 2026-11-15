import pytest
from ghostwalk import mcp_tools as t
from ghostwalk.api.workspace import Workspace


@pytest.fixture(scope="module")
def ws():
    return Workspace(None, demo_incidents=8)


def test_why_returns_ranked_roots_path_and_explanation(ws):
    inc = ws.incidents[-1]
    out = t.why(ws, inc["alerts"])
    assert out["ranking"][0]["service"] == out["root"] and 0 < out["confidence"] <= 1 and out["explanation"].startswith("Root cause:")
    assert t.why(ws, [a["name"] for a in inc["alerts"]])["root"] == out["root"]      # plain names work too


def test_tools_are_read_only_and_errors_are_clear(ws):
    before = dict(ws.g.edges), len(ws.pending)
    inc = ws.incidents[-1]["verdict"]
    r, e = inc["root_name"], inc["entry_name"]
    t.path(ws, r, e); t.blast_radius(ws, r, 3)
    assert (dict(ws.g.edges), len(ws.pending)) == before
    with pytest.raises(t.ToolError, match="not in the map"):
        t.path(ws, "no-such-service", e)
    b = t.blast_radius(ws, r, 2)
    assert b["hops"] == 2 and b["count"] == len(b["affected"])


def test_propose_edge_creates_a_pending_proposal_and_never_writes_the_graph(ws):
    names = [c["name"] for c in list(ws.g.components.values())[:2]]
    edges_before = dict(ws.g.edges)
    n = len(ws.pending)
    # use a pair that is not already an edge
    a, b = next((x["name"], y["name"]) for i, x in ws.g.components.items() for j, y in ws.g.components.items() if i != j and (i, j) not in ws.g.edges)
    out = t.propose_edge(ws, a, b, "INC-1001", "saw it in the traces")
    assert out["status"] == "pending" and out["applied"] is False
    assert len(ws.pending) == n + 1 and dict(ws.g.edges) == edges_before
    item = ws.pending[-1]
    assert item["shown"][0]["text"] == f"{a} ⇢ {b}" and "MCP client" in item["source"]
    ws.apply_pending(item["id"])
    assert any(e.origin == "learned" for e in ws.g.edges.values())          # only a human approval writes it


def test_stdio_server_exposes_exactly_the_six_tools(tmp_path, monkeypatch):
    import asyncio, json
    from ghostwalk.mcp_server import build_server
    monkeypatch.setenv("GW_HOME", str(tmp_path / "gw"))
    monkeypatch.delenv("GW_URL", raising=False)
    w = Workspace(tmp_path / "gw" / "state.json", demo_incidents=4)
    w.save()
    srv = build_server()
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert names == {"why", "path", "blast_radius", "propose_edge", "why_edge", "lesson_impact"}
    alerts = [a["name"] for a in w.incidents[-1]["alerts"]]
    out = asyncio.run(srv.call_tool("why", {"alerts": alerts}))
    assert "Root cause:" in json.dumps(out, default=str)
