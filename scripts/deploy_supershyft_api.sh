#!/usr/bin/env bash
# Production API deploy — installed on servers as /usr/local/bin/deploy-supershyft-api
# Clone path: /var/www/supershyft-api — branch: origin/main (SuperShyft-devs/dev-api)
set -euo pipefail

API_DIR="/var/www/supershyft-api"
BRANCH="main"

echo "======================================"
echo "  Supershyft API Deploy - $(date)"
echo "======================================"

_deploy_user() {
  if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    echo "$SUDO_USER"
  else
    id -un
  fi
}

echo ""
echo "▶ [1/5] Pulling backend..."
_run_user="$(_deploy_user)"
if [[ "$_run_user" != "$(id -un)" ]]; then
  sudo -u "$_run_user" -H git -C "$API_DIR" pull origin "$BRANCH"
else
  git -C "$API_DIR" pull origin "$BRANCH"
fi
cd "$API_DIR"

echo "▶ [2/5] Installing dependencies..."
"$API_DIR/venv/bin/pip" install -r "$API_DIR/requirements.txt"

echo "▶ [3/5] Running migrations..."
export DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "$API_DIR/.env")"
(cd "$API_DIR" && "$API_DIR/venv/bin/alembic" upgrade head)

echo "▶ [4/5] Restarting API..."
sudo systemctl restart supershyft-api

echo "▶ [5/5] Checking API..."
sudo systemctl is-active --quiet supershyft-api
for i in {1..10}; do
    if curl --fail --silent http://127.0.0.1:8000/openapi.json >/dev/null; then
        echo "✔ API health check passed"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "✖ API health check failed after 10 attempts"
        exit 1
    fi
    sleep 2
done

echo ""
echo "======================================"
echo "  ✅ API deploy complete - $(date)"
echo "======================================"