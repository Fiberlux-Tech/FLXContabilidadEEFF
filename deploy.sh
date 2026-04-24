#!/usr/bin/env bash
# Deploy the working tree this script lives in.
# Usage: run from the root of the working tree (./deploy.sh).
# Target branch + systemd service are inferred from the directory name.
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(basename "$PWD")"

case "$DIR" in
  FLXContabilidad)
    SERVICE="flxcontabilidad"
    BRANCH="main"
    URL="http://10.100.50.4"
    ;;
  FLXContabilidad-staging)
    SERVICE="flxcontabilidad-staging"
    BRANCH="dev"
    URL="http://10.100.50.4:8081"
    ;;
  *)
    echo "error: unknown working tree '$DIR' — deploy.sh only runs in FLXContabilidad or FLXContabilidad-staging" >&2
    exit 1
    ;;
esac

echo "==> Deploying $SERVICE from branch $BRANCH"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  echo "error: expected branch $BRANCH in $DIR, found $CURRENT_BRANCH" >&2
  echo "fix with: git checkout $BRANCH" >&2
  exit 1
fi

git fetch origin
git pull --ff-only origin "$BRANCH"

echo "==> Building frontend"
cd frontend
npm ci
npm run build
cd ..

echo "==> Restarting $SERVICE (sudo password may be required)"
sudo systemctl restart "$SERVICE"

sleep 2
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "error: $SERVICE failed to start" >&2
  systemctl status "$SERVICE" --no-pager -l | head -20 >&2
  exit 1
fi

echo "==> Done. $URL should be serving HEAD of $BRANCH."
