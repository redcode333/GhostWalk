# shopfront (example)

A small storefront with 12 services. It is the example for the developer flow: scan the repos, ask why, teach the map from a postmortem, check what a change touches.

The map is built from the compose file. It does not show two dependencies that the code has (a feature-flag client that checkout uses, a shared orders read in checkout, and a cart-count read in the web app). The postmortems in `postmortems/` describe them; the alert sets in `alerts/` are the incidents.

Run the flow from this folder (see docs/DEVELOPER-QUICKSTART.md):

    gw map import .
    gw why --alerts alerts/storm-1.json
    gw learn INC-1000 --root feature-flags --path "feature-flags -> checkout-api" -y
    gw why --alerts alerts/storm-2.json
