from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_public_snapshot import FakeEngine, calendar

from semialert.public_snapshot import export_ready_engine_snapshot
from tools.validate_public_release import (
    PUBLIC_RELEASE_POLICY_VERSION,
    PublicReleaseValidationError,
    _core_quality_is_acceptable,
    validate_public_release,
)


class PublicReleaseTests(unittest.TestCase):
    def test_release_policy_version_tracks_partial_calendar_safety_rule(self) -> None:
        self.assertEqual(PUBLIC_RELEASE_POLICY_VERSION, "1.1.0")

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

    def test_complete_but_expired_calendar_does_not_block_fresh_market_release(self) -> None:
        ranges = [
            ("2026-08-10", "2026-08-16"),
            ("2026-08-17", "2026-08-23"),
            ("2026-08-24", "2026-08-30"),
            ("2026-08-31", "2026-09-06"),
        ]
        weeks = [
            {
                "start": start,
                "end": end,
                "events": [] if index else [{"id": "cpi-jul"}],
            }
            for index, (start, end) in enumerate(ranges)
        ]
        envelopes = {
            "event-calendar": {
                "quality": {
                    "status": "PARTIAL",
                    "missing": ["calendar_verification"],
                    "errors": [],
                },
                "data": {
                    "generated_at": "2026-08-11T00:48:57+00:00",
                    "verified_at": "2026-08-06T13:20:00+08:00",
                    "verification_status": "需要重新核验",
                    "timezone_note": "美东时间与北京时间",
                    "methodology": "仅显示有公开来源的事件",
                    "event_count": 1,
                    "weeks": weeks,
                },
            }
        }
        self.assertTrue(_core_quality_is_acceptable("event-calendar", envelopes))

        envelopes["event-calendar"]["data"]["verification_status"] = "已核验"
        self.assertFalse(_core_quality_is_acceptable("event-calendar", envelopes))
        envelopes["event-calendar"]["data"]["verification_status"] = "需要重新核验"
        envelopes["event-calendar"]["quality"]["missing"].append("weeks")
        self.assertFalse(_core_quality_is_acceptable("event-calendar", envelopes))


if __name__ == "__main__":
    unittest.main()
