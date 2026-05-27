#!/usr/bin/env python3
"""Generate a Xiaohongshu image-card draft from one daily brief JSON file."""

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
XHS_TITLE = "AI 动态"
XHS_CONTENT_TYPE_DECLARATION = "笔记含AI合成内容"
XHS_COLLECTION = "AI 日报"
CARD_WIDTH = 1242
CARD_HEIGHT = 1656
PADDING = 96
FONT_REGULAR = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_BOLD = Path("/System/Library/Fonts/STHeiti Medium.ttc")


COLORS = {
    "background": "#FAF7EF",
    "ink": "#1F2933",
    "muted": "#657381",
    "hairline": "#E2D8C8",
    "accent": "#D9483B",
    "accent_dark": "#A9362D",
    "cream": "#F3EADB",
    "blue": "#E7EEF7",
    "mint": "#E8F3EC",
    "yellow": "#F7E7A6",
    "white": "#FFFDF8",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load the project card font."""

    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont) -> int:
    """Return rendered text width."""

    bbox = draw.textbbox((0, 0), text, font=text_font)
    return bbox[2] - bbox[0]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    text_font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    """Wrap mixed Chinese/English text by rendered width."""

    chunks = re.findall(r"[A-Za-z0-9_.:/+-]+|\s+|.", text.strip())
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

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]

    if max_lines and len(lines) == max_lines:
        last = lines[-1]
        while last and text_width(draw, f"{last}…", text_font) > max_width:
            last = last[:-1]
        lines[-1] = f"{last}…" if last and last != text else last
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int,
    max_lines: int | None = None,
) -> int:
    """Draw wrapped text and return the next y coordinate."""

    x, y = xy
    line_height = text_font.size + line_gap
    for line in wrap_text(draw, text, text_font, max_width, max_lines):
        draw.text((x, y), line, font=text_font, fill=fill)
        y += line_height
    return y


def new_card(index: int, total: int, section: str, date: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Create a card canvas with common header and footer."""

    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (40, 40, CARD_WIDTH - 40, CARD_HEIGHT - 40),
        radius=36,
        outline=COLORS["hairline"],
        width=3,
    )
    draw.text((PADDING, 74), "AI DAILY BRIEF", font=font(34, True), fill=COLORS["accent"])
    draw.text((CARD_WIDTH - PADDING - 130, 74), f"{index:02d}/{total:02d}", font=font(32, True), fill=COLORS["muted"])
    draw.text((PADDING, CARD_HEIGHT - 112), section, font=font(30, True), fill=COLORS["muted"])
    draw.text((CARD_WIDTH - PADDING - 160, CARD_HEIGHT - 112), date.replace("-", "."), font=font(30), fill=COLORS["muted"])
    return image, draw


def draw_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str | None = None) -> int:
    """Draw a large card title."""

    y = 190
    y = draw_wrapped(draw, title, (PADDING, y), font(76, True), COLORS["ink"], CARD_WIDTH - PADDING * 2, 20, 3)
    if subtitle:
        y += 26
        y = draw_wrapped(draw, subtitle, (PADDING, y), font(38), COLORS["muted"], CARD_WIDTH - PADDING * 2, 18, 3)
    return y + 44


def draw_pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: str) -> int:
    """Draw one small label pill."""

    text_font = font(28, True)
    width = text_width(draw, text, text_font) + 38
    draw.rounded_rectangle((x, y, x + width, y + 50), radius=25, fill=color)
    draw.text((x + 19, y + 7), text, font=text_font, fill=COLORS["ink"])
    return x + width + 14


