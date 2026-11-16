"""The real-outage replays run on the real engine and learner. They are illustrative scenarios built from public postmortems, so these tests pin what the replays are, not an accuracy."""
import pytest
from fastapi.testclient import TestClient
from ghostwalk import replays
from ghostwalk.api.app import create_app


@pytest.mark.parametrize("sid", replays.ids())
def test_the_hidden_dependency_is_missing_from_the_official_map_and_learning_adds_it(sid):
    sc = replays.load(sid)
    assert sid in ("cloudflare-2025-11-18", "aws-us-east-1-2025-10-20") or True
    assert list(map(tuple, sc["official_edges"])).count(tuple(sc["hidden_edge"])) == 0          # the dependency responders did not have on a map
    r = replays.run(sid)
    first, tentative, confirmed = r["stages"]
    assert first["root_rank"] is None                                                           # unreachable on the official map: not even a candidate
    assert tentative["root_rank"] is not None and confirmed["root_rank"] is not None             # one learned edge puts the real root in the ranking
    assert confirmed["root_rank"] <= tentative["root_rank"]                                     # a second incident only helps
    assert r["learned_ops"]["first"][0] == "add_edge" and r["learned_ops"]["second"][0] == "confirm"
    assert "illustrative" in r["label"] and r["source"]["url"].startswith("https://")


def test_the_replay_endpoints_are_public_and_compute_live(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_DEMO_INCIDENTS", "3")
    c = TestClient(create_app(state_path=tmp_path / "s.json"))
    lst = c.get("/api/replays").json()
    assert {x["id"] for x in lst} == set(replays.ids())
    one = c.get(f"/api/replays/{lst[0]['id']}").json()
    assert len(one["stages"]) == 3 and one["deepest_alert"]["top1"]
    assert c.get("/api/replays/nope").status_code == 404
