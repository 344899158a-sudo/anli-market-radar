import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.qqq_engine_public import MonitorEngine


class HistoryCacheTests(unittest.TestCase):
    def _engine(self, directory: str) -> MonitorEngine:
        engine = MonitorEngine.__new__(MonitorEngine)
        engine._history_cache_path = Path(directory) / "market_history_cache.json"
        engine.history = {}
        engine.status = {}
        return engine

    def test_history_cache_round_trip_is_atomic_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            saved_at = datetime.now(timezone.utc).isoformat()
            source = self._engine(directory)
            source.history = {"QQQ": [{"t": "2026-07-30", "c": 683.55}]}
            source.status["last_history_refresh"] = saved_at

            source._save_history_cache()

            loaded = self._engine(directory)
            loaded._load_history_cache()
            self.assertEqual(loaded.history, source.history)
            self.assertEqual(loaded.status["last_history_refresh"], saved_at)
            self.assertTrue(loaded.status["history_cache_loaded"])
            self.assertFalse(loaded.status["history_cache_stale"])
            self.assertFalse((Path(directory) / "market_history_cache.json.tmp").exists())

    def test_fresh_cache_fetches_symbols_added_to_the_watchlist(self):
        class HistoryClient:
            def __init__(self):
                self.calls = []

            def historical_daily_bars(self, symbols, days):
                self.calls.append((symbols, days))
                return {
                    symbol: [{"t": "2026-08-06", "c": 100.0}]
                    for symbol in symbols
                }

        engine = self._engine(".")
        engine.history = {"QQQ": [{"t": "2026-08-06", "c": 700.0}]}
        engine.status["last_history_refresh"] = datetime.now(timezone.utc).isoformat()
        engine.client = HistoryClient()
        engine.config = type(
            "Config",
            (),
            {"get": lambda self, key, default=None: 220 if key == "history_days" else default},
        )()
        engine._save_history_cache = lambda: None

        original = MonitorEngine.all_symbols
        try:
            MonitorEngine.all_symbols = property(lambda self: ["QQQ", "WOLF"])
            engine._refresh_history_if_needed()
        finally:
            MonitorEngine.all_symbols = original

        self.assertEqual(engine.client.calls, [(["WOLF"], 220)])
        self.assertIn("WOLF", engine.history)

    def test_invalid_history_cache_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_history_cache.json"
            path.write_text(json.dumps({"saved_at": "bad", "history": {}}), encoding="utf-8")
            engine = self._engine(directory)

            engine._load_history_cache()

            self.assertEqual(engine.history, {})
            self.assertFalse(engine.status["history_cache_loaded"])
            self.assertIn("history_cache_error", engine.status)

    def test_naive_history_cache_timestamp_fails_without_loading_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_history_cache.json"
            path.write_text(
                json.dumps(
                    {
                        "saved_at": "2026-07-31T12:00:00",
                        "history": {"QQQ": [{"t": "2026-07-30", "c": 683.55}]},
                    }
                ),
                encoding="utf-8",
            )
            engine = self._engine(directory)

            engine._load_history_cache()

            self.assertEqual(engine.history, {})
            self.assertFalse(engine.status["history_cache_loaded"])
            self.assertIn("timezone", engine.status["history_cache_error"])

    def test_future_history_cache_timestamp_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_history_cache.json"
            path.write_text(
                json.dumps(
                    {
                        "saved_at": (
                            datetime.now(timezone.utc) + timedelta(hours=2)
                        ).isoformat(),
                        "history": {"QQQ": [{"t": "2026-07-30", "c": 683.55}]},
                    }
                ),
                encoding="utf-8",
            )
            engine = self._engine(directory)

            engine._load_history_cache()

            self.assertEqual(engine.history, {})
            self.assertFalse(engine.status["history_cache_loaded"])
            self.assertIn("future", engine.status["history_cache_error"])

if __name__ == "__main__":
    unittest.main()
