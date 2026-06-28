#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Use virtual environment
if [ -d venv ]; then
  source venv/bin/activate
fi

count="${XHS_CARD_COUNT:-15}"
date_arg=""
publish=1
publisher_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      if [[ $# -lt 2 ]]; then
        echo "小红书发布失败：--date 缺少日期参数。"
        exit 1
      fi
      date_arg="$2"
      shift 2
      ;;
    --count)
      if [[ $# -lt 2 ]]; then
        echo "小红书发布失败：--count 缺少数量参数。"
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
      publisher_args+=(--dry-run)
      shift
      ;;
    --headless)
      publisher_args+=(--headless)
      shift
      ;;
    --profile-dir)
      if [[ $# -lt 2 ]]; then
        echo "小红书发布失败：--profile-dir 缺少路径参数。"
        exit 1
      fi
      publisher_args+=(--profile-dir "$2")
      shift 2
      ;;
    --login-wait)
      if [[ $# -lt 2 ]]; then
        echo "小红书发布失败：--login-wait 缺少秒数参数。"
        exit 1
      fi
      publisher_args+=(--login-wait "$2")
      shift 2
      ;;
    *)
      echo "小红书发布失败：不支持的参数 $1"
      exit 1
      ;;
  esac
done

if [[ -z "$date_arg" ]]; then
  date_arg="$(python3 scripts/latest_publishable_date.py)"
fi

python3 scripts/generate_xhs_kami_html.py --date "$date_arg" --count "$count"
python3 scripts/render_xhs_kami_html.py --date "$date_arg"
actual_count="$(find "xhs-drafts/${date_arg}-kami-news/cards" -maxdepth 1 -name '*.png' | wc -l | tr -d ' ')"

if (( publish == 0 )); then
  echo "小红书图片已生成：${date_arg}，${actual_count} 张。"
  exit 0
fi

if (( ${#publisher_args[@]} == 0 )); then
  node scripts/publish_xhs.mjs --date "$date_arg"
else
  node scripts/publish_xhs.mjs --date "$date_arg" "${publisher_args[@]}"
fi
