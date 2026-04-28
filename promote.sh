#!/usr/bin/env bash
# Promote dev → main and deploy to prod.
# Run from the prod working tree (~/FLXContabilidad).
# Fast-forward only: bails if main has commits that aren't on dev.
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(basename "$PWD")"

if [ "$DIR" != "FLXContabilidad" ]; then
  echo "error: promote.sh only runs in FLXContabilidad (prod tree), not '$DIR'" >&2
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "error: expected branch main, found $CURRENT_BRANCH" >&2
  echo "fix with: git checkout main" >&2
  exit 1
fi

if ! git diff-index --quiet HEAD --; then
  echo "error: working tree has uncommitted changes" >&2
  git status --short >&2
  exit 1
fi

echo "==> Fetching origin"
git fetch origin

LOCAL_MAIN="$(git rev-parse main)"
REMOTE_MAIN="$(git rev-parse origin/main)"
REMOTE_DEV="$(git rev-parse origin/dev)"

if [ "$LOCAL_MAIN" != "$REMOTE_MAIN" ]; then
  echo "error: local main ($LOCAL_MAIN) differs from origin/main ($REMOTE_MAIN)" >&2
  echo "fix with: git pull --ff-only origin main" >&2
  exit 1
fi

if [ "$REMOTE_MAIN" = "$REMOTE_DEV" ]; then
  echo "==> Nothing to promote: origin/dev == origin/main"
  exit 0
fi

# Verify dev is ahead of main (fast-forward possible).
if ! git merge-base --is-ancestor "$REMOTE_MAIN" "$REMOTE_DEV"; then
  echo "error: origin/main is not an ancestor of origin/dev — branches have diverged" >&2
  echo "this means someone committed directly to main. resolve manually." >&2
  exit 1
fi

echo "==> Commits to promote (origin/main..origin/dev):"
git log --oneline "$REMOTE_MAIN..$REMOTE_DEV"
echo ""
read -r -p "Promote these to main and deploy to prod? [y/N] " REPLY
case "$REPLY" in
  y|Y|yes|YES) ;;
  *) echo "aborted."; exit 1 ;;
esac

echo "==> Fast-forwarding main to origin/dev"
git merge --ff-only origin/dev

echo "==> Pushing main"
git push origin main

echo "==> Running deploy.sh"
exec ./deploy.sh
