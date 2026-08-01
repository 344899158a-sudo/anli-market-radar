from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_public_snapshot import FakeEngine, calendar

from semialert.public_snapshot import PublicSnapshotExporter
from semialert.public_snapshot_contract import make_envelope, make_quality


def read_module(output: Path, manifest: dict, name: str) -> dict:
    return json.loads(
        (output / manifest["modules"][name]["path"]).read_text(encoding="utf-8")
    )


class PublicSnapshotQualityTests(unittest.TestCase):
    def test_stale_market_and_unverified_calendar_are_not_ok(self) -> None:
        engine = FakeEngine()
        engine.status["market_data_time"] = "2020-01-02T20:00:00+00:00"
        engine.status["market_overview"]["as_of"] = "2020-01-02T20:00:00+00:00"

        def stale_calendar() -> dict:
            payload = calendar()
            payload["verification_status"] = "需要重新核验"
            return payload

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            manifest = PublicSnapshotExporter(
                engine,
                output,
                rule_version="1.0.0",
                event_calendar_builder=stale_calendar,
                now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
            ).export()

            market = read_module(output, manifest, "market-overview")
            events = read_module(output, manifest, "event-calendar")
            self.assertEqual(market["quality"]["status"], "STALE")
            self.assertIn("market_data_stale", market["quality"]["missing"])
            self.assertEqual(events["quality"]["status"], "PARTIAL")
            self.assertIn(
                "calendar_verification",
                events["quality"]["missing"],
            )
            self.assertEqual(manifest["quality"]["status"], "STALE")

    def test_market_errors_are_generic_and_mark_partial(self) -> None:
        engine = FakeEngine()
        engine.status["last_error"] = "token=must-not-leak"
        engine.status["history_cache_stale"] = True
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            manifest = PublicSnapshotExporter(
                engine,
                output,
                rule_version="1.0.0",
                event_calendar_builder=calendar,
                now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
            ).export()

            market = read_module(output, manifest, "market-overview")
            self.assertEqual(market["quality"]["status"], "PARTIAL")
            self.assertIn("history_cache_stale", market["quality"]["missing"])
            self.assertNotIn("must-not-leak", json.dumps(market))

    def test_nested_private_technical_fields_are_removed(self) -> None:
        envelope = make_envelope(
            snapshot_id="snapshot-1",
            module="technical",
            rule_version="1.0.0",
            as_of="2026-07-31T14:00:00+00:00",
            source={
                "provider": "test",
                "feed": "test",
                "latency": "static",
                "is_official_realtime": False,
                "session": "REGULAR",
                "timezone": "America/New_York",
            },
            quality=make_quality(),
            data={
                "symbol": "NVDA",
                "data": {
                    "provider": "public",
                    "internal_note": "private",
                    "raw_model_response": "private",
                },
            },
        )
        self.assertNotIn("internal_note", envelope["data"]["data"])
        self.assertNotIn("raw_model_response", envelope["data"]["data"])

    def test_watchlist_contains_only_sanitized_sector_status(self) -> None:
        engine = FakeEngine()
        engine.status["sector_status"] = {
            "US Mega Cap": {
                "benchmark": "QQQ",
                "above_ma50": True,
                "secret": "never-public",
            }
        }
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            manifest = PublicSnapshotExporter(
                engine,
                output,
                rule_version="1.0.0",
                event_calendar_builder=calendar,
                now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
            ).export()

            watchlist = read_module(output, manifest, "watchlist")["data"]
            self.assertEqual(
                watchlist["sector_status"]["US Mega Cap"],
                {"benchmark": "QQQ", "above_ma50": True},
            )


if __name__ == "__main__":
    unittest.main()
