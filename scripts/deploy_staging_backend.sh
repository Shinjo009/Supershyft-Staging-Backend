#!/usr/bin/env bash
# Server alias: deploy-staging-backend -> ~/scripts/deploy_staging_backend.sh
# Syncs /var/www/staging-api from origin/main, migrates, restarts API (+ optional admin).
set -euo pipefail

API_DIR="${STAGING_API_ROOT:-/var/www/staging-api}"
ADMIN_DIR="${STAGING_ADMIN_ROOT:-/var/www/staging-admin-app}"
GIT_BRANCH="${STAGING_GIT_BRANCH:-main}"
DEPLOY_ADMIN="${DEPLOY_STAGING_ADMIN:-1}"
RUN_SEED="${STAGING_RUN_POST_DEPLOY:-0}"

cd "$API_DIR"
git fetch origin
git checkout "$GIT_BRANCH"
git reset --hard "origin/$GIT_BRANCH"

if [[ -f venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

pip install -q -r requirements.txt
alembic upgrade head

# Restart without sudo when the service user owns the uvicorn PID (port 8102).
if systemctl restart staging-api.service 2>/dev/null; then
  :
else
  old_pid="$(pgrep -f 'uvicorn main:app --host 127.0.0.1 --port 8102' || true)"
  if [[ -n "$old_pid" ]]; then
    kill "$old_pid" || true
    sleep 1
  fi
  nohup uvicorn main:app --host 127.0.0.1 --port 8102 >> /tmp/staging-api.log 2>&1 &
fi

if [[ "$RUN_SEED" == "1" ]]; then
  bash "$API_DIR/scripts/staging-post-deploy.sh"
fi

if [[ "$DEPLOY_ADMIN" == "1" ]]; then
  cd "$ADMIN_DIR"
  git fetch origin
  git checkout "$GIT_BRANCH"
  git reset --hard "origin/$GIT_BRANCH"
  npm ci
  npm run build
fi

echo "Staging deploy complete ($(git -C "$API_DIR" log -1 --oneline))"
