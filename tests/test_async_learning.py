"""Async learning writes (GW_STORE=hydradb): the endpoint accepts and journals the job, one background writer applies the HydraDB writes in order and bumps the
revision when each is done, verdicts read only the committed graph, and a crash mid-queue is replayed on restart. Skips cleanly when HydraDB is down."""
import pytest
from ghostwalk.api.workspace import Workspace
from ghostwalk.graph.hydra import HydraGraph
from tests.test_parity import state_equal

START, N = 8, 5


def _learn(ws, k):
    """One incident's full cycle through the workspace API: ingest alerts, queue the postmortem, apply it."""
    c = ws.company["incidents"][k]
    inc = ws.ingest_alerts(c["alerts"], source="test")
    item = ws.queue(inc, c["postmortem"], "test")
    return inc, ws.apply_pending(item["id"])


def _rank(ws, k):
    return [(r["id"], r["confidence"]) for r in ws.ingest_alerts(ws.company["incidents"][k]["alerts"], source="test")["verdict"]["ranking"]]


def _twin():
    tw = Workspace(None, demo_incidents=START, store="memory")
    for k in range(START, START + N):
        _learn(tw, k)
    return tw


def test_accepts_immediately_writes_in_order_and_ranks_like_the_in_memory_learner(make_hydra, tmp_path):
    hg = make_hydra()
    ws = Workspace(tmp_path / "s.json", demo_incidents=START, store="hydradb", hydra=hg)
    rev0 = ws.hy.revision()
    replies = [_learn(ws, k)[1] for k in range(START, START + N)]
    assert all(r["saving"] for r in replies)                            # answered before the HydraDB writes were done
    assert ws.summary()["saving"] >= 0 and len(ws.jobs) <= N
    assert ws.wait_saved(120) and ws.summary()["saving"] == 0
    assert ws.hy.revision() == rev0 + N and ws.revision >= N            # one bump per job, in order
    tw = _twin()
    state_equal(ws.g, tw.g)
    assert _rank(ws, START + N) == _rank(tw, START + N)
    seqs = [l["created_seq"] for l in ws.hy.lessons()]
    assert seqs == sorted(seqs, reverse=True)                           # lessons were written in queue order


def test_a_verdict_never_sees_a_half_written_lesson(make_hydra, tmp_path):
    hg = make_hydra()
    ws = Workspace(tmp_path / "s.json", demo_incidents=START, store="hydradb", hydra=hg)
    before = _rank(ws, START)
    _learn(ws, START)
    mid = _rank(ws, START)                                              # the write is (probably) still in flight: the committed graph answers
    ws.wait_saved(120)
    assert mid == before or mid == _rank(ws, START)                     # either the old committed graph or the new one, never something in between


def test_crash_before_the_queue_ran_is_replayed(make_hydra, tmp_path):
    hg = make_hydra()
    path = tmp_path / "s.json"
    ws = Workspace(path, demo_incidents=START, store="hydradb", hydra=hg, worker=False)       # accepts and journals, but the writer never runs
    for k in range(START, START + 3):
        _learn(ws, k)
    assert len(ws.jobs) == 3 and ws.hy.revision() == ws.g.seq           # nothing reached HydraDB
    del ws                                                              # "crash"
    hg2 = HydraGraph(run_id=hg.run_id, mode="cached")
    ws2 = Workspace(path, demo=False, store="hydradb", hydra=hg2)
    assert ws2.wait_saved(120)
    tw = Workspace(None, demo_incidents=START, store="memory")
    for k in range(START, START + 3):
        _learn(tw, k)
    state_equal(ws2.g, tw.g)
    assert _rank(ws2, START + 3) == _rank(tw, START + 3)


def test_crash_in_the_middle_of_a_job_is_replayed_without_double_counting(make_hydra, tmp_path):
    hg = make_hydra()
    path = tmp_path / "s.json"
    ws = Workspace(path, demo_incidents=START, store="hydradb", hydra=hg)
    real, calls = ws.hy._write_meta, {"n": 0}

    def dying_meta(*a, **k):                                            # the second job dies after its graph and memory writes, before the revision bump
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash")
        return real(*a, **k)
    ws.hy._write_meta = dying_meta
    for k in range(START, START + 3):
        _learn(ws, k)
    with pytest.raises(RuntimeError):
        ws.wait_saved(60)
    assert len(ws.jobs) >= 2                                            # the failed job and the one behind it are still journalled
    del ws
    hg2 = HydraGraph(run_id=hg.run_id, mode="cached")
    ws2 = Workspace(path, demo=False, store="hydradb", hydra=hg2)
    assert ws2.wait_saved(120)
    tw = Workspace(None, demo_incidents=START, store="memory")
    for k in range(START, START + 3):
        _learn(tw, k)
    state_equal(ws2.g, tw.g)                                            # counters and confirmations were not applied twice
    assert _rank(ws2, START + 3) == _rank(tw, START + 3)
