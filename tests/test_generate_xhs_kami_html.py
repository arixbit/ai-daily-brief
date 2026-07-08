from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_xhs_kami_html.py"
SPEC = importlib.util.spec_from_file_location("generate_xhs_kami_html", MODULE_PATH)
assert SPEC and SPEC.loader
xhs = importlib.util.module_from_spec(SPEC)
sys.modules["generate_xhs_kami_html"] = xhs
SPEC.loader.exec_module(xhs)


class GenerateXhsKamiHtmlTests(unittest.TestCase):
    def test_top_items_returns_all_items_without_count(self) -> None:
        payload = {
            "items": [
                {"rank": 2, "title_cn": "第二条"},
                {"rank": 1, "title_cn": "第一条"},
            ]
        }

        items = xhs.top_items(payload, None)

        self.assertEqual([item["rank"] for item in items], [1, 2])

    def test_page_html_hides_page_number(self) -> None:
        item = {
            "rank": 1,
            "title_cn": "AI 工具更新",
            "summary_cn": "这是摘要。",
            "why_it_matters_cn": "这是影响。",
            "tags": ["AI"],
            "source": "公开来源",
        }

        html = xhs.page_html(item, "2026-07-09", 1, 3)

        self.assertNotIn("01/03", html)


if __name__ == "__main__":
    unittest.main()
