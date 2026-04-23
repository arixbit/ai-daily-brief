#!/usr/bin/env python3
"""Generate a Chinese AI daily brief as static JSON data.

The script fetches configured RSS/Atom/API sources, ranks recent AI-related
items, optionally rewrites them through an OpenAI-compatible local model, and
writes files consumed by the static website.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "sources.json"
DEFAULT_OUTPUT = ROOT / "public" / "data"
USER_AGENT = "ai-daily-brief/0.1 (+https://ai.arixbit.me)"
UTC = dt.timezone.utc


@dataclass(frozen=True)
class NewsItem:
    """Normalized source item before Chinese brief generation."""

    title: str
    url: str
    source: str
    published_at: str
    summary: str


class ReadhubDescriptionParser(HTMLParser):
    """Extract individual stories from Readhub Daily's RSS HTML description."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str, str]] = []
        self._in_item = False
        self._in_paragraph = False
        self._paragraph_parts: list[str] = []
        self._paragraph_href = ""
        self._title = ""
        self._url = ""
        self._summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "li":
            self._in_item = True
            self._title = ""
            self._url = ""
            self._summary_parts = []
        elif self._in_item and tag == "p":
            self._in_paragraph = True
            self._paragraph_parts = []
            self._paragraph_href = ""
        elif self._in_paragraph and tag == "a" and not self._paragraph_href:
            self._paragraph_href = dict(attrs).get("href") or ""

    def handle_data(self, data: str) -> None:
        if self._in_paragraph:
            self._paragraph_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_paragraph and tag == "p":
            paragraph = re.sub(r"\s+", " ", "".join(self._paragraph_parts)).strip()
            if self._paragraph_href and not self._title:
                self._title = paragraph
                self._url = self._paragraph_href
            elif paragraph:
                self._summary_parts.append(paragraph)
            self._in_paragraph = False
            self._paragraph_parts = []
            self._paragraph_href = ""
        elif self._in_item and tag == "li":
            if self._title and self._url:
                self.items.append((self._title, self._url, " ".join(self._summary_parts)))
            self._in_item = False


def utc_now() -> dt.datetime:
    """Return the current UTC time with timezone information."""

    return dt.datetime.now(UTC)


def parse_date(value: str | None) -> dt.datetime | None:
    """Parse common RSS, Atom, API, and ISO date strings."""

    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        pass

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_timezone_offset(value: str) -> dt.timezone:
    """Parse a fixed timezone offset such as '+08:00'."""

    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Invalid timezone_offset: {value}")
    sign, hours, minutes = match.groups()
    delta = dt.timedelta(hours=int(hours), minutes=int(minutes))
    if sign == "-":
        delta = -delta
    return dt.timezone(delta)


def parse_cutoff_time(value: str) -> dt.time:
    """Parse HH:MM cutoff time used to build non-overlapping daily windows."""

    try:
        hour, minute = value.strip().split(":", 1)
        parsed = dt.time(int(hour), int(minute))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid daily_cutoff_time: {value}") from exc
    return parsed


def target_publish_window(config: dict[str, Any], target_date: str) -> tuple[dt.datetime, dt.datetime]:
    """Return the UTC publish window for a report date.

    A report dated 2026-04-24 with a 06:30 +08:00 cutoff covers articles
    published from 2026-04-23 06:30 +08:00 up to 2026-04-24 06:30 +08:00.
    Adjacent report dates therefore do not overlap.
    """

    report_date = dt.date.fromisoformat(target_date)
    tz = parse_timezone_offset(str(config.get("timezone_offset", "+08:00")))
    cutoff = parse_cutoff_time(str(config.get("daily_cutoff_time", "06:30")))
    end_local = dt.datetime.combine(report_date, cutoff, tzinfo=tz)
    start_local = end_local - dt.timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def strip_html(value: str | None) -> str:
    """Convert small HTML snippets from feeds into compact plain text."""

    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(value: str) -> str:
    """Remove common tracking parameters so duplicate links compare cleanly."""

    parsed = urllib.parse.urlsplit(value.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [
        (key, val)
        for key, val in query
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(kept), "")
    )


