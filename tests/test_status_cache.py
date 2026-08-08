from __future__ import annotations

import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.qqq_engine_public import MonitorEngine


class StatusCacheTests(unittest.TestCase):
    def _engine(self, directory: str) -> MonitorEngine:
        engine = MonitorEngine.__new__(MonitorEngine)
        engine._status_cache_path = Path(directory) / "market_status_cache.json"
        engine.status = {
            "feed": "public-resilient",
            "is_official_realtime": False,
        }
        return engine

    def test_last_real_market_state_round_trips_and_is_marked_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._engine(directory)
            source.status.update({
                "last_refresh": "2026-08-07T20:05:00+00:00",
                "market_data_time": "2026-08-07T20:04:24+00:00",
                "market_overview": {"regime": "STRONG_HIGH_VOL", "assets": {}},
                "sector_pulse": {"state": "MIXED", "members": 13},
                "sector_status": {"半导体": {"benchmark": "SOXX", "above_ma50": False}},
                "provider": "Yahoo 公开近实时",
            })
            source._save_status_cache()

            loaded = self._engine(directory)
            loaded._load_status_cache()

            self.assertTrue(loaded.status["status_cache_loaded"])
            self.assertTrue(loaded.status["cached_snapshot"])
            self.assertFalse(loaded.status["is_official_realtime"])
            self.assertEqual(loaded.status["feed"], "last-known-good-cache")
            self.assertEqual(
                loaded.status["market_data_time"],
                "2026-08-07T20:04:24+00:00",
            )
            self.assertIn("最后有效缓存", loaded.status["provider"])
            self.assertFalse((Path(directory) / "market_status_cache.json.tmp").exists())

    def test_future_status_cache_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(directory)
            engine._status_cache_path.write_text(
                '{"saved_at":"2999-01-01T00:00:00+00:00","status":{}}',
                encoding="utf-8",
            )
            engine.history = {}
            engine.store = type("EmptyStore", (), {"get_signals": lambda self: []})()

            engine._load_status_cache()

            self.assertFalse(engine.status["status_cache_loaded"])
            self.assertIn("future", engine.status["status_cache_error"])


if __name__ == "__main__":
    unittest.main()
