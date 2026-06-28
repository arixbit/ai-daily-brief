#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Use virtual environment
if [ -d venv ]; then
  source venv/bin/activate
fi

count="${X_CARD_COUNT:-12}"
date_arg=""
publish=1
publisher="${X_PUBLISHER:-api}"
api_args=()
browser_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      if [[ $# -lt 2 ]]; then
        echo "X 发布失败：--date 缺少日期参数。"
        exit 1
      fi
      date_arg="$2"
      shift 2
      ;;
    --count)
      if [[ $# -lt 2 ]]; then
        echo "X 发布失败：--count 缺少数量参数。"
        exit 1
      fi
      count="$2"
      shift 2
      ;;
    --no-publish)
      publish=0
      shift
      ;;
    --dry-run)
      api_args+=(--dry-run)
      browser_args+=(--dry-run)
      shift
      ;;
    --headless)
      publisher="browser"
      browser_args+=(--headless)
      shift
      ;;
    --profile-dir)
      if [[ $# -lt 2 ]]; then
        echo "X 发布失败：--profile-dir 缺少路径参数。"
        exit 1
      fi
      publisher="browser"
      browser_args+=(--profile-dir "$2")
      shift 2
      ;;
    --login-wait)
      if [[ $# -lt 2 ]]; then
        echo "X 发布失败：--login-wait 缺少秒数参数。"
        exit 1
      fi
      publisher="browser"
      browser_args+=(--login-wait "$2")
      shift 2
      ;;
    --api)
      publisher="api"
      shift
      ;;
    --browser)
      publisher="browser"
      shift
      ;;
    *)
      echo "X 发布失败：不支持的参数 $1"
      exit 1
      ;;
  esac
done

if [[ -z "$date_arg" ]]; then
  date_arg="$(python3 scripts/latest_publishable_date.py)"
fi

python3 scripts/generate_x_kami_html.py --date "$date_arg" --count "$count"
python3 scripts/render_x_kami_html.py --date "$date_arg"
actual_count="$(find "x-drafts/${date_arg}-kami-x/cards" -maxdepth 1 -name '*.png' | wc -l | tr -d ' ')"

if (( publish == 0 )); then
  echo "X 图片已生成：${date_arg}，${actual_count} 张。"
  exit 0
fi

if [[ "$publisher" == "api" ]]; then
  if (( ${#api_args[@]} == 0 )); then
    node scripts/publish_x_api.mjs --date "$date_arg"
  else
    node scripts/publish_x_api.mjs --date "$date_arg" "${api_args[@]}"
  fi
elif [[ "$publisher" == "browser" ]]; then
  if (( ${#browser_args[@]} == 0 )); then
    node scripts/publish_x.mjs --date "$date_arg"
  else
    node scripts/publish_x.mjs --date "$date_arg" "${browser_args[@]}"
  fi
else
  echo "X 发布失败：不支持的发布器 ${publisher}"
  exit 1
fi
