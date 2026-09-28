#!/bin/bash
#
# deploy_staging_backend.sh — Deploy staging-api (+ optional staging-admin-app)
# Server alias: deploy-staging-backend -> ~/scripts/deploy_staging_backend.sh
#
# Usage:
#   ./scripts/deploy_staging_backend.sh
#   DEPLOY_STAGING_ADMIN=0 ./scripts/deploy_staging_backend.sh   # API only
#
set -euo pipefail

API_DIR="${STAGING_API_ROOT:-/var/www/staging-api}"
ADMIN_DIR="${STAGING_ADMIN_ROOT:-/var/www/staging-admin-app}"
API_BRANCH="${STAGING_API_BRANCH:-Stage1}"
ADMIN_BRANCH="${STAGING_ADMIN_BRANCH:-main}"
API_SERVICE="${STAGING_API_SERVICE:-staging-api.service}"
API_HEALTH_URL="${STAGING_API_HEALTH_URL:-https://staging-api.supershyft.com/docs}"
DEPLOY_STAGING_ADMIN="${DEPLOY_STAGING_ADMIN:-1}"

GREEN="\033[0;32m"
RED="\033[0;31m"
CYAN="\033[0;36m"
YELLOW="\033[0;33m"
RESET="\033[0m"

step() { echo -e "\n${CYAN}▶ $1${RESET}"; }
success() { echo -e "${GREEN}✔ $1${RESET}"; }
warn() { echo -e "${YELLOW}▲ $1${RESET}"; }
fail() { echo -e "${RED}✖ $1${RESET}"; exit 1; }

echo -e "${CYAN}=== Deploying staging backend (API${DEPLOY_STAGING_ADMIN:+ + admin app}) ===${RESET}"

step "[API] Pulling latest code from ${API_BRANCH}"
cd "$API_DIR" || fail "Could not find ${API_DIR}"
git fetch origin || fail "git fetch failed"
git reset --hard "origin/${API_BRANCH}" || fail "git reset failed"
success "API code updated"

step "[API] Activating virtualenv and installing dependencies"
source venv/bin/activate || fail "Could not activate venv (does ${API_DIR}/venv exist?)"
pip install -r requirements.txt || fail "pip install failed"
success "Dependencies installed"

step "[API] Running database migrations"
cd "$API_DIR" || fail "Could not find ${API_DIR}"
set -a
# shellcheck disable=SC1091
source .env
set +a
alembic upgrade head || fail "alembic migration failed"
success "Migrations applied"

if [[ -f "${API_DIR}/scripts/staging-post-deploy.sh" ]]; then
  step "[API] Post-deploy hooks"
  bash "${API_DIR}/scripts/staging-post-deploy.sh" || warn "staging-post-deploy.sh failed (non-fatal)"
fi

step "[API] Restarting service"
sudo systemctl restart "$API_SERVICE" || fail "Failed to restart ${API_SERVICE}"
success "Service restarted"

step "[API] Checking service status"
sudo systemctl status "$API_SERVICE" --no-pager || warn "Service status returned non-zero"

step "[API] Checking live endpoint"
if curl -sI --max-time 10 "$API_HEALTH_URL" | head -n1 | grep -qE "200|301|302"; then
  success "API responding at ${API_HEALTH_URL}"
else
  warn "API did not respond as expected at ${API_HEALTH_URL}"
fi

if [[ "$DEPLOY_STAGING_ADMIN" == "1" ]]; then
  step "[Admin App] Pulling latest code from ${ADMIN_BRANCH}"
  cd "$ADMIN_DIR" || fail "Could not find ${ADMIN_DIR}"
  git pull origin "$ADMIN_BRANCH" || fail "git pull failed"
  success "Admin app code updated"

  step "[Admin App] Installing dependencies"
  npm install || fail "npm install failed"
  success "Dependencies installed"

  step "[Admin App] Building"
  npm run build || fail "npm run build failed"
  success "Build completed"

  step "Reloading nginx"
  sudo systemctl reload nginx || fail "nginx reload failed"
  success "nginx reloaded"
fi

echo -e "\n${GREEN}=== Staging backend deployment complete: $(date '+%Y-%m-%d %H:%M:%S') ===${RESET}\n"
