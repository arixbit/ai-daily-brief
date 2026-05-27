#!/usr/bin/env python3
"""Render Kami-style Xiaohongshu HTML cards to PNG with Chrome."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "xhs-drafts"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CARD_WIDTH = 1242
CARD_HEIGHT = 1656


def render_card(html_path: Path, png_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="xhs-kami-chrome-", dir="/private/tmp") as profile:
        command = [
            str(CHROME),
            "--headless",
            "--disable-background-networking",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-default-browser-check",
            "--no-first-run",
            "--allow-file-access-from-files",
            f"--user-data-dir={profile}",
            f"--window-size={CARD_WIDTH},{CARD_HEIGHT}",
            f"--screenshot={png_path}",
            html_path.resolve().as_uri(),
        ]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 20
        try:
            while time.monotonic() < deadline:
                if png_path.exists() and png_path.stat().st_size > 0:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return
                if proc.poll() is not None:
                    if proc.returncode != 0:
                        stdout, stderr = proc.communicate()
                        raise RuntimeError(f"Chrome failed for {html_path}\n{stdout}\n{stderr}")
                    return
                time.sleep(0.2)
            proc.kill()
            if png_path.exists() and png_path.stat().st_size > 0:
                return
            raise RuntimeError(f"Chrome timed out before writing {png_path}")
        finally:
            if proc.poll() is None:
                proc.kill()


def write_contact_sheet(card_paths: list[Path], output_dir: Path) -> None:
    thumb_w = 330
    thumb_h = int(thumb_w * CARD_HEIGHT / CARD_WIDTH)
    gap = 24
    cols = 4
    rows = (len(card_paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * thumb_h + (rows + 1) * gap), "#f5f4ed")
    for idx, path in enumerate(card_paths):
        image = Image.open(path)
        image.thumbnail((thumb_w, thumb_h))
        x = gap + (idx % cols) * (thumb_w + gap)
        y = gap + (idx // cols) * (thumb_h + gap)
        sheet.paste(image, (x, y))
    sheet.save(output_dir / "contact-sheet.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Kami-style XHS HTML cards to PNG.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir / f"{args.date}-kami-news"
    html_dir = output_dir / "html"
    card_dir = output_dir / "cards"
    if card_dir.exists():
        shutil.rmtree(card_dir)
    card_dir.mkdir(parents=True, exist_ok=True)

    html_paths = sorted(html_dir.glob("*.html"))
    if not html_paths:
        raise SystemExit(f"No HTML cards found in {html_dir}")

    card_paths: list[Path] = []
    for html_path in html_paths:
        png_path = card_dir / f"{html_path.stem}.png"
        render_card(html_path, png_path)
        card_paths.append(png_path)

    write_contact_sheet(card_paths, output_dir)
    print(f"Rendered Kami-style XHS PNG cards: {card_dir}")
    print(f"Cards: {len(card_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
