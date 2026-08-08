import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.watchlist_config import load_config


class WatchlistConfigTests(unittest.TestCase):
    def test_watchlist_has_52_unique_symbols(self):
        config = load_config(ROOT / "config_watchlist.json")
        self.assertEqual(len(config.symbols), 52)
        self.assertEqual(len(set(config.symbols)), 52)
        for symbol in ("DELL", "SMCI", "TEM", "FORM", "SANM", "AAPL", "WOLF", "INOD", "RUN", "NBIS", "SNDK", "ONDS", "INTC"):
            self.assertIn(symbol, config.symbols)

    def test_spacex_is_marked_unlisted(self):
        config = load_config(ROOT / "config_watchlist.json")
        self.assertTrue(config.symbol_meta["SPCX"]["unlisted"])
        self.assertFalse(config.symbol_meta["SPCX"]["quality_approved"])


if __name__ == "__main__":
    unittest.main()
