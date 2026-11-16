# Developer quickstart: the flow on the shopfront example

This walks the CLI on `examples/shopfront/`, a 12-service storefront. The map is built from its compose file, which does not show every dependency. The postmortems in `examples/shopfront/postmortems/` describe the ones it misses.

Install the CLI from this repo, then run the steps from inside the example:

    pip install -e .
    cd examples/shopfront
    gw map import .                                              # scan the repo: 12 services, 13 dependencies
    gw why --alerts alerts/storm-1.json                          # unsure: checkout-api 0.32, the real cause is not on any path yet
    gw learn INC-1000 --root feature-flags --path "feature-flags -> checkout-api" --missed "checkout-api depends on feature-flags" -y
    gw why --alerts alerts/storm-2.json                          # feature-flags 0.64, with the learned path
    gw diff --base main --head declare-flags                     # what a change adds: two dependencies on feature-flags and their blast radius

The first `why` is unsure on purpose: the flags dependency is not in the map. `learn` adds it as a tentative edge (0.35). A second incident confirms it, and then the verdict ranks it first with its path. `gw diff` needs two git refs; `examples/shopfront/setup_history.py <folder>` creates `main` and `declare-flags` in a scratch folder.

The steps are covered by `tests/test_scan_layout.py` (the scanner) and by the CLI tests.
