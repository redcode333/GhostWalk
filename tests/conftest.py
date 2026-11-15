import os
import httpx
import pytest

HYDRA_URL = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
HYDRA_READY = os.environ.get("HYDRA_READY", "http://127.0.0.1:9090/readyz")
HYDRA_TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")


def hydra_is_up():
    try:
        return httpx.get(HYDRA_READY, timeout=2).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def hydra_available():
    if not hydra_is_up():
        pytest.skip(f"HydraDB is not running ({HYDRA_READY} unreachable): start it with "
                    "scripts/start_hydradb_local.sh <hydradb repo>")


@pytest.fixture
def make_hydra(hydra_available):
    """Factory for HydraGraph backends; every one is dropped (company nodes deleted) at teardown."""
    import itertools, time
    from ghostwalk.graph.hydra import HydraGraph
    made = []
    base = int(time.time()) % 1000
    counter = itertools.count(1)

    def make():
        hg = HydraGraph(HYDRA_URL, HYDRA_TOKEN, run_id=base * 100 + next(counter))
        made.append(hg)
        return hg
    yield make
    for hg in made:
        hg.drop()
        hg.close()
