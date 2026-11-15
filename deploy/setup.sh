#!/usr/bin/env bash
# GhostWalk backend on a fresh Linux VM (Ubuntu/Debian, >= 4 GB RAM): HydraDB + API + Caddy (HTTPS).
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

if [ ! -f "$DEPLOY/.env" ]; then
  ip=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  API_DOMAIN="${API_DOMAIN:-api.${ip}.sslip.io}"
  {
    echo "API_DOMAIN=$API_DOMAIN"
    echo "GW_CORS_ORIGINS=${FRONTEND_ORIGIN:-}"
    echo "HYDRA_TOKEN=$(openssl rand -hex 16)"
    echo "GW_ADMIN_TOKEN=$(openssl rand -hex 24)"
    echo "GW_RATE_LIMIT=60/60"
  } > "$DEPLOY/.env"
  chmod 600 "$DEPLOY/.env"
  echo "wrote $DEPLOY/.env"
fi
if command -v ufw >/dev/null; then sudo ufw allow 80/tcp >/dev/null 2>&1 || true; sudo ufw allow 443/tcp >/dev/null 2>&1 || true; fi

DC="docker compose --env-file $DEPLOY/.env -f $DEPLOY/docker-compose.prod.yml"
$DC up -d --build
set -a; . "$DEPLOY/.env"; set +a
echo "waiting for https://$API_DOMAIN ..."
for i in $(seq 1 90); do
  if curl -fsS "https://$API_DOMAIN/api/health" >/dev/null 2>&1; then break; fi
  sleep 4
done
python3 -m pip install --quiet httpx 2>/dev/null || true
python3 "$DEPLOY/smoke.py" --api "https://$API_DOMAIN" ${GW_CORS_ORIGINS:+--frontend "$GW_CORS_ORIGINS"}
echo
echo "API:      https://$API_DOMAIN   (status: https://$API_DOMAIN/api/health)"
echo "Frontend: set VITE_API_URL=https://$API_DOMAIN in the Vercel project, then: cd web && vercel --prod"
