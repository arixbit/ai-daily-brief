#!/usr/bin/env python3
"""Generate four Kami-style X image pages from a daily brief JSON file."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "public" / "data" / "daily"
DEFAULT_OUTPUT_DIR = ROOT / "x-drafts"
KAMI_ROOT = Path("/Users/arix/.agents/skill-sources/kami")
KAMI_CSS = KAMI_ROOT / "styles.css"
LUO_FONT_URL = "https://cdn.jsdelivr.net/gh/tw93/Luo@main/dist/Luo-Regular.woff2"
X_TITLE_PREFIX = "AI 日报"
DEFAULT_X_COUNT = 12
ITEMS_PER_CARD = 3


def top_items(payload: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return sorted(payload["items"], key=lambda item: int(item.get("rank", 999)))[:count]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def x_title(date: str) -> str:
    value = dt.date.fromisoformat(date)
    return f"{X_TITLE_PREFIX}｜{value.month}月{value.day}日"


ADAPTER_CSS = """
@font-face {
  font-family: "Luo";
  src: url("__LUO_FONT_URL__") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
  unicode-range: U+4E00-9FFF, U+3400-4DBF, U+3000-303F, U+FF00-FFEF;
}
:root,
html[lang="zh-CN"] {
  --serif: "Luo", Seravek, Candara, Optima, "Iowan Old Style", Charter, Georgia,
           "Avenir Next", "Noto Sans CJK SC", sans-serif;
  --sans: var(--serif);
}
html,
body {
  width: 1200px;
  height: 1600px;
  margin: 0;
  overflow: hidden;
  background: var(--parchment);
}
body {
  font-family: var(--sans);
  color: var(--near-black);
  letter-spacing: 0;
  -webkit-font-smoothing: antialiased;
}
.sheet {
  width: 1200px;
  height: 1600px;
  padding: 78px 72px;
  box-sizing: border-box;
  position: relative;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.22), rgba(255,255,255,0) 24%),
    var(--parchment);
}
.kicker {
  font-family: var(--mono);
  font-size: 19px;
  color: var(--stone);
  letter-spacing: 0.8px;
  text-transform: uppercase;
  margin-bottom: 16px;
}
h1 {
  font-size: 54px;
  line-height: 1.08;
  margin: 0;
  color: var(--near-black);
  font-weight: 500;
}
.rule {
  height: 1px;
  background: var(--border-soft);
  margin: 28px 0 20px;
}
.story {
  padding: 24px 0 26px;
  border-bottom: 1px solid var(--border-soft);
}
.story:last-of-type {
  border-bottom: 0;
}
h2 {
  font-size: 35px;
  line-height: 1.2;
  margin: 0 0 14px;
  font-weight: 500;
}
p {
  margin: 0;
}
.summary {
  color: var(--dark-warm);
  font-size: 26px;
  line-height: 1.48;
}
.why {
  color: var(--brand);
  font-size: 25px;
  line-height: 1.44;
  margin-top: 15px;
}
.meta {
  display: flex;
  justify-content: space-between;
  gap: 28px;
  margin-top: 16px;
  color: var(--stone);
  font-family: var(--mono);
  font-size: 18px;
  line-height: 1.35;
}
.footer {
  position: absolute;
  left: 72px;
  right: 72px;
  bottom: 58px;
  display: flex;
  justify-content: space-between;
  color: var(--stone);
  font-family: var(--mono);
  font-size: 19px;
}
"""


def page_html(items: list[dict[str, Any]], date: str, start: int, total: int) -> str:
    sections = []
    for item in items:
        tags = "  ".join(f"#{tag}" for tag in item.get("tags", [])[:3])
        sections.append(
            f"""
            <section class="story">
              <h2>{esc(item["title_cn"])}</h2>
              <p class="summary">{esc(item.get("summary_cn", ""))}</p>
              <p class="why">{esc(item.get("why_it_matters_cn", ""))}</p>
              <div class="meta"><span>{esc(item.get("source", "公开来源"))}</span><span>{esc(tags)}</span></div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1200,height=1600,initial-scale=1">
  <title>{esc(x_title(date))}</title>
  <link rel="stylesheet" href="{KAMI_CSS.resolve().as_uri()}">
  <style>{ADAPTER_CSS.replace("__LUO_FONT_URL__", LUO_FONT_URL)}</style>
</head>
<body>
  <main class="sheet">
    <div class="kicker">ArixBit · AI Daily Brief · X Edition</div>
    <h1>{esc(x_title(date))}</h1>
    <div class="rule"></div>
    {"".join(sections)}
    <div class="footer"><span>公开来源整理</span><span>{start}-{start + len(items) - 1} / {total}</span></div>
  </main>
</body>
</html>
"""


def write_post_text(items: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    lines = [
        title,
        "",
        f"今日 {len(items)} 条 AI 新闻速览，见图。",
        "",
        "#AI #人工智能 #AI日报 #大模型",
        "",
    ]
    (output_dir / "post.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Kami-style X news card HTML.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--count", type=int, default=DEFAULT_X_COUNT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads((args.data_dir / f"{args.date}.json").read_text(encoding="utf-8"))

    output_dir = args.output_dir / f"{args.date}-kami-x"
    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    count = min(args.count, DEFAULT_X_COUNT)
    items = top_items(payload, count)
    for page, start in enumerate(range(0, len(items), ITEMS_PER_CARD), start=1):
        group = items[start : start + ITEMS_PER_CARD]
        filename = f"{page:02d}-news-{start + 1:02d}-{start + len(group):02d}.html"
        html = page_html(group, payload["date"], start + 1, len(items))
        (html_dir / filename).write_text(html, encoding="utf-8")

    title = x_title(payload["date"])
    write_post_text(items, output_dir, title)
    print(f"Generated Kami-based X news HTML: {output_dir}")
    print(f"HTML cards: {(len(items) + ITEMS_PER_CARD - 1) // ITEMS_PER_CARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
