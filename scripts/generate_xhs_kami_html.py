#!/usr/bin/env python3
"""Generate one Kami-based Xiaohongshu image page per news item."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "public" / "data" / "daily"
DEFAULT_OUTPUT_DIR = ROOT / "xhs-drafts"
KAMI_ROOT = Path("/Users/arix/.agents/skill-sources/kami")
KAMI_CSS = KAMI_ROOT / "styles.css"
LUO_FONT_URL = "https://cdn.jsdelivr.net/gh/tw93/Luo@main/dist/Luo-Regular.woff2"
XHS_TITLE_PREFIX = "AI 日报"
XHS_CONTENT_TYPE_DECLARATION = "笔记含AI合成内容"
XHS_COLLECTION = "AI 日报"
DEFAULT_XHS_COUNT = 15


def compact(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip("，。；、 ") + "…"


def top_items(payload: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return sorted(payload["items"], key=lambda item: int(item.get("rank", 999)))[:count]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def xhs_title(date: str) -> str:
    value = dt.date.fromisoformat(date)
    return f"{XHS_TITLE_PREFIX}｜{value.month}月{value.day}日"


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
html, body {
  width: 1242px;
  height: 1656px;
  overflow: hidden;
}
body {
  background: var(--parchment);
  font-family: var(--sans);
}
.xhs-card {
  width: 1242px;
  height: 1656px;
  max-width: none;
  margin: 0;
  padding: 108px 96px 132px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: none;
}
.xhs-card .hero {
  padding: 82px 0 34px;
  margin: 0 0 44px;
}
.xhs-card .hero h1 {
  font-size: 80px;
  line-height: 1.14;
  letter-spacing: 0;
  margin-bottom: 0;
}
.xhs-card .section-head {
  margin-bottom: 18px;
}
.xhs-card .section-num,
.xhs-card .eyebrow {
  color: var(--brand);
}
.xhs-card .eyebrow {
  font-size: 18px;
  letter-spacing: 0.8px;
  margin-bottom: 22px;
}
.xhs-card section {
  margin-bottom: 44px;
}
.xhs-card .xhs-body {
  margin-top: 0;
  margin-bottom: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.xhs-card .xhs-block {
  padding: 0 0 40px;
  border-bottom: 1px solid var(--border-soft);
}
.xhs-card .xhs-block + .xhs-block {
  margin-top: 46px;
}
.xhs-card .xhs-lower {
  margin-top: auto;
}
.xhs-card .section-lede {
  font-size: 45px;
  line-height: 1.42;
  margin-top: 0;
}
.xhs-card .xhs-body .manifesto {
  font-size: 47px;
  line-height: 1.42;
  letter-spacing: 0.02em;
  margin: 0;
  padding-left: 34px;
  border-left: 5px solid var(--brand);
}
.xhs-card .rules {
  grid-template-columns: 1fr;
}
.xhs-card .rules li {
  grid-template-columns: 44px 1fr;
  padding: 20px 0;
  border-right: none !important;
}
.xhs-card .rules li:nth-child(even) {
  padding-left: 0;
}
.xhs-card .rules .n {
  font-size: 28px;
}
.xhs-card .rules p {
  font-size: 30px;
  line-height: 1.45;
}
.xhs-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}
.xhs-tag {
  background: #EEF2F7;
  color: var(--brand);
  border-radius: 2px;
  padding: 5px 12px;
  font-family: var(--mono);
  font-size: 26px;
  letter-spacing: 0.3px;
}
.xhs-meta {
  position: absolute;
  left: 96px;
  right: 96px;
  bottom: 72px;
  display: flex;
  justify-content: space-between;
  color: var(--stone);
  font-family: var(--mono);
  font-size: 23px;
  line-height: 1.4;
}
.xhs-source {
  margin-top: 32px;
  color: var(--stone);
  font-size: 32px;
}
"""


def page_html(item: dict[str, Any], date: str, index: int, total: int) -> str:
    tags = "".join(f'<span class="xhs-tag">#{esc(tag)}</span>' for tag in item.get("tags", [])[:4])
    summary = compact(str(item.get("summary_cn", "")), 150)
    why = compact(str(item.get("why_it_matters_cn", "")), 105)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1242,height=1656,initial-scale=1">
  <title>{esc(item["title_cn"])}</title>
  <link rel="stylesheet" href="{KAMI_CSS.resolve().as_uri()}">
  <style>{ADAPTER_CSS.replace("__LUO_FONT_URL__", LUO_FONT_URL)}</style>
</head>
<body>
  <main class="page xhs-card">
    <section class="hero">
      <p class="eyebrow">AI Daily · {esc(date.replace("-", "."))}</p>
      <h1>{esc(item["title_cn"])}</h1>
      <div class="xhs-tags">{tags}</div>
    </section>

    <section class="xhs-body">
      <div class="xhs-block">
        <p class="section-lede">{esc(summary)}</p>
      </div>
      <div class="xhs-lower">
        <div class="xhs-block">
          <p class="manifesto">{esc(why)}</p>
        </div>
        <p class="xhs-source">来源 · {esc(item.get("source", "公开来源"))}</p>
      </div>
    </section>

    <div class="xhs-meta"><span>ArixBit · AI Daily Brief</span><span>{index:02d}/{total:02d}</span></div>
  </main>
</body>
</html>
"""


def write_post_text(items: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    lines = [
        f"# {title}",
        "",
        f"今天整理了 {len(items)} 条 AI 相关资讯，每条新闻对应一张图。",
        "",
        *[f"{idx}. {item['title_cn']}" for idx, item in enumerate(items, start=1)],
        "",
        "信息来自公开来源，已做中文整理。",
        "",
        "#AI #人工智能 #大模型 #AI工具 #AI日报 #Agent #科技资讯",
        "",
    ]
    (output_dir / "post.md").write_text("\n".join(lines), encoding="utf-8")


def write_publish_settings(output_dir: Path, title: str) -> None:
    lines = [
        "# 小红书发布设置",
        "",
        f"标题：{title}",
        f"内容类型声明：{XHS_CONTENT_TYPE_DECLARATION}",
        "原创声明：开启",
        f"合集：{XHS_COLLECTION}",
        "",
    ]
    (output_dir / "publish-settings.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Kami-based XHS news card HTML.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--count", type=int, default=DEFAULT_XHS_COUNT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads((args.data_dir / f"{args.date}.json").read_text(encoding="utf-8"))

    output_dir = args.output_dir / f"{args.date}-kami-news"
    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    items = top_items(payload, args.count)
    for index, item in enumerate(items, start=1):
        filename = f"{index:02d}-news-{int(item['rank']):02d}.html"
        (html_dir / filename).write_text(page_html(item, payload["date"], index, len(items)), encoding="utf-8")

    title = xhs_title(payload["date"])
    write_post_text(items, output_dir, title)
    write_publish_settings(output_dir, title)
    print(f"Generated Kami-based XHS news HTML: {output_dir}")
    print(f"HTML cards: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
