#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

python3 scripts/generate_daily.py

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git add public/data
  if ! git diff --cached --quiet; then
    git commit -m "Update AI brief $(date +%F)"
    git push
  fi
fi

