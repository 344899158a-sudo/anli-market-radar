import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.event_calendar import build_event_calendar


class EventCalendarTests(unittest.TestCase):
    def test_uses_complete_monday_to_sunday_weeks(self):
        sunday_result = build_event_calendar(date(2026, 8, 2))
        self.assertEqual(sunday_result["weeks"][0]["start"], "2026-08-03")
        self.assertEqual(sunday_result["weeks"][0]["end"], "2026-08-09")
        self.assertEqual(sunday_result["weeks"][0]["label"], "下周")
        self.assertEqual(sunday_result["weeks"][1]["start"], "2026-08-10")
        self.assertEqual(sunday_result["weeks"][1]["end"], "2026-08-16")

        monday_result = build_event_calendar(date(2026, 8, 3))
        self.assertEqual(monday_result["weeks"][0]["start"], "2026-08-03")
        self.assertEqual(monday_result["weeks"][0]["end"], "2026-08-09")
        self.assertEqual(monday_result["weeks"][0]["label"], "本周")

        tuesday_result = build_event_calendar(date(2026, 8, 4))
        self.assertEqual(tuesday_result["weeks"][0]["start"], "2026-08-03")
        self.assertEqual(tuesday_result["weeks"][0]["end"], "2026-08-09")
        self.assertEqual(tuesday_result["weeks"][0]["label"], "本周")

        thursday_result = build_event_calendar(date(2026, 8, 6))
        self.assertEqual(thursday_result["weeks"][0]["start"], "2026-08-03")
        self.assertEqual(thursday_result["weeks"][0]["end"], "2026-08-09")
        self.assertEqual(thursday_result["weeks"][0]["label"], "\u672c\u5468")

    def test_builds_four_weeks_from_traceable_sources(self):
        result = build_event_calendar(date(2026, 7, 27))
        self.assertEqual(len(result["weeks"]), 4)
        self.assertGreaterEqual(result["event_count"], 10)
        self.assertEqual(result["weeks"][0]["risk_label"], "很高")
        for week in result["weeks"]:
            for event in week["events"]:
                self.assertTrue(event["source_url"].startswith("https://"))
                self.assertTrue(event["verification"])

    def test_verification_clock_is_deterministic(self):
        fresh = build_event_calendar(
            date(2026, 8, 3),
            now=datetime(2026, 8, 11, 2, 30, tzinfo=timezone.utc),
        )
        stale = build_event_calendar(
            date(2026, 8, 9),
            now=datetime(2026, 8, 14, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(fresh["verification_status"], "已核验")
        self.assertEqual(stale["verification_status"], "需要重新核验")

    def test_lite_earnings_is_officially_traced_and_maps_to_related_industries(self):
        result = build_event_calendar(
            date(2026, 8, 11),
            now=datetime(2026, 8, 11, 2, 30, tzinfo=timezone.utc),
        )
        lite = next(
            event
            for week in result["weeks"]
            for event in week["events"]
            if event["id"] == "lite-fy26-q4"
        )
        self.assertEqual(lite["at_et"], "2026-08-11T17:00:00-04:00")
        self.assertEqual(lite["source"], "Lumentum Investor Relations")
        self.assertTrue({"LITE", "光模块", "半导体"}.issubset(set(lite["scope"])))

    def test_excludes_events_outside_window(self):
        result = build_event_calendar(date(2026, 8, 24))
        event_ids = {event["id"] for week in result["weeks"] for event in week["events"]}
        self.assertNotIn("fomc-jul", event_ids)


if __name__ == "__main__":
    unittest.main()