def title_fingerprint(value: str) -> str:
    """Normalize a title for cross-day duplicate detection."""

    text = html.unescape(value).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"['’`]s\b", "", text)
    text = re.sub(r"['’`\"]", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "by",
        "from",
        "is",
        "its",
        "new",
        "report",
        "reports",
    }
    words = [word for word in text.split() if word not in stop_words]
    return " ".join(words)


def is_similar_title(title: str, previous_titles: set[str]) -> bool:
    """Return true when a title likely describes an already published story."""

    current = title_fingerprint(title)
    if not current:
        return False
    if current in previous_titles:
        return True

    current_words = set(current.split())
    entity_terms = {
        "ai",
        "agent",
        "agents",
        "openai",
        "anthropic",
        "claude",
        "chatgpt",
        "codex",
        "google",
        "gemini",
        "deepmind",
        "meta",
        "microsoft",
        "nvidia",
        "llm",
    }
    for previous in previous_titles:
        previous_words = set(previous.split())
        if not previous_words:
            continue
        shared = len(current_words & previous_words)
        shared_words = current_words & previous_words
        meaningful_shared = {
            word for word in shared_words if len(word) >= 4 or word.isdigit()
        }
        broad_overlap = shared / max(len(current_words), len(previous_words))
        contained_overlap = shared / min(len(current_words), len(previous_words))
        if broad_overlap >= 0.75:
            return True
        if shared >= 5 and contained_overlap >= 0.8:
            return True
        if len(meaningful_shared) >= 3 and shared_words & entity_terms:
            return True
        if SequenceMatcher(None, current, previous).ratio() >= 0.82:
            return True
    return False


def load_history_dedupe(output_dir: Path, target_date: str, days: int) -> tuple[set[str], set[str]]:
    """Load URLs and title fingerprints from prior daily briefs."""

    if days <= 0:
        return set(), set()

    try:
        cutoff = dt.date.fromisoformat(target_date) - dt.timedelta(days=days)
        target = dt.date.fromisoformat(target_date)
    except ValueError:
        cutoff = dt.date.min
        target = dt.date.max

    urls: set[str] = set()
    titles: set[str] = set()
    daily_dir = output_dir / "daily"
    if not daily_dir.exists():
        return urls, titles

    for path in daily_dir.glob("*.json"):
        try:
            day = dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not (cutoff <= day < target):
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url:
                urls.add(normalize_url(str(url)))
            for title_key in ("title", "title_cn"):
                title = item.get(title_key)
                if title:
                    fingerprint = title_fingerprint(str(title))
                    if fingerprint:
                        titles.add(fingerprint)
    return urls, titles


def fetch_text(url: str, timeout: int = 25) -> str:
    """Fetch a URL and decode the response as text."""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    """Return text for the first matching child, ignoring XML namespaces."""

    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            return "".join(child.itertext()).strip()
    return ""


def child_link(element: ET.Element) -> str:
    """Return a feed item link from RSS or Atom shapes."""

    direct = child_text(element, ("link",))
    if direct:
        return direct

    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name == "link" and child.attrib.get("href"):
            return child.attrib["href"]
    return ""


def parse_feed(source: dict[str, Any]) -> list[NewsItem]:
    """Fetch and parse RSS or Atom feeds into normalized items."""

    text = fetch_text(source["url"])
    root = ET.fromstring(text)
    root_name = root.tag.rsplit("}", 1)[-1].lower()

    if root_name == "rss":
        candidates = root.findall(".//item")
    elif root_name == "feed":
        candidates = root.findall("{*}entry") or root.findall(".//entry")
    else:
        candidates = root.findall(".//item") or root.findall(".//{*}entry")

    items: list[NewsItem] = []
    for entry in candidates:
        title = strip_html(child_text(entry, ("title",)))
        link = child_link(entry)
        summary = strip_html(
            child_text(entry, ("description", "summary", "content", "encoded"))
        )
        published = (
            child_text(entry, ("published", "updated", "pubdate", "dc:date"))
            or child_text(entry, ("date",))
        )
        parsed = parse_date(published) or utc_now()

        if title and link:
            items.append(
                NewsItem(
                    title=title,
                    url=normalize_url(link),
                    source=source["name"],
                    published_at=parsed.astimezone(UTC).isoformat(),
                    summary=summary,
                )
            )
    return items


