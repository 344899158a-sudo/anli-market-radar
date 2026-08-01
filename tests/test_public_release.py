from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_public_snapshot import FakeEngine, calendar

from semialert.public_snapshot import export_ready_engine_snapshot
from tools.validate_public_release import (
    PublicReleaseValidationError,
    _core_quality_is_acceptable,
    validate_public_release,
)


class PublicReleaseTests(unittest.TestCase):
    def test_valid_bulk_release_contains_every_watchlist_technical_shard(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            manifest = export_ready_engine_snapshot(
                FakeEngine(),
                data,
                project_root=Path(__file__).resolve().parents[1],
                event_calendar_builder=calendar,
                now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
            )
            validated = validate_public_release(data)
            self.assertEqual(validated["snapshot_id"], manifest["snapshot_id"])
            self.assertIn("technical/NVDA", validated["modules"])

    def test_validator_blocks_stale_core_market_data(self) -> None:
        engine = FakeEngine()
        engine.status["market_data_time"] = "2020-01-02T20:00:00+00:00"
        engine.status["market_overview"]["as_of"] = "2020-01-02T20:00:00+00:00"
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            export_ready_engine_snapshot(
                engine,
                data,
                project_root=Path(__file__).resolve().parents[1],
                event_calendar_builder=calendar,
                now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
            )
            with self.assertRaises(PublicReleaseValidationError):
                validate_public_release(data)

    def test_expected_unlisted_symbol_does_not_block_opportunities(self) -> None:
        envelopes = {
            "watchlist": {
                "data": {
                    "symbols": [
                        {"symbol": "SPCX", "unlisted": True},
                        {"symbol": "NVDA", "unlisted": False},
                    ]
                }
            },
            "opportunities": {
                "quality": {
                    "status": "PARTIAL",
                    "missing": ["SPCX"],
                    "errors": [],
                }
            },
        }
        self.assertTrue(_core_quality_is_acceptable("opportunities", envelopes))
        envelopes["opportunities"]["quality"]["missing"] = ["NVDA"]
        self.assertFalse(_core_quality_is_acceptable("opportunities", envelopes))


if __name__ == "__main__":
    unittest.main()