def top_items(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Return the highest-ranked daily items."""

    return sorted(items, key=lambda item: int(item.get("rank", 999)))[:count]


def compact_summary(value: str, limit: int) -> str:
    """Trim one text field to a display-safe length."""

    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def card_cover(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render the cover card."""

    image, draw = new_card(1, total, "今日封面", payload["date"])
    y = draw_title(draw, "今天 AI 圈 5 件事", "从 24 条公开资讯里，压缩成一组快速读完的图文卡。")
    draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + 410), radius=34, fill=COLORS["white"])
    draw.text((PADDING + 42, y + 42), "今天的主线", font=font(40, True), fill=COLORS["accent_dark"])
    bullets = [
        "搜索平台开始治理 AI 投毒内容",
        "AI 安全审计进入多 agent 协作阶段",
        "编码 agent 继续升温，但工程风险被重新讨论",
        "推理加速和数学证明显示模型能力正在下沉到工具链",
    ]
    ty = y + 116
    for bullet in bullets:
        draw.text((PADDING + 44, ty), "•", font=font(40, True), fill=COLORS["accent"])
        ty = draw_wrapped(draw, bullet, (PADDING + 84, ty), font(36), COLORS["ink"], CARD_WIDTH - PADDING * 2 - 120, 14, 2)
        ty += 18
    draw.rounded_rectangle((PADDING, y + 462, CARD_WIDTH - PADDING, y + 610), radius=28, fill=COLORS["yellow"])
    draw.text((PADDING + 42, y + 504), "适合 2 分钟扫一遍今天 AI 圈变化", font=font(42, True), fill=COLORS["ink"])
    image.save(path)


def card_top5(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render the top-five list card."""

    image, draw = new_card(2, total, "先看重点", payload["date"])
    y = draw_title(draw, "最值得先看的 5 条", "按影响面、信号强度和工程相关性压缩。")
    for item in top_items(payload["items"], 5):
        box_h = 182
        draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + box_h), radius=28, fill=COLORS["white"])
        draw.text((PADDING + 34, y + 34), f"{item['rank']:02d}", font=font(44, True), fill=COLORS["accent"])
        draw_wrapped(
            draw,
            str(item["title_cn"]),
            (PADDING + 112, y + 28),
            font(38, True),
            COLORS["ink"],
            CARD_WIDTH - PADDING * 2 - 150,
            12,
            2,
        )
        draw.text((PADDING + 112, y + 122), str(item["source"]), font=font(26), fill=COLORS["muted"])
        y += box_h + 24
    image.save(path)


def card_trends(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render the trend card."""

    image, draw = new_card(3, total, "趋势判断", payload["date"])
    y = draw_title(draw, "今天透露的 3 个趋势", "不是罗列新闻，而是看它们指向哪里。")
    trends = [
        ("内容可信度", "谷歌治理 GEO 垃圾内容，说明搜索和 AI 摘要都会继续围绕“可信来源”重排。", COLORS["blue"]),
        ("安全自动化", "微软 MDASH 把漏洞研究拆给 100+ agent 协作，安全审计会变成 AI 原生工作流。", COLORS["mint"]),
        ("工程冷启动", "编码 agent 很有用，但 Hotz 的警告说明：原型速度提升后，验证成本会变成新瓶颈。", COLORS["cream"]),
    ]
    for title, body, color in trends:
        draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + 260), radius=30, fill=color)
        draw.text((PADDING + 42, y + 34), title, font=font(44, True), fill=COLORS["accent_dark"])
        draw_wrapped(draw, body, (PADDING + 42, y + 104), font(36), COLORS["ink"], CARD_WIDTH - PADDING * 2 - 84, 16, 4)
        y += 292
    image.save(path)


def card_tools(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render model/tool updates."""

    image, draw = new_card(4, total, "工具与模型", payload["date"])
    y = draw_title(draw, "工具链里的变化", "今天不只是在发模型，也在补工程化拼图。")
    picks = [item for item in payload["items"] if int(item.get("rank", 999)) in {5, 7, 8, 9, 10}]
    for item in picks[:4]:
        box_h = 250
        draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + box_h), radius=28, fill=COLORS["white"])
        draw.text((PADDING + 36, y + 34), str(item["source"]), font=font(28, True), fill=COLORS["accent"])
        draw_wrapped(draw, str(item["title_cn"]), (PADDING + 36, y + 82), font(38, True), COLORS["ink"], CARD_WIDTH - PADDING * 2 - 72, 12, 2)
        tags = [str(tag) for tag in item.get("tags", [])[:3]]
        tx = PADDING + 36
        for tag in tags:
            tx = draw_pill(draw, tx, y + 184, tag, COLORS["cream"])
        y += box_h + 22
    image.save(path)


def card_deep_dive(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render one focused item card."""

    item = next((row for row in payload["items"] if int(row.get("rank", 0)) == 2), payload["items"][0])
    image, draw = new_card(5, total, "重点展开", payload["date"])
    y = draw_title(draw, "今天最值得展开的一条", str(item["title_cn"]))
    draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + 560), radius=34, fill=COLORS["white"])
    draw.text((PADDING + 42, y + 42), "为什么重要", font=font(44, True), fill=COLORS["accent_dark"])
    y2 = draw_wrapped(
        draw,
        compact_summary(str(item["summary_cn"]), 190),
        (PADDING + 42, y + 118),
        font(38),
        COLORS["ink"],
        CARD_WIDTH - PADDING * 2 - 84,
        18,
        5,
    )
    y2 += 28
    draw.text((PADDING + 42, y2), "可以观察", font=font(38, True), fill=COLORS["accent_dark"])
    points = [
        "多 agent 协作是否真的能降低人工安全审计成本",
        "漏洞验证和误报过滤会不会成为下一阶段竞争点",
        "这类系统能否从安全领域迁移到普通代码评审",
    ]
    ty = y2 + 68
    for point in points:
        draw.text((PADDING + 46, ty), "•", font=font(34, True), fill=COLORS["accent"])
        ty = draw_wrapped(draw, point, (PADDING + 84, ty), font(32), COLORS["ink"], CARD_WIDTH - PADDING * 2 - 120, 12, 2)
        ty += 10
    image.save(path)


