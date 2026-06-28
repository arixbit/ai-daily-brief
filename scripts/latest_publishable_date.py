#!/usr/bin/env python3
"""Print the latest manifest date that is safe to publish downstream."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "sources.json"
DEFAULT_MANIFEST = ROOT / "public" / "data" / "manifest.json"
UTC = dt.timezone.utc


def parse_timezone_offset(value: str) -> dt.timezone:
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Invalid timezone_offset: {value}")
    sign, hours, minutes = match.groups()
    delta = dt.timedelta(hours=int(hours), minutes=int(minutes))
    if sign == "-":
        delta = -delta
    return dt.timezone(delta)


def local_today(config: dict[str, Any]) -> dt.date:
    tz = parse_timezone_offset(str(config.get("timezone_offset", "+08:00")))
    return dt.datetime.now(UTC).astimezone(tz).date()


def latest_publishable_date(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    today = local_today(config)
    for day in manifest.get("days") or []:
        date_value = str(day.get("date") or "").strip()
        try:
            report_date = dt.date.fromisoformat(date_value)
        except ValueError:
            continue
        if report_date <= today and int(day.get("count") or 0) > 0:
            return date_value
    raise RuntimeError("manifest 中没有非未来且 count > 0 的日报。")


def main() -> int:
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    print(latest_publishable_date(manifest, config))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
