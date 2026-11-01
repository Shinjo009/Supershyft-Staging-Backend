#!/usr/bin/env bash
# Run on the staging server (not production). Typical flow after `git push staging main`:
#
#   deploy-staging-backend
#   bash /var/www/staging-api/scripts/staging-post-deploy.sh
#   deploy-staging-frontend
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

echo "==> Minimal direct content backfill (idempotent)"
python scripts/backfill_minimal_direct_content.py

echo "==> Cutover readiness (before Alembic)"
python scripts/verify_notification_cutover_ready.py

echo "==> Alembic upgrade"
alembic upgrade head

echo "==> Sample seed (idempotent)"
python -m db.seed_sample --yes

echo "==> Staging post-deploy done"
