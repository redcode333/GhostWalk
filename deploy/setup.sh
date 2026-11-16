#!/usr/bin/env bash
# GhostWalk backend on a fresh Linux VM (Ubuntu/Debian, >= 4 GB RAM): HydraDB + MinIO + API + Caddy (HTTPS).
#   git clone https://github.com/redcode333/GhostWalk && cd GhostWalk
#   FRONTEND_ORIGIN=https://ghostwalk.vercel.app ./deploy/setup.sh        # API_DOMAIN defaults to api.<this-vm-ip>.sslip.io
#   API_DOMAIN=api.example.com FRONTEND_ORIGIN=https://example.com ./deploy/setup.sh
#   ./deploy/setup.sh update        # git pull, rebuild, restart, smoke test
set -euo pipefail
cd "$(dirname "$0")/.."
DEPLOY=deploy
MODE="${1:-install}"

mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 3600000 ]; then echo "need >= 4 GB RAM (found $((mem_kb / 1024)) MB)"; exit 1; fi

if ! command -v docker >/dev/null; then
  echo "installing docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null || { echo "docker compose plugin missing"; exit 1; }

if [ "$MODE" = "update" ]; then git pull --ff-only; fi

ENVF="$DEPLOY/.env"
touch "$ENVF"; chmod 600 "$ENVF"
ensure() { grep -q "^$1=" "$ENVF" || echo "$1=$2" >> "$ENVF"; }      # add a setting once; existing values (and generated secrets) are never overwritten
ip=$(curl -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
ensure API_DOMAIN "${API_DOMAIN:-api.${ip}.sslip.io}"
ensure GW_CORS_ORIGINS "${FRONTEND_ORIGIN:-}"
ensure HYDRA_TOKEN "$(openssl rand -hex 16)"
ensure GW_ADMIN_TOKEN "$(openssl rand -hex 24)"
ensure GW_RATE_LIMIT "60/60"        # the public VM only: the code default is off
# object storage for HydraDB: STORAGE=minio (default) keeps the graph in MinIO on this VM; STORAGE=local keeps it on a docker volume
STORAGE="${STORAGE:-$(grep '^STORAGE=' "$ENVF" | cut -d= -f2 || true)}"; STORAGE="${STORAGE:-minio}"
ensure STORAGE "$STORAGE"
ensure MINIO_ROOT_USER "gwadmin$(openssl rand -hex 4)"
ensure MINIO_ROOT_PASSWORD "$(openssl rand -hex 24)"
ensure HYDRA_S3_KEY "$(openssl rand -hex 10)"
ensure HYDRA_S3_SECRET "$(openssl rand -hex 24)"
ensure HYDRA_BUCKET "ghostwalk"
sed -i '/^HYDRA_CLOUD_PROVIDER=/d;/^COMPOSE_PROFILES=/d' "$ENVF"
if [ "$STORAGE" = minio ]; then echo "HYDRA_CLOUD_PROVIDER=aws" >> "$ENVF"; echo "COMPOSE_PROFILES=minio" >> "$ENVF"; else echo "HYDRA_CLOUD_PROVIDER=local" >> "$ENVF"; echo "COMPOSE_PROFILES=" >> "$ENVF"; fi
echo "storage: $STORAGE (secrets are in $ENVF, not printed)"
if command -v ufw >/dev/null; then sudo ufw allow 80/tcp >/dev/null 2>&1 || true; sudo ufw allow 443/tcp >/dev/null 2>&1 || true; fi

DC="docker compose --env-file $DEPLOY/.env -f $DEPLOY/docker-compose.prod.yml"
export GW_VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"     # shown in /health
$DC up -d --build
set -a; . "$DEPLOY/.env"; set +a
echo "waiting for https://$API_DOMAIN ..."
for i in $(seq 1 90); do
  if curl -fsS "https://$API_DOMAIN/api/health" >/dev/null 2>&1; then break; fi
  sleep 4
done
# the smoke test runs in a throwaway container: the VM needs no Python packages
docker run --rm --network host -v "$PWD/$DEPLOY:/d:ro" python:3.12-slim sh -c 'pip install -q httpx >/dev/null 2>&1 && python /d/smoke.py "$@"' sh --api "https://$API_DOMAIN" ${GW_CORS_ORIGINS:+--frontend "$GW_CORS_ORIGINS"}
echo
echo "API:      https://$API_DOMAIN   (status: https://$API_DOMAIN/api/health)"
echo "Frontend: set VITE_API_URL=https://$API_DOMAIN in the Vercel project, then: cd web && vercel --prod"
