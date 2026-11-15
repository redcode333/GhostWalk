# Deploying GhostWalk

Two halves: the **backend** (HydraDB + API + Caddy HTTPS) on a Linux VM, and the **frontend** (the Vite app) on Vercel.

## 1. Backend on a Linux VM (>= 4 GB RAM)

```bash
git clone https://github.com/redcode333/GhostWalk && cd GhostWalk
FRONTEND_ORIGIN=https://<your-project>.vercel.app ./deploy/setup.sh
```

`deploy/setup.sh` installs Docker if it is missing, writes `deploy/.env` (random HydraDB and admin tokens; `API_DOMAIN` defaults to `api.<vm-ip>.sslip.io`, or set `API_DOMAIN=api.example.com`),
starts `deploy/docker-compose.prod.yml` and runs `deploy/smoke.py` against it. Open ports 80 and 443.

| service | what it is |
|---|---|
| `hydradb` | the pinned HydraDB 0.4.0 image, no published ports, data in the `hydradb-data` volume |
| `api` | GhostWalk with `GW_STORE=hydradb`, `AUTH_MODE=none`, `GW_PUBLIC_DEMO=1`, rate limit on `/v1/*` and on POSTs, CORS for the frontend origin only |
| `caddy` | HTTPS (Let's Encrypt) in front of the API; certificate data in the `caddy-data` volume |

HydraDB 0.4.0 runs with its local store on the `hydradb-data` volume (`STORAGE=local`, the default). An opt-in MinIO setup exists (`STORAGE=minio`, below) but is not the default.

**The public demo** is a sandbox: anyone can trigger a demo outage, read verdicts, apply a postmortem and ask `why-edge`; settings, onboarding and webhooks answer 403. It is rebuilt every night at
03:00 UTC (or `POST /api/demo/reset` with the `X-GW-Admin` token). `GET /api/health` is the status endpoint.

Update later: `./deploy/setup.sh update` (the `deploy` workflow does this over SSH on every push to `main` that touches the backend; secrets `VM_HOST`, `VM_USER`, `VM_SSH_KEY`).

## 2. Frontend on Vercel

```bash
cd web
vercel link                                   # once
vercel env add VITE_API_URL production        # https://<API_DOMAIN>
vercel --prod
```

`web/vercel.json` sets the Vite build and the single-page-app rewrite (every path serves `index.html`, so `/demo` works). Put the resulting `https://<project>.vercel.app` into `GW_CORS_ORIGINS`
on the VM (`deploy/.env`, then `./deploy/setup.sh update`) so the browser may call the API.

## 3. Smoke test

```bash
python deploy/smoke.py --api https://<API_DOMAIN> --frontend https://<project>.vercel.app --rate-limit-check
```

Checks the landing page and that its bundle points at the API, `/demo`, health, that the store is HydraDB, CORS (allowed for the frontend, refused for others), the proof data, a demo outage verdict,
learn -> apply (answers at once with `saving`, the revision moves when the write lands), `why-edge` on a learned edge, the sandbox guard and the rate limit.

## Object storage (MinIO): tried, not the default

`STORAGE=minio ./deploy/setup.sh` adds MinIO (internal network only, no published ports, data in the `minio-data` volume), a one-shot `mc` container that creates the bucket and a user limited to it
(credentials generated into `deploy/.env`, never committed or printed), and points HydraDB at it with `CLOUD_PROVIDER=aws`, `AWS_ENDPOINT`, `AWS_BUCKET_NAME`, `AWS_ALLOW_HTTP`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
(from HydraDB's Helm chart). HydraDB's writer leases and manifest pointer need conditional writes; its startup log confirms "object store passed the create-only probe: writers allowed" on MinIO
`RELEASE.2025-09-07T16-13-09Z`. MinIO no longer publishes images, so `deploy/minio/Dockerfile` builds that release from source.

What was verified on a laptop (Docker Desktop, not the VM): the stack starts, the bucket fills (about 24 MB, 2,900 objects after the demo seed), `deploy/smoke.py` passes, 60 incidents with learning give identical
rankings and an identical learned graph against the in-memory learner (`deploy/parity_check.py`), and `make durability-demo` (stop everything, delete only HydraDB's local volume, keep MinIO's, start again) returns
an identical ranking and `why-edge`: the graph is read back from object storage.

**What blocked making it the default:** after any HydraDB restart, every write is rejected with `409 mutation_conflict: idempotency identity was reused for a different request`, so the learn step cannot save
(reads are fine). This is not specific to MinIO: the same thing happens on local disk after restarting the `hydradb` container (reproduced). Sending `Idempotency-Key` or `X-Request-Id` headers did not help, and
giving the node a new `GRAPH_NODE_ID` on each boot did not fix the API's writes. With local disk the workaround is to delete the volume and re-seed the (disposable) demo; with MinIO the data survives
so the same wipe is not available without emptying the bucket. Until HydraDB resolves this, the deployment keeps the persistent volume, and we do not claim that the graph "comes back from object storage"
in production. Not measured: warm latency on MinIO against local disk (one write took about 6 s on MinIO against 2.7 s on local disk in the smoke test, laptop, indicative only).
