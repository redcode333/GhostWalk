"""The response parser, tested offline against responses saved from a live HydraDB v0.4.0 node (tests/fixtures)."""
import json, pathlib
import pytest
from ghostwalk.graph.hydra import _tabulate, _parse_path, decode_cell, HydraError

FX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text())


def test_probe_response_shape_and_vertex_id_decoding():
    probe = load("hydra_probe.json")
    assert probe["columns"] == ["id"]
    assert _tabulate(probe) == [[999998]]                        # a vertex_id cell decodes to a plain int


def test_path_response_decodes_nodes_cost_and_unwraps_tagged_properties():
    resp = load("hydra_sppaths.json")
    nodes, cost = _parse_path(resp, base=0)
    assert nodes == [500, 501] and cost > 0
    path = _tabulate(resp)[0][0]
    assert path["edges"][0]["type"] == "DEPENDS_ON" and path["edges"][0]["props"]["conf"] == 0     # {"Integer": 0} unwrapped
    assert _parse_path(resp, base=500)[0] == [0, 1]              # ids are made local by subtracting the company offset


def test_null_cells_have_no_value_key_and_lists_hold_typed_cells():
    assert decode_cell({"type": "null"}) is None
    assert decode_cell({"type": "list", "value": [{"type": "vertex_id", "value": 2}, {"type": "null"}]}) == [2, None]
    assert decode_cell({"type": "float", "value": 1}) == 1.0 and decode_cell({"type": "string", "value": "x"}) == "x"


def test_no_rows_means_unreachable_and_errors_raise():
    assert _parse_path({"columns": ["path", "pathCost"], "rows": []}, 0) is None
    with pytest.raises(HydraError, match="invalid_request"):
        _tabulate({"error": {"code": "invalid_request", "message": "OpenCypher query is not supported yet: x"}})
    with pytest.raises(HydraError, match="unexpected"):
        _tabulate({"detail": "Failed to deserialize the JSON body"})              # the bare-422 envelope has neither rows nor error


# ---- pagination: results are paged (default 1024 rows) and a client that ignores next_cursor silently truncates -----------------
import httpx
from ghostwalk.graph.hydra import HydraGraph, PAGE_SIZE


def paged_graph(total, page=4):
    seen = []

    def handler(req: httpx.Request):
        b = json.loads(req.content)
        seen.append(b)
        assert b["page_size"] == PAGE_SIZE                           # page_size is re-sent on every page, constant
        start = b.get("cursor", 0) if "cursor" in b else 0
        nxt = start + page
        rows = [[{"type": "vertex_id", "value": i}] for i in range(start, min(nxt, total))]
        return httpx.Response(200, json={"query_id": "q1", "columns": ["id"], "rows": rows, "next_cursor": nxt if nxt < total else None})
    hg = HydraGraph()
    hg._http = httpx.Client(transport=httpx.MockTransport(handler), headers=hg._http.headers)
    return hg, seen


def test_every_page_is_read_and_each_cursor_is_used_once():
    hg, seen = paged_graph(10)
    assert [r[0] for r in hg._rows("MATCH (n:T) RETURN n.id AS id")] == list(range(10))
    assert len(seen) == 3 and [b.get("cursor") for b in seen] == [None, 4, 8]
    assert all(b["query_id"] == "q1" for b in seen[1:]) and all(b["query"] == seen[0]["query"] for b in seen)    # the whole request is re-sent


def test_a_single_page_result_makes_one_request():
    hg, seen = paged_graph(3)
    assert len(hg._rows("MATCH (n:T) RETURN n.id AS id")) == 3 and len(seen) == 1
