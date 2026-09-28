#!/usr/bin/env bash
# Run on the staging server (not production). Typical flow:
#
#   deploy-staging-backend
#   # or: bash /var/www/staging-api/scripts/deploy_staging_backend.sh
#
# Post-deploy (migrations also run in deploy script; this adds sample seed):
#   bash /var/www/staging-api/scripts/staging-post-deploy.sh
#
set -euo pipefail

APP_ROOT="${STAGING_API_ROOT:-/var/www/staging-api}"
cd "$APP_ROOT"

if [[ -f venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "==> Alembic upgrade"
alembic upgrade head

echo "==> Sample seed (idempotent)"
python -m db.seed_sample --yes

echo "==> Staging post-deploy done"
