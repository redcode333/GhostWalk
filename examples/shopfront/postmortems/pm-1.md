# INC-1000: checkout errors after a flags rollout

Root cause: feature-flags (latency), which checkout-api reads on every request through a generated client.
Path: feature-flags -> checkout-api.
What the map missed: checkout-api depends on feature-flags. Nothing in the compose file or the env vars names it, because the client is generated from the flags schema.
