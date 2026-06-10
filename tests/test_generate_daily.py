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

    def test_build_daily_payload_sorts_by_editorial_category_order(self) -> None:
        published = "2026-06-10T00:00:00+00:00"
        fixtures = [
            ("AI startup announces IPO financing plan", "industry", "AI funding and IPO market news"),
            ("Claude Code MCP agent workflow guide", "developer", "Developer workflow for coding agents"),
            ("NotebookLM app adds a new AI feature", "product", "Product update launched for users"),
            ("New arXiv paper improves AI reasoning", "paper", "Research paper with benchmark results"),
            ("Claude Fable 5 model released", "model", "New model release with updated inference pricing"),
            ("AI prompt tips for product teams", "tips", "Guide and best practices"),
            ("AI meme rumor circulates on X", "community", "Fun community rumor"),
        ]
        items = [
            gd.NewsItem(
                title=title,
                url=f"https://example.com/{slug}",
                source="Fixture",
                published_at=published,
                summary=summary,
            )
            for title, slug, summary in fixtures
        ]

        payload = gd.build_daily_payload(items, [], [], "2026-06-10", skip_llm=True, allow_fallback=True)

        self.assertEqual([item["rank"] for item in payload["items"]], list(range(1, 8)))
        self.assertEqual(
            [item["category"] for item in payload["items"]],
            [
                "model_release",
                "product_update",
                "paper_research",
                "industry",
                "developer_agent",
                "tips",
                "community_light",
            ],
        )
        self.assertEqual(payload["items"][0]["category_label"], "模型发布/更新")

    def test_build_daily_payload_suppresses_speculative_duplicate_when_official_exists(self) -> None:
        published = "2026-06-10T00:00:00+00:00"
        items = [
            gd.NewsItem(
                title="Anthropic 明天或将发布公开版本 Mythos",
                url="https://readhub.cn/topic/example",
                source="Readhub Daily",
                published_at=published,
                summary="Anthropic 可能发布 Claude Fable 5 和 Mythos。",
            ),
            gd.NewsItem(
                title="Claude Fable 5 and Claude Mythos 5",
                url="https://www.anthropic.com/news/claude-fable-5-mythos-5",
                source="Anthropic News",
                published_at=published,
                summary="Anthropic released Claude Fable 5 and Claude Mythos 5.",
            ),
            gd.NewsItem(
                title="Anthropic’s Fable 5 can make weirdly fun video games",
                url="https://techcrunch.com/example",
                source="TechCrunch AI",
                published_at=published,
                summary="Coverage of Claude Fable 5 from Anthropic.",
            ),
        ]
        skipped: list[str] = []

        payload = gd.build_daily_payload(items, [], skipped, "2026-06-10", skip_llm=True, allow_fallback=True)

        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["source"], "Anthropic News")
        self.assertIn("Anthropic 明天或将发布公开版本 Mythos", skipped)
        self.assertEqual(payload["editorial_dropped_items"][0]["reason"], "被更高可信来源覆盖")
        self.assertEqual(
            payload["editorial_dropped_items"][0]["duplicate_of"],
            "Claude Fable 5 and Claude Mythos 5",
        )

    def test_build_daily_payload_adds_editorial_metadata_and_prefers_official_sources(self) -> None:
        published = "2026-06-10T00:00:00+00:00"
        items = [
            gd.NewsItem(
                title="Claude Fable 5 model released",
                url="https://www.reddit.com/r/LocalLLaMA/comments/example",
                source="Reddit LocalLLaMA",
                published_at=published,
                summary="Community post about the Claude Fable 5 model release.",
            ),
            gd.NewsItem(
                title="Claude Fable 5 and Claude Mythos 5",
                url="https://www.anthropic.com/news/claude-fable-5-mythos-5",
                source="Anthropic News",
                published_at=published,
                summary="Anthropic released Claude Fable 5 and Claude Mythos 5.",
            ),
        ]

        payload = gd.build_daily_payload(items, [], [], "2026-06-10", skip_llm=True, allow_fallback=True)

        self.assertEqual(payload["items"][0]["source"], "Anthropic News")
        self.assertEqual(payload["items"][0]["source_role"], "official")
        self.assertEqual(payload["items"][0]["source_role_label"], "官方")
        self.assertGreater(payload["items"][0]["editorial_score"], payload["items"][1]["editorial_score"])
        self.assertTrue(payload["items"][0]["selected"])

    def test_build_daily_payload_limits_selected_community_items_per_category(self) -> None:
        published = "2026-06-10T00:00:00+00:00"
        items = [
            gd.NewsItem(
                title=f"Gemma community model release {index}",
                url=f"https://www.reddit.com/r/LocalLLaMA/comments/model_{index}",
                source="Reddit LocalLLaMA",
                published_at=published,
                summary="Gemma model weights released for local inference.",
            )
            for index in range(4)
        ]

        payload = gd.build_daily_payload(items, [], [], "2026-06-10", skip_llm=True, allow_fallback=True)
        selected = [item for item in payload["items"] if item["selected"]]
        demoted = [item for item in payload["items"] if not item["selected"]]

        self.assertEqual(len(selected), 2)
        self.assertEqual(len(demoted), 2)
        self.assertTrue(all(item["source_role"] == "community" for item in payload["items"]))
        self.assertTrue(all(item.get("editorial_note") == "社区源精选配额已满" for item in demoted))

    def test_normalize_brief_corrects_developer_tool_category(self) -> None:
        item = gd.NewsItem(
            title="llm 0.32a3",
            url="https://simonwillison.net/2026/Jun/9/llm",
            source="Simon Willison",
            published_at="2026-06-10T00:00:00+00:00",
            summary="Release notes for an llm CLI tool update written using Claude Fable 5.",
        )

        brief = gd.normalize_brief(
            {
                "title_cn": "llm 0.32a3 发布",
                "summary_cn": "Simon Willison 发布 llm 命令行工具更新。",
                "why_it_matters_cn": "这是开发者工具生态的重要更新。",
                "tags": ["llm", "开发者工具"],
                "category": "product_update",
            },
            item,
        )

        self.assertEqual(brief["category"], "developer_agent")

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
