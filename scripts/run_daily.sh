#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Use virtual environment
if [ -d venv ]; then
  source venv/bin/activate
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

target_date=""
previous_arg=""
for arg in "$@"; do
  if [[ "$previous_arg" == "--date" ]]; then
    target_date="$arg"
    break
  fi
  previous_arg="$arg"
done

python scripts/generate_daily.py "$@"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [[ -z "$target_date" ]]; then
    target_date="$(python3 scripts/latest_publishable_date.py)"
  fi
  git add public/data/manifest.json "public/data/daily/${target_date}.json"
  if ! git diff --cached --quiet; then
    git commit -m "Update AI brief ${target_date}"
    git push
  fi
fi