def parse_hn_algolia(source: dict[str, Any]) -> list[NewsItem]:
    """Fetch Hacker News items from Algolia's public API."""

    payload = json.loads(fetch_text(source["url"]))
    items: list[NewsItem] = []
    for hit in payload.get("hits", []):
        title = strip_html(hit.get("title") or hit.get("story_title"))
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        published = parse_date(hit.get("created_at")) or utc_now()
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        min_points = int(source.get("min_points", 0))
        min_comments = int(source.get("min_comments", 0))
        if (min_points or min_comments) and points < min_points and comments < min_comments:
            continue
        metadata = []
        if points:
            metadata.append(f"{points} points")
        if comments:
            metadata.append(f"{comments} comments")

        if title and link:
            items.append(
                NewsItem(
                    title=title,
                    url=normalize_url(link),
                    source=source["name"],
                    published_at=published.astimezone(UTC).isoformat(),
                    summary=", ".join(metadata),
                )
            )
    return items


def parse_readhub_daily_feed(source: dict[str, Any]) -> list[NewsItem]:
    """Fetch Readhub Daily RSS and split the daily digest into story items."""

    urls = [str(source["url"]), *[str(url) for url in source.get("fallback_urls", [])]]
    last_error: Exception | None = None
    for url in urls:
        try:
            text = fetch_text(url)
            break
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
    else:
        raise ValueError(f"all Readhub RSS endpoints failed: {last_error}")

    root = ET.fromstring(text)
    items: list[NewsItem] = []

    for entry in root.findall(".//item"):
        description = child_text(entry, ("description",))
        page_date_match = re.search(r"日期[：:]\s*(\d{4}-\d{2}-\d{2})", description)
        published = parse_date(child_text(entry, ("pubdate",))) or utc_now()
        if page_date_match and not child_text(entry, ("pubdate",)):
            published = dt.datetime.combine(
                dt.date.fromisoformat(page_date_match.group(1)),
                dt.time(0, 0),
                tzinfo=UTC,
            )

        parser = ReadhubDescriptionParser()
        parser.feed(description)
        for title, url, summary in parser.items:
            items.append(
                NewsItem(
                    title=strip_html(title),
                    url=normalize_url(url),
                    source=source["name"],
                    published_at=published.astimezone(UTC).isoformat(),
                    summary=strip_html(summary),
                )
            )

    return items


def fetch_source(source: dict[str, Any]) -> list[NewsItem]:
    """Dispatch source fetching by source type."""

    if source.get("type") == "feed":
        return parse_feed(source)
    if source.get("type") == "hn_algolia":
        return parse_hn_algolia(source)
    if source.get("type") == "readhub_daily_feed":
        return parse_readhub_daily_feed(source)
    raise ValueError(f"Unsupported source type: {source.get('type')}")


def keyword_score(item: NewsItem, keywords: list[str]) -> int:
    """Score an item by keyword matches in title and summary."""

    haystack = f"{item.title} {item.summary}".lower()
    score = 0
    for keyword in keywords:
        term = keyword.lower()
        if term in haystack:
            score += 3 if term in item.title.lower() else 1
    return score


