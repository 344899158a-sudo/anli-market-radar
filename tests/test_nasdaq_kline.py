import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.market_regime import _daily_chart


class NasdaqKlineTests(unittest.TestCase):
    def test_daily_chart_preserves_ohlcv_and_moving_averages(self):
        bars = [{
            "t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
            "o": 100 + i, "h": 102 + i, "l": 99 + i, "c": 101 + i, "v": 1_000_000 + i,
            "ohlcv_complete": True,
        } for i in range(220)]
        rows = _daily_chart(bars)
        self.assertEqual(len(rows), 180)
        self.assertEqual(rows[-1]["open"], 319)
        self.assertEqual(rows[-1]["high"], 321)
        self.assertEqual(rows[-1]["low"], 318)
        self.assertEqual(rows[-1]["close"], 320)
        self.assertIsNotNone(rows[-1]["ma20"])
        self.assertIsNotNone(rows[-1]["ma50"])
        self.assertIsNotNone(rows[-1]["ma200"])

    def test_dashboard_has_clickable_market_overview_without_small_hint(self):
        html = (ROOT / "web" / "watchlist_v2.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "watchlist_v2.js").read_text(encoding="utf-8")
        self.assertIn('id="qqqRadar"', html)
        self.assertIn('id="marketOverview"', html)
        self.assertIn('id="marketKline"', html)
        self.assertIn('href="/qqq_trendiq.html"', html)
        self.assertIn('data-detail-href="/qqq_trendiq.html"', html)
        self.assertIn('role="link"', html)
        self.assertNotIn('<span class="market-detail-link">', html)
        self.assertNotIn("先看状态，再看位置，最后才决定进攻、防守或保护利润", html)
        self.assertNotIn('id="nasdaqKline"', html)
        self.assertIn("/api/event-calendar", js)
        self.assertIn("function renderQQQRadar", js)
        self.assertIn("/api/qqq-analysis", js)
        self.assertIn("document.querySelectorAll('[data-detail-href]')", js)
        self.assertIn("['Enter', ' '].includes(event.key)", js)

    def test_every_watchlist_symbol_opens_the_full_trendiq_system(self):
        html = (ROOT / "web" / "watchlist_v2.html").read_text(encoding="utf-8")
        watchlist_js = (ROOT / "web" / "watchlist_v2.js").read_text(encoding="utf-8")
        trendiq_html = (ROOT / "web" / "qqq_trendiq.html").read_text(encoding="utf-8")
        trendiq_js = (ROOT / "web" / "qqq_trendiq.js").read_text(encoding="utf-8")
        self.assertIn('href="/playbooks.html"', html)
        self.assertNotIn('id="decisionCenter"', html)
        self.assertIn('./qqq_trendiq.html?symbol=${encodeURIComponent(item.symbol)}', watchlist_js)
        self.assertIn('id="technicalTitle"', trendiq_html)
        self.assertIn('new URLSearchParams(location.search)', trendiq_js)
        self.assertIn('/api/technical?symbol=${encodeURIComponent(TECH_SYMBOL)}', trendiq_js)
        self.assertIn('TECH_SYMBOL==="QQQ"?"/api/qqq-analysis"', trendiq_js)


if __name__ == "__main__":
    unittest.main()