def card_close(payload: dict[str, Any], path: Path, total: int) -> None:
    """Render closing card without external link."""

    image, draw = new_card(6, total, "收尾", payload["date"])
    y = draw_title(draw, "今天可以记住这句话", None)
    draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + 460), radius=34, fill=COLORS["accent"])
    draw_wrapped(
        draw,
        "AI 正在从“谁的模型更强”，转向“谁能把模型放进可信、可验证、可维护的工作流”。",
        (PADDING + 54, y + 72),
        font(58, True),
        COLORS["white"],
        CARD_WIDTH - PADDING * 2 - 108,
        24,
        5,
    )
    y += 540
    notes = [
        "信息来自公开来源，已做中文整理。",
        "这组图文只保留今天最值得快速扫过的部分。",
        "适合收藏，晚上复盘 AI 圈变化。",
    ]
    for note in notes:
        draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + 124), radius=24, fill=COLORS["white"])
        draw.text((PADDING + 42, y + 38), note, font=font(36), fill=COLORS["ink"])
        y += 154
    image.save(path)


def write_post_text(payload: dict[str, Any], output_dir: Path) -> None:
    """Write Xiaohongshu title/body draft."""

    items = top_items(payload["items"], 5)
    lines = [
        f"# {XHS_TITLE}",
        "",
        "今天的 AI 简报整理好了。",
        "",
        "重点包括：",
        *[f"{idx}. {item['title_cn']}" for idx, item in enumerate(items[:5], start=1)],
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
    """Write manual Xiaohongshu publishing settings."""

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


def write_contact_sheet(card_paths: list[Path], output_dir: Path) -> None:
    """Write a thumbnail overview for quick review."""

    thumb_w = 360
    thumb_h = int(thumb_w * CARD_HEIGHT / CARD_WIDTH)
    gap = 28
    cols = 3
    rows = (len(card_paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * thumb_h + (rows + 1) * gap), "#EEE8DC")
    for index, path in enumerate(card_paths):
        image = Image.open(path)
        image.thumbnail((thumb_w, thumb_h))
        x = gap + (index % cols) * (thumb_w + gap)
        y = gap + (index // cols) * (thumb_h + gap)
        sheet.paste(image, (x, y))
    sheet.save(output_dir / "contact-sheet.png")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(description="Generate Xiaohongshu draft cards.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    """Generate one draft package."""

    args = parse_args()
    data_path = args.data_dir / f"{args.date}.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))

    output_dir = args.output_dir / args.date
    output_dir.mkdir(parents=True, exist_ok=True)
    card_dir = output_dir / "cards"
    card_dir.mkdir(exist_ok=True)

    renderers = [card_cover, card_top5, card_trends, card_tools, card_deep_dive, card_close]
    card_paths: list[Path] = []
    for index, renderer in enumerate(renderers, start=1):
        path = card_dir / f"{index:02d}.png"
        renderer(payload, path, len(renderers))
        card_paths.append(path)

    write_contact_sheet(card_paths, output_dir)
    write_post_text(payload, output_dir)
    write_publish_settings(output_dir)
    print(f"Generated Xiaohongshu draft: {output_dir}")
    print(f"Cards: {len(card_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
