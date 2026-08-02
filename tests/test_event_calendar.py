import sys
import unittest
from datetime import date
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

    def test_builds_four_weeks_from_traceable_sources(self):
        result = build_event_calendar(date(2026, 7, 27))
        self.assertEqual(len(result["weeks"]), 4)
        self.assertGreaterEqual(result["event_count"], 10)
        self.assertEqual(result["weeks"][0]["risk_label"], "很高")
        for week in result["weeks"]:
            for event in week["events"]:
                self.assertTrue(event["source_url"].startswith("https://"))
                self.assertTrue(event["verification"])

    def test_excludes_events_outside_window(self):
        result = build_event_calendar(date(2026, 8, 24))
        event_ids = {event["id"] for week in result["weeks"] for event in week["events"]}
        self.assertNotIn("fomc-jul", event_ids)


if __name__ == "__main__":
    unittest.main()