def collect_items(
    config: dict[str, Any],
    output_dir: Path,
    target_date: str,
) -> tuple[list[NewsItem], list[str], list[str]]:
    """Fetch all sources and return deduplicated, ranked recent items."""

    now = utc_now()
    try:
        window_start, window_end = target_publish_window(config, target_date)
    except ValueError:
        fallback = dt.timedelta(hours=int(config.get("fallback_lookback_hours", 72)))
        window_start, window_end = now - fallback, now
    keywords = list(config.get("keywords", []))
    default_source_weight = int(config.get("default_source_weight", 3))
    history_urls, history_titles = load_history_dedupe(
        output_dir,
        target_date,
        int(config.get("history_dedupe_days", 14)),
    )
    errors: list[str] = []
    skipped_duplicates: list[str] = []
    seen: set[str] = set()
    scored: list[tuple[int, dt.datetime, NewsItem]] = []

    for source in config.get("sources", []):
        try:
            fetched = fetch_source(source)
        except (ET.ParseError, OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{source.get('name', source.get('url'))}: {exc}")
            continue

        for item in fetched:
            published = parse_date(item.published_at) or now
            if not (window_start <= published < window_end):
                continue
            dedupe_key = normalize_url(item.url)
            if dedupe_key in seen:
                continue
            if dedupe_key in history_urls or is_similar_title(item.title, history_titles):
                skipped_duplicates.append(item.title)
                continue
            seen.add(dedupe_key)

            score = keyword_score(item, keywords)
            if score <= 0:
                continue
            source_weight = int(source.get("weight", default_source_weight))
            hours_old = max(0.0, (window_end - published).total_seconds() / 3600)
            freshness_score = max(0, 6 - int(hours_old // 4))
            scored.append((score + source_weight + freshness_score, published, item))

        time.sleep(0.25)

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    selected: list[NewsItem] = []
    selected_urls: set[str] = set()
    selected_titles: set[str] = set()
    selected_source_counts: dict[str, int] = {}
    default_source_limit = int(config.get("default_source_daily_limit", 3))
    source_limits = {
        str(source.get("name")): int(source.get("daily_limit", default_source_limit))
        for source in config.get("sources", [])
    }
    max_items = int(config.get("max_items", 10))
    for _, _, item in scored:
        source_limit = source_limits.get(item.source, default_source_limit)
        if selected_source_counts.get(item.source, 0) >= source_limit:
            continue
        if is_similar_title(item.title, selected_titles):
            skipped_duplicates.append(item.title)
            continue
        selected.append(item)
        selected_urls.add(normalize_url(item.url))
        selected_source_counts[item.source] = selected_source_counts.get(item.source, 0) + 1
        fingerprint = title_fingerprint(item.title)
        if fingerprint:
            selected_titles.add(fingerprint)
        if len(selected) >= max_items:
            break

    if len(selected) < max_items:
        for _, _, item in scored:
            if normalize_url(item.url) in selected_urls:
                continue
            source_limit = source_limits.get(item.source, default_source_limit)
            if selected_source_counts.get(item.source, 0) >= source_limit:
                continue
            if is_similar_title(item.title, selected_titles):
                skipped_duplicates.append(item.title)
                continue
            selected.append(item)
            selected_urls.add(normalize_url(item.url))
            selected_source_counts[item.source] = selected_source_counts.get(item.source, 0) + 1
            fingerprint = title_fingerprint(item.title)
            if fingerprint:
                selected_titles.add(fingerprint)
            if len(selected) >= max_items:
                break

    return selected, errors, skipped_duplicates


def load_env(path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without overriding environment."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def llm_chat(messages: list[dict[str, str]], timeout: int = 240) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""

    base_url = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:12345/v1").rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY", "smartisan")
    model = os.environ.get("OPENAI_MODEL", "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-4bit")
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def parse_llm_json(content: str) -> dict[str, Any]:
    """Parse model output that may wrap JSON in explanatory text."""

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    return data


def fallback_brief(item: NewsItem) -> dict[str, Any]:
    """Build a usable brief when the local model is unavailable."""

    return {
        "title_cn": f"中文待整理：{item.title}",
        "summary_cn": strip_html(item.summary)[:220] or "模型暂时不可用，暂无中文摘要；请点击原文查看详情。",
        "why_it_matters_cn": "该条资讯与 AI 产业、模型能力或开发者生态相关，建议结合原文进一步判断影响。",
        "tags": infer_tags(item),
    }


def infer_tags(item: NewsItem) -> list[str]:
    """Infer compact Chinese tags from the source text."""

    text = f"{item.title} {item.summary}".lower()
    tag_rules = [
        ("agent", "agent"),
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("claude", "Claude"),
        ("google", "Google"),
        ("deepmind", "DeepMind"),
        ("chatgpt", "ChatGPT"),
        ("arxiv", "论文"),
        ("model", "模型"),
        ("inference", "推理"),
        ("token", "token"),
        ("robot", "机器人"),
        ("enterprise", "企业应用"),
    ]
    tags = [label for needle, label in tag_rules if needle in text]
    return tags[:4] or ["AI"]


def normalize_brief(data: dict[str, Any], item: NewsItem) -> dict[str, Any]:
    """Normalize one model-generated brief and fill missing fields."""

    fallback = fallback_brief(item)
    tags = data.get("tags", fallback["tags"])
    if not isinstance(tags, list):
        tags = fallback["tags"]
    return {
        "title_cn": str(data.get("title_cn") or fallback["title_cn"]).strip(),
        "summary_cn": str(data.get("summary_cn") or fallback["summary_cn"]).strip(),
        "why_it_matters_cn": str(
            data.get("why_it_matters_cn") or fallback["why_it_matters_cn"]
        ).strip(),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:4],
    }


def generate_llm_briefs(items: list[NewsItem], skip_llm: bool) -> list[dict[str, Any]]:
    """Generate Chinese briefs in one model call, falling back on errors."""

    if skip_llm:
        return [fallback_brief(item) for item in items]

    prompt_items = [
        {
            "index": index,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at,
            "url": item.url,
            "source_summary": item.summary[:1000],
        }
        for index, item in enumerate(items, start=1)
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是中文 AI 新闻简报编辑。输出严格 JSON，不要 Markdown。"
                "保留必要英文术语，比如 agent、token、Claude Code、Codex、ChatGPT。"
                "不要虚构输入中没有的信息。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请把这些 AI 资讯整理成中文简报。输出 JSON 对象，唯一顶层字段是 items。"
                "items 必须是数组，长度和输入一致，每项字段必须是："
                "index, title_cn, summary_cn, why_it_matters_cn, tags。"
                "summary_cn 控制在 80-140 个中文字符；why_it_matters_cn 控制在 40-90 个中文字符；"
                "tags 是 2-4 个短标签。输入："
                f"{json.dumps(prompt_items, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        content = llm_chat(messages)
        data = parse_llm_json(content)
        generated = data.get("items", [])
        if not isinstance(generated, list):
            raise ValueError("LLM JSON missing items array")

        by_index: dict[int, dict[str, Any]] = {}
        for brief in generated:
            if isinstance(brief, dict):
                try:
                    by_index[int(brief.get("index"))] = brief
                except (TypeError, ValueError):
                    continue

        return [
            normalize_brief(by_index.get(index, {}), item)
            for index, item in enumerate(items, start=1)
        ]
    except (OSError, TimeoutError, urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        briefs = [fallback_brief(item) for item in items]
        for brief in briefs:
            brief["llm_error"] = str(exc)
        return briefs


def build_daily_payload(
    items: list[NewsItem],
    errors: list[str],
    skipped_duplicates: list[str],
    target_date: str,
    skip_llm: bool,
) -> dict[str, Any]:
    """Build the final daily JSON payload."""

    generated_at = utc_now().isoformat()
    entries = []
    briefs = generate_llm_briefs(items, skip_llm)
    if len(items) != len(briefs):
        raise RuntimeError("Brief count does not match source item count")

    for index, (item, brief) in enumerate(zip(items, briefs), start=1):
        entries.append(
            {
                "rank": index,
                "title": item.title,
                "title_cn": brief["title_cn"],
                "summary_cn": brief["summary_cn"],
                "why_it_matters_cn": brief["why_it_matters_cn"],
                "tags": brief["tags"],
                "source": item.source,
                "url": item.url,
                "published_at": item.published_at,
                **({"llm_error": brief["llm_error"]} if "llm_error" in brief else {}),
            }
        )

    return {
        "date": target_date,
        "generated_at": generated_at,
        "title": f"{target_date} AI 每日简报",
        "description": "自动抓取并整理的 AI 资讯，中文摘要，来源可追溯。",
        "items": entries,
        "source_errors": errors,
        "skipped_duplicates": skipped_duplicates,
    }


def build_empty_payload(
    errors: list[str],
    skipped_duplicates: list[str],
    target_date: str,
    reason: str,
) -> dict[str, Any]:
    """Build a valid daily payload when no source item is available."""

    generated_at = utc_now().isoformat()
    return {
        "date": target_date,
        "generated_at": generated_at,
        "title": f"{target_date} AI 每日简报",
        "description": "该日期没有可发布的 AI 资讯。",
        "items": [],
        "source_errors": errors,
        "skipped_duplicates": skipped_duplicates,
        "status": "empty",
        "empty_reason_cn": reason,
    }


def should_allow_empty_historical(config: dict[str, Any], target_date: str) -> bool:
    """Return true for old backfill dates that current RSS feeds cannot cover."""

    try:
        report_date = dt.date.fromisoformat(target_date)
    except ValueError:
        return False

    days = int(config.get("empty_historical_after_days", 3))
    return report_date <= utc_now().date() - dt.timedelta(days=days)


def update_manifest(output_dir: Path, daily_payload: dict[str, Any]) -> None:
    """Update the static site manifest with the generated day."""

    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"updated_at": None, "days": []}

    day_entry = {
        "date": daily_payload["date"],
        "title": daily_payload["title"],
        "count": len(daily_payload["items"]),
        "path": f"data/daily/{daily_payload['date']}.json",
        "generated_at": daily_payload["generated_at"],
    }
    days = [day for day in manifest.get("days", []) if day.get("date") != daily_payload["date"]]
    days.append(day_entry)
    days.sort(key=lambda day: day["date"], reverse=True)

    manifest["updated_at"] = daily_payload["generated_at"]
    manifest["days"] = days
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    """Write daily data and manifest files for the static site."""

    daily_dir = output_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_path = daily_dir / f"{payload['date']}.json"
    daily_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_manifest(output_dir, payload)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Generate the AI daily brief.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--skip-llm", action="store_true", help="Use fallback summaries without calling the model.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """CLI entry point."""

    args = parse_args(argv)
    load_env(ROOT / ".env")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    items, errors, skipped_duplicates = collect_items(config, args.output, args.date)
    if not items:
        if not should_allow_empty_historical(config, args.date):
            print("No matching AI news items found.", file=sys.stderr)
            for error in errors:
                print(f"source error: {error}", file=sys.stderr)
            return 1

        reason = (
            "没有找到落在该日报时间窗口内的候选资讯。"
            "如果这是较早历史日期，通常是因为 RSS 源只保留近期内容，无法可靠回溯。"
        )
        payload = build_empty_payload(errors, skipped_duplicates, args.date, reason)
        write_outputs(payload, args.output)
        print(f"Generated empty brief for {args.date}: {reason}")
        if errors:
            print(f"{len(errors)} source(s) failed; see source_errors in the JSON output.")
        return 0

    payload = build_daily_payload(items, errors, skipped_duplicates, args.date, args.skip_llm)
    write_outputs(payload, args.output)
    print(f"Generated {len(payload['items'])} items for {args.date}.")
    if skipped_duplicates:
        print(f"Skipped {len(skipped_duplicates)} historical duplicate(s).")
    if errors:
        print(f"{len(errors)} source(s) failed; see source_errors in the JSON output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
