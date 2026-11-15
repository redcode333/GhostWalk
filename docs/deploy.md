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

There is no MinIO: HydraDB 0.4.0 is run with its local SlateDB store on a named volume (`CLOUD_PROVIDER=local`), which is the configuration we have tested.

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
