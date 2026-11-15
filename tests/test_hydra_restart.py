"""Writes keep working after the HydraDB container restarts (regression for the 409 mutation_conflict, docs/hydradb-issue.md).
HydraDB 0.4.0 numbered HTTP requests http-query-1, 2, ... from the start of every process and deduplicated writes durably by that number; the adapter now sends its own unique query_id.
Needs docker and the compose `hydradb` service; skips otherwise."""
import shutil, subprocess, time
import pytest
from eval.runner import load
from ghostwalk.graph.hydra import HydraGraph
from ghostwalk.learn import update


def _container():
    if not shutil.which("docker"):
        return None
    out = subprocess.run(["docker", "ps", "--filter", "publish=8443", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    return out[0] if out else None


def test_a_write_after_a_hydradb_restart_is_accepted_and_the_data_is_intact(make_hydra):
    name = _container()
    if name is None:
        pytest.skip("no docker container publishing HydraDB on 8443")
    co = sorted(load("dev"), key=lambda c: len(c["components"]))[0]
    hg = make_hydra()
    g = hg.fresh(co)
    inc = co["incidents"][0]
    hg.apply(update.propose(g, inc["postmortem"], None, inc["alerts"], 0), incident={"seq": 0, "name": "i0", "alerts": inc["alerts"], "postmortem": inc["postmortem"]})
    before = hg._read_graph()
    subprocess.run(["docker", "restart", name], check=True, capture_output=True)
    for _ in range(90):
        try:
            if hg._rows("MATCH (m {id: $id}) RETURN m.seq AS seq", id=hg.co + 99_999):
                break
        except Exception:
            time.sleep(1)
    after = hg._read_graph()
    assert after.seq == before.seq and list(after.edges) == list(before.edges)             # nothing lost
    inc1 = co["incidents"][1]
    snap = hg.snapshot()
    hg.apply(update.propose(snap, inc1["postmortem"], None, inc1["alerts"], 1), incident={"seq": 1, "name": "i1", "alerts": inc1["alerts"], "postmortem": inc1["postmortem"]})
    assert hg.revision() == before.seq + 1                                                  # the write after the restart landed (it was a 409 before the fix)
