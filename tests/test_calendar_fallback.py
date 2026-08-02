from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from export_calendar_fallback import (  # noqa: E402
    CalendarFallbackError,
    export_calendar_fallback,
)
from tests.test_public_snapshot import FakeEngine, calendar  # noqa: E402
from semialert.event_calendar import build_event_calendar  # noqa: E402
from semialert.public_snapshot import export_ready_engine_snapshot  # noqa: E402
from tools.validate_public_release import validate_public_release  # noqa: E402


class CalendarFallbackTests(unittest.TestCase):
    def _base_release(self, root: Path) -> tuple[dict, dict[str, bytes]]:
        data = root / "data"
        manifest = export_ready_engine_snapshot(
            FakeEngine(),
            data,
            project_root=ROOT,
            event_calendar_builder=calendar,
            now=lambda: datetime(2026, 7, 31, 14, 2, tzinfo=timezone.utc),
        )
        mapping = {
            "https://example.test/data/manifest.json": (data / "manifest.json").read_bytes()
        }
        for entry in manifest["modules"].values():
            mapping["https://example.test/data/" + entry["path"]] = (
                data / entry["path"]
            ).read_bytes()
        return manifest, mapping

    def test_reuses_validated_market_data_and_refreshes_only_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_manifest, mapping = self._base_release(root / "base")

            def fetcher(url: str) -> bytes:
                return mapping[url]

            result = export_calendar_fallback(
                root / "site",
                base_url="https://example.test/",
                fetcher=fetcher,
                calendar_builder=lambda: build_event_calendar(date(2026, 8, 2)),
                now=lambda: datetime(2026, 8, 2, 13, 30, tzinfo=timezone.utc),
            )
            validated = validate_public_release(root / "site" / "data")
            self.assertEqual(validated["snapshot_id"], result["snapshot_id"])
            self.assertEqual(result["refresh_mode"], "calendar-only-fallback")
            self.assertEqual(result["base_snapshot_id"], base_manifest["snapshot_id"])
            self.assertEqual(result["as_of"], base_manifest["as_of"])
            self.assertEqual(result["quality"]["status"], "PARTIAL")
            self.assertIn("validated_market_snapshot_reused", result["quality"]["missing"])

            old_opportunity = json.loads(
                mapping[
                    "https://example.test/data/"
                    + base_manifest["modules"]["opportunities"]["path"]
                ]
            )
            new_opportunity = json.loads(
                (
                    root
                    / "site"
                    / "data"
                    / result["modules"]["opportunities"]["path"]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(new_opportunity["data"], old_opportunity["data"])
            self.assertEqual(new_opportunity["as_of"], old_opportunity["as_of"])
            self.assertEqual(new_opportunity["source"], old_opportunity["source"])
            self.assertEqual(new_opportunity["quality"], old_opportunity["quality"])
            self.assertNotEqual(new_opportunity["snapshot_id"], old_opportunity["snapshot_id"])

            calendar_envelope = json.loads(
                (
                    root
                    / "site"
                    / "data"
                    / result["modules"]["event-calendar"]["path"]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(calendar_envelope["quality"]["status"], "OK")
            self.assertEqual(calendar_envelope["data"]["weeks"][0]["start"], "2026-08-03")
            self.assertEqual(calendar_envelope["data"]["weeks"][0]["end"], "2026-08-09")

    def test_rejects_calendar_outside_verification_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, mapping = self._base_release(root / "base")
            stale_calendar = calendar()
            stale_calendar["verification_status"] = "需要重新核验"
            with self.assertRaisesRegex(CalendarFallbackError, "verification window"):
                export_calendar_fallback(
                    root / "site",
                    base_url="https://example.test/",
                    fetcher=lambda url: mapping[url],
                    calendar_builder=lambda: stale_calendar,
                    now=lambda: datetime(2026, 8, 2, 13, 30, tzinfo=timezone.utc),
                )

    def test_rejects_tampered_published_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_manifest, mapping = self._base_release(root / "base")
            path = "https://example.test/data/" + base_manifest["modules"]["opportunities"]["path"]
            mapping[path] += b"tampered"
            with self.assertRaises(Exception):
                export_calendar_fallback(
                    root / "site",
                    base_url="https://example.test/",
                    fetcher=lambda url: mapping[url],
                    now=lambda: datetime(2026, 8, 2, 13, 30, tzinfo=timezone.utc),
                )

    def test_workflow_uses_fallback_without_disabling_final_validation(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("id: live_release", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("steps.live_release.outcome == 'failure'", workflow)
        self.assertIn("python tools/export_calendar_fallback.py .site", workflow)
        self.assertIn("python tools/validate_public_release.py .site/data", workflow)


if __name__ == "__main__":
    unittest.main()