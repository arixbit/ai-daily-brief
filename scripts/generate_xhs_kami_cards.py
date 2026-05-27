#!/usr/bin/env python3
"""Generate Kami-inspired Xiaohongshu image cards from a daily brief JSON file."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "public" / "data" / "daily"
DEFAULT_OUTPUT_DIR = ROOT / "xhs-drafts"
KAMI_FONT_DIR = Path("/Users/arix/.agents/skill-sources/kami/assets/fonts")
XHS_TITLE = "AI 动态"
XHS_CONTENT_TYPE_DECLARATION = "笔记含AI合成内容"
XHS_COLLECTION = "AI 日报"

CARD_WIDTH = 1242
CARD_HEIGHT = 1656
PAGE_PAD = 96

COLORS = {
    "parchment": "#f5f4ed",
    "ivory": "#faf9f5",
    "warm_sand": "#e8e6dc",
    "brand": "#1B365D",
    "brand_soft": "#EEF2F7",
    "near_black": "#141413",
    "dark_warm": "#3d3d3a",
    "olive": "#504e49",
    "stone": "#6b6a64",
    "border": "#e8e6dc",
    "border_soft": "#e5e3d8",
}


def load_font(size: int, medium: bool = False) -> ImageFont.FreeTypeFont:
    """Load Kami's CJK serif when available, falling back to macOS CJK fonts."""

    kami_font = KAMI_FONT_DIR / ("TsangerJinKai02-W05.ttf" if medium else "TsangerJinKai02-W04.ttf")
    if kami_font.exists():
        return ImageFont.truetype(str(kami_font), size=size)

    fallbacks = [
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    ]
    for path in fallbacks:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=text_font)
    return bbox[2] - bbox[0]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    text_font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    chunks = re.findall(r"[A-Za-z0-9_.:/+-]+|\s+|.", re.sub(r"\s+", " ", text.strip()))
    lines: list[str] = []
    current = ""

    for chunk in chunks:
        candidate = f"{current}{chunk}"
        if text_width(draw, candidate.strip(), text_font) <= max_width:
            current = candidate
            continue

        if current.strip():
            lines.append(current.strip())
        current = chunk.strip()

        if max_lines and len(lines) >= max_lines:
            break

    if current.strip() and (not max_lines or len(lines) < max_lines):
        lines.append(current.strip())

    if max_lines and len(lines) == max_lines:
        original = lines[-1]
        shortened = original
        while shortened and text_width(draw, f"{shortened}…", text_font) > max_width:
            shortened = shortened[:-1]
        if shortened != original:
            lines[-1] = f"{shortened}…"

    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_height: int,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, text_font, max_width, max_lines):
        draw.text((x, y), line, font=text_font, fill=fill)
        y += line_height
    return y


def compact(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip("，。；、 ") + "…"


def top_items(payload: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
    return sorted(payload["items"], key=lambda item: int(item.get("rank", 999)))[:count]


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLORS["parchment"])
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (44, 44, CARD_WIDTH - 44, CARD_HEIGHT - 44),
        radius=32,
        outline=COLORS["border_soft"],
        width=1,
    )
    return image, draw


def draw_header(draw: ImageDraw.ImageDraw, label: str, date: str) -> None:
    small = load_font(30, medium=True)
    draw.text((PAGE_PAD, 78), label.upper(), font=small, fill=COLORS["brand"])
    date_text = date.replace("-", ".")
    draw.text(
        (CARD_WIDTH - PAGE_PAD - text_width(draw, date_text, small), 78),
        date_text,
        font=small,
        fill=COLORS["stone"],
    )


def draw_footer(draw: ImageDraw.ImageDraw, index: int, total: int) -> None:
    tiny = load_font(28)
    left = "ArixBit · AI Daily Brief"
    right = f"{index:02d}/{total:02d}"
    draw.text((PAGE_PAD, CARD_HEIGHT - 112), left, font=tiny, fill=COLORS["stone"])
    draw.text(
        (CARD_WIDTH - PAGE_PAD - text_width(draw, right, tiny), CARD_HEIGHT - 112),
        right,
        font=tiny,
        fill=COLORS["stone"],
    )


def draw_title_block(draw: ImageDraw.ImageDraw, title: str, y: int, max_lines: int = 4) -> int:
    draw.rounded_rectangle((PAGE_PAD, y + 8, PAGE_PAD + 10, y + 104), radius=5, fill=COLORS["brand"])
    return draw_wrapped(
        draw,
        title,
        (PAGE_PAD + 34, y),
        load_font(58, medium=True),
        COLORS["near_black"],
        CARD_WIDTH - PAGE_PAD * 2 - 34,
        74,
        max_lines,
    )


def draw_tags(draw: ImageDraw.ImageDraw, tags: list[str], y: int) -> int:
    font = load_font(28, medium=True)
    x = PAGE_PAD
    for tag in tags[:4]:
        label = f"#{tag}"
        width = text_width(draw, label, font) + 36
        if x + width > CARD_WIDTH - PAGE_PAD:
            break
        draw.rounded_rectangle((x, y, x + width, y + 48), radius=10, fill=COLORS["brand_soft"])
        draw.text((x + 18, y + 8), label, font=font, fill=COLORS["brand"])
        x += width + 14
    return y + 70


def draw_section(
    draw: ImageDraw.ImageDraw,
    label: str,
    body: str,
    y: int,
    max_lines: int,
) -> int:
    label_font = load_font(32, medium=True)
    body_font = load_font(37)
    draw.text((PAGE_PAD, y), label, font=label_font, fill=COLORS["brand"])
    y += 52
    y = draw_wrapped(
        draw,
        body,
        (PAGE_PAD, y),
        body_font,
        COLORS["dark_warm"],
        CARD_WIDTH - PAGE_PAD * 2,
        55,
        max_lines,
    )
    return y + 36


def draw_cover(payload: dict[str, Any], path: Path, total: int) -> None:
    image, draw = new_canvas()
    draw_header(draw, "ai daily", payload["date"])

    y = 238
    y = draw_title_block(draw, "今日 AI 圈 5 个信号", y, 2)
    y += 26
    y = draw_wrapped(
        draw,
        "把同一条信息完整放在同一张图里，不交给平台按字数切卡。",
        (PAGE_PAD, y),
        load_font(40),
        COLORS["olive"],
        CARD_WIDTH - PAGE_PAD * 2,
        58,
        2,
    )

    y += 80
    row_font = load_font(38, medium=True)
    meta_font = load_font(27)
    for item in top_items(payload):
        row_top = y
        rank = f"{int(item['rank']):02d}"
        draw.text((PAGE_PAD, row_top + 6), rank, font=load_font(38, medium=True), fill=COLORS["brand"])
        draw_wrapped(
            draw,
            str(item["title_cn"]),
            (PAGE_PAD + 84, row_top),
            row_font,
            COLORS["near_black"],
            CARD_WIDTH - PAGE_PAD * 2 - 104,
            46,
            2,
        )
        draw.text((PAGE_PAD + 84, row_top + 76), str(item.get("source", "")), font=meta_font, fill=COLORS["stone"])
        y += 126
        draw.line((PAGE_PAD, y, CARD_WIDTH - PAGE_PAD, y), fill=COLORS["border"], width=1)
        y += 34

    draw_footer(draw, 1, total)
    image.save(path)


def draw_item_card(item: dict[str, Any], date: str, index: int, total: int, path: Path) -> None:
    image, draw = new_canvas()
    rank = int(item["rank"])
    draw_header(draw, f"signal {rank:02d}", date)

    y = 190
    y = draw_title_block(draw, str(item["title_cn"]), y, 4)
    y += 20
    y = draw_tags(draw, [str(tag) for tag in item.get("tags", [])], y)

    y += 12
    y = draw_section(draw, "信号", compact(str(item.get("summary_cn", "")), 175), y, 8)

    draw.line((PAGE_PAD, y, CARD_WIDTH - PAGE_PAD, y), fill=COLORS["border"], width=2)
    y += 34
    draw.text((PAGE_PAD, y), "为什么重要", font=load_font(32, medium=True), fill=COLORS["brand"])
    draw_wrapped(
        draw,
        compact(str(item.get("why_it_matters_cn", "")), 110),
        (PAGE_PAD, y + 58),
        load_font(35),
        COLORS["dark_warm"],
        CARD_WIDTH - PAGE_PAD * 2,
        52,
        4,
    )

    source = f"来源 · {item.get('source', '公开来源')}"
    draw.text((PAGE_PAD, CARD_HEIGHT - 178), source, font=load_font(28), fill=COLORS["stone"])
    draw_footer(draw, index, total)
    image.save(path)


def draw_close(payload: dict[str, Any], path: Path, total: int) -> None:
    image, draw = new_canvas()
    draw_header(draw, "takeaway", payload["date"])

    y = 244
    y = draw_title_block(draw, "今天的主线", y, 2)
    y += 56

    takeaways = [
        ("内容可信度", "搜索与 AI 摘要会继续惩罚“迎合模型”的垃圾内容，可信来源会变成新的护城河。"),
        ("Agent 工程化", "安全审计、编码、验证都在 agent 化，但真正的门槛会从生成速度转向验证流程。"),
        ("推理效率", "多 Token 预测和投机解码让模型能力继续下沉到日常工具链。"),
    ]
    for title, body in takeaways:
        draw.text((PAGE_PAD, y), title, font=load_font(40, medium=True), fill=COLORS["brand"])
        draw_wrapped(
            draw,
            body,
            (PAGE_PAD, y + 58),
            load_font(34),
            COLORS["dark_warm"],
            CARD_WIDTH - PAGE_PAD * 2,
            50,
            3,
        )
        y += 206
        draw.line((PAGE_PAD, y, CARD_WIDTH - PAGE_PAD, y), fill=COLORS["border"], width=1)
        y += 34

    y += 34
    draw.line((PAGE_PAD, y, CARD_WIDTH - PAGE_PAD, y), fill=COLORS["border"], width=2)
    y += 36
    draw_wrapped(
        draw,
        "我的观察：AI 的竞争正在从“谁的模型更强”，转向“谁能把模型放进可信、可验证、可维护的工作流”。",
        (PAGE_PAD, y),
        load_font(42, medium=True),
        COLORS["near_black"],
        CARD_WIDTH - PAGE_PAD * 2,
        60,
        4,
    )

    draw_footer(draw, total, total)
    image.save(path)


def write_contact_sheet(card_paths: list[Path], output_dir: Path) -> None:
    thumb_w = 330
    thumb_h = int(thumb_w * CARD_HEIGHT / CARD_WIDTH)
    gap = 24
    cols = 4
    rows = (len(card_paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * thumb_h + (rows + 1) * gap), COLORS["parchment"])
    for idx, path in enumerate(card_paths):
        image = Image.open(path)
        image.thumbnail((thumb_w, thumb_h))
        x = gap + (idx % cols) * (thumb_w + gap)
        y = gap + (idx // cols) * (thumb_h + gap)
        sheet.paste(image, (x, y))
    sheet.save(output_dir / "contact-sheet.png")


def write_post_text(payload: dict[str, Any], output_dir: Path) -> None:
    items = top_items(payload)
    lines = [
        f"# {XHS_TITLE}",
        "",
        "今天的 AI 简报整理好了。",
        "",
        "重点包括：",
        *[f"{idx}. {item['title_cn']}" for idx, item in enumerate(items, start=1)],
        "",
        "我的观察：AI 的竞争正在从单点模型能力，转向内容可信度、安全自动化、推理效率和 agent 工程化。",
        "",
        "信息来自公开来源，已做中文整理。",
        "",
        "#AI #人工智能 #大模型 #AI工具 #AI日报 #Agent #科技资讯",
        "",
    ]
    (output_dir / "post.md").write_text("\n".join(lines), encoding="utf-8")


def write_publish_settings(output_dir: Path) -> None:
    lines = [
        "# 小红书发布设置",
        "",
        f"标题：{XHS_TITLE}",
        f"内容类型声明：{XHS_CONTENT_TYPE_DECLARATION}",
        "原创声明：开启",
        f"合集：{XHS_COLLECTION}",
        "",
    ]
    (output_dir / "publish-settings.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Kami-style Xiaohongshu image cards.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_path = args.data_dir / f"{args.date}.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))

    output_dir = args.output_dir / f"{args.date}-kami"
    card_dir = output_dir / "cards"
    card_dir.mkdir(parents=True, exist_ok=True)

    items = top_items(payload)
    total = len(items) + 2
    card_paths: list[Path] = []

    cover_path = card_dir / "01-cover.png"
    draw_cover(payload, cover_path, total)
    card_paths.append(cover_path)

    for offset, item in enumerate(items, start=2):
        path = card_dir / f"{offset:02d}-signal-{int(item['rank']):02d}.png"
        draw_item_card(item, payload["date"], offset, total, path)
        card_paths.append(path)

    close_path = card_dir / f"{total:02d}-takeaway.png"
    draw_close(payload, close_path, total)
    card_paths.append(close_path)

    write_contact_sheet(card_paths, output_dir)
    write_post_text(payload, output_dir)
    write_publish_settings(output_dir)
    print(f"Generated Kami-style XHS cards: {output_dir}")
    print(f"Cards: {len(card_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
