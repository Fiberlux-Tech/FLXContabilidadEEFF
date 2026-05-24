#!/usr/bin/env bash
# Deploy the working tree this script lives in. Both prod and staging trees
# track main; the only difference is which systemd service gets restarted.
# Usage: ./deploy.sh
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(basename "$PWD")"

case "$DIR" in
  FLXContabilidad)
    SERVICE="flxcontabilidad"
    URL="http://10.100.50.4"
    ;;
  FLXContabilidad-staging)
    SERVICE="flxcontabilidad-staging"
    URL="http://10.100.50.4:8081"
    ;;
  *)
    echo "error: unknown working tree '$DIR' — deploy.sh only runs in FLXContabilidad or FLXContabilidad-staging" >&2
    exit 1
    ;;
esac

echo "==> Deploying $SERVICE from main"

git fetch origin
git checkout main
git pull --ff-only origin main

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
  ERROR_LOG="$PWD/backend/logs/error.log"
  if [ -f "$ERROR_LOG" ]; then
    echo "" >&2
    echo "--- last 30 lines of $ERROR_LOG ---" >&2
    tail -30 "$ERROR_LOG" >&2
  fi
  exit 1
fi

echo "==> Done. $URL should be serving HEAD of main."
