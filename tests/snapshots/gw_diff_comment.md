<!-- ghostwalk-diff -->
### GhostWalk: dependency changes in this PR

- + `fraud-check` → `config-svc` · new dependency · blast radius 4 services (fraud-check, payments, checkout-api, web-edge) · a learned edge already touches it: fraud-check ⇢ config-svc · `config-svc` caused INC-0931, INC-1042
- + `search` → `redis-main` · new dependency · blast radius 4 services (search, cart, web-edge, checkout-api)
- − `cart` → `redis-main` · removed (`docker-compose.yml`)

<sub>Read-only. Compared `main` with `feature` against graph revision 48.</sub>
