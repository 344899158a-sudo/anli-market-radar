from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "build_public_site.py"
SPEC = importlib.util.spec_from_file_location("build_public_site", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicSiteBuildTests(unittest.TestCase):
    def test_build_uses_same_responsive_shell_with_pages_safe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = MODULE.build_public_site(directory)
            index = (output / "index.html").read_text(encoding="utf-8")
            qqq = (output / "qqq_trendiq.html").read_text(encoding="utf-8")

            self.assertIn("原则驱动实时机会雷达", index)
            self.assertIn('href="./watchlist_v2.css', index)
            self.assertIn('data-detail-href="./qqq_trendiq.html"', index)
            self.assertLess(
                index.index("./public_adapter.js"),
                index.index("./watchlist_v2.js"),
            )
            self.assertLess(
                qqq.index("./public_adapter.js"),
                qqq.index("./qqq_trendiq.js"),
            )
            self.assertNotIn('id="decisionCenter"', index)
            self.assertNotIn('href="#decisionCenter"', index)
            self.assertNotIn("今日纪律行动", index)
            self.assertNotIn("checkin.html", index)
            self.assertNotIn("decision_center.css", index)
            self.assertNotIn("decision_center.js", index)
            self.assertNotRegex(
                "\n".join((index, qqq)),
                r'(?:href|src|data-detail-href)="/',
            )

            desktop = (ROOT / "web" / "watchlist_v2.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("今日纪律行动", desktop)
            self.assertIn('/checkin.html', desktop)

    def test_build_copies_only_explicit_public_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = MODULE.build_public_site(directory)
            names = {
                path.name
                for path in output.iterdir()
                if path.is_file()
            }
            self.assertEqual(
                names,
                {
                    *MODULE.PUBLIC_ASSETS,
                    "index.html",
                    "qqq_trendiq.html",
                },
            )
            self.assertTrue(
                {
                    "decision_center.css",
                    "decision_center.js",
                    "checkin.css",
                    "checkin.js",
                    "checkin.html",
                }.isdisjoint(names)
            )
            self.assertFalse((output / "config_watchlist.json").exists())
            self.assertFalse((output / "watchlist_state.db").exists())


if __name__ == "__main__":
    unittest.main()
