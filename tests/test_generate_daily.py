from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_daily.py"
SPEC = importlib.util.spec_from_file_location("generate_daily", MODULE_PATH)
assert SPEC and SPEC.loader
gd = importlib.util.module_from_spec(SPEC)
sys.modules["generate_daily"] = gd
SPEC.loader.exec_module(gd)


class GenerateDailyTests(unittest.TestCase):
    def patch_attr(self, name: str, value) -> None:
        original = getattr(gd, name)
        setattr(gd, name, value)
        self.addCleanup(setattr, gd, name, original)

    def test_collect_items_caps_daily_output_at_100(self) -> None:
        published = "2026-05-04T12:00:00+00:00"
        fixture_items = [
            gd.NewsItem(
                title=f"AI item {index} zephyr{index} quartz{index}",
                url=f"https://example.com/{index}",
                source="Fixture",
                published_at=published,
                summary="AI model release",
            )
            for index in range(120)
        ]

        self.patch_attr("fetch_source", lambda source, config, target_date=None: fixture_items)
        self.patch_attr("is_similar_title", lambda title, previous_titles: False)
        self.patch_attr("load_history_dedupe", lambda output_dir, target_date, days: (set(), set()))
        self.patch_attr("time", type("TimeStub", (), {"sleep": staticmethod(lambda seconds: None)})())

        config = {
            "max_items": 150,
            "min_items": 150,
            "daily_cutoff_time": "06:30",
            "timezone_offset": "+08:00",
            "history_dedupe_days": 14,
            "keywords": ["ai"],
            "default_source_daily_limit": 200,
            "sources": [
                {
                    "name": "Fixture",
                    "type": "feed",
                    "weight": 1,
                    "daily_limit": 200,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            selected, errors, skipped = gd.collect_items(config, Path(tmp), "2026-05-05")

        self.assertEqual(len(selected), 100)
        self.assertEqual(errors, [])
        self.assertEqual(skipped, [])

    def test_parse_github_repo_releases_skips_prerelease_by_default(self) -> None:
        payload = [
            {
                "name": "v1.0.0",
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/example/project/releases/tag/v1.0.0",
                "published_at": "2026-05-04T10:00:00Z",
                "body": "<p>AI release notes</p>",
                "draft": False,
                "prerelease": False,
            },
            {
                "name": "v2.0.0-rc1",
                "tag_name": "v2.0.0-rc1",
                "html_url": "https://github.com/example/project/releases/tag/v2.0.0-rc1",
                "published_at": "2026-05-04T11:00:00Z",
                "body": "release candidate",
                "draft": False,
                "prerelease": True,
            },
        ]
        self.patch_attr("fetch_text", lambda url, timeout=25, headers=None: json.dumps(payload))

        items = gd.parse_github_repo_releases(
            {
                "name": "GitHub Releases",
                "type": "github_repo_releases",
                "owner": "example",
                "repo": "project",
            }
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "example/project: v1.0.0")
        self.assertEqual(items[0].summary, "AI release notes")

    def test_parse_reddit_subreddit_filters_by_engagement(self) -> None:
        payload = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "AI agents benchmark",
                            "url": "https://example.com/agents",
                            "created_utc": dt.datetime(2026, 5, 4, tzinfo=gd.UTC).timestamp(),
                            "score": 120,
                            "num_comments": 3,
                            "selftext": "community discussion",
                        }
                    },
                    {
                        "data": {
                            "title": "low signal",
                            "url": "https://example.com/low",
                            "created_utc": dt.datetime(2026, 5, 4, tzinfo=gd.UTC).timestamp(),
                            "score": 2,
                            "num_comments": 1,
                            "selftext": "",
                        }
                    },
                ]
            }
        }
        self.patch_attr("fetch_text", lambda url, timeout=25, headers=None: json.dumps(payload))

        items = gd.parse_reddit_subreddit(
            {
                "name": "Reddit Test",
                "type": "reddit_subreddit",
                "subreddit": "LocalLLaMA",
                "prefer_json": True,
                "min_score": 100,
                "min_comments": 20,
            }
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "AI agents benchmark")
        self.assertIn("120 upvotes", items[0].summary)

    def test_parse_telegram_channel_extracts_public_message(self) -> None:
        html = """
        <div class="tgme_widget_message_wrap js-widget_message_wrap">
          <a class="tgme_widget_message_date" href="https://t.me/example/42">
            <time datetime="2026-05-04T09:30:00+00:00"></time>
          </a>
          <div class="tgme_widget_message_text js-message_text">
            OpenAI released a new agent toolkit<br>Useful for Codex workflows.
          </div>
        </div>
        """
        self.patch_attr("fetch_text", lambda url, timeout=25, headers=None: html)

        items = gd.parse_telegram_channel(
            {
                "name": "Telegram Test",
                "type": "telegram_channel",
                "channel": "example",
            }
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://t.me/example/42")
        self.assertIn("OpenAI released", items[0].title)


if __name__ == "__main__":
    unittest.main()
