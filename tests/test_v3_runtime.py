from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.v3_runtime import build_v3_dashboard  # noqa: E402


class V3RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = json.loads(
            (ROOT / "config" / "rules" / "v3.json").read_text(encoding="utf-8")
        )
        self.now = datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc)

    @staticmethod
    def decision(symbol: str, state: str, completion: int = 50) -> dict:
        return {
            "symbol": symbol,
            "name": symbol,
            "sector": "测试行业",
            "price": 10,
            "source_status": "READY",
            "playbook": {"code": "TEST", "label": "测试剧本"},
            "entry": {"state": state, "label": state, "can_act": state == "READY"},
            "evidence_completion_pct": completion,
            "primary_constraint": {"label": "测试条件", "next_condition": "等待测试条件"},
            "next_best_action": "等待测试条件",
        }

    @staticmethod
    def signal(symbol: str, status: str = "READY") -> dict:
        return {
            "symbol": symbol,
            "name": symbol,
            "status": status,
            "score": 80,
            "opportunity": {"stage": "NEAR_READY", "final_score": 80, "can_act": False},
        }

    def build(self, decisions, signals):
        return build_v3_dashboard(
            v2_dashboard={
                "rule_version": "2.1.0",
                "meta": {"as_of": self.now.isoformat(), "source": {"provider": "test"}},
                "data_quality": {"status": "OK"},
                "command_brief": {"risk_budget": {"risk_per_trade_pct": "0.50"}},
                "symbols": decisions,
            },
            engine_status={"market_data_time": self.now.isoformat()},
            market_overview={"score": 80},
            legacy_signals=signals,
            event_calendar={"weeks": []},
            sector_pulse=None,
            alerts=[],
            rules=self.rules,
            now=self.now,
        )

    def test_v2_entry_state_is_the_canonical_research_state(self):
        payload = self.build(
            [
                self.decision("READY", "READY", 100),
                self.decision("WAIT", "WAIT_TRIGGER", 80),
                self.decision("GAP", "EVIDENCE_INSUFFICIENT", 60),
                self.decision("BLOCK", "BLOCKED", 40),
                self.decision("NONE", "NO_TRADE", 20),
            ],
            [self.signal(symbol) for symbol in ["READY", "WAIT", "GAP", "BLOCK", "NONE"]],
        )
        states = {row["symbol"]: row["research_state"]["code"] for row in payload["symbols"]}
        self.assertEqual(states["READY"], "RESEARCH_READY")
        self.assertEqual(states["WAIT"], "WAIT_TRIGGER")
        self.assertEqual(states["GAP"], "EVIDENCE_GAP")
        self.assertEqual(states["BLOCK"], "BLOCKED")
        self.assertEqual(states["NONE"], "NO_SETUP")

    def test_missing_legacy_evidence_fails_closed_and_marks_partial(self):
        payload = self.build([self.decision("MISS", "READY")], [])
        self.assertEqual(payload["symbols"][0]["research_state"]["code"], "DATA_GAP")
        self.assertIsNone(payload["symbols"][0]["price"])
        self.assertIsNone(payload["symbols"][0]["day_change_pct"])
        self.assertEqual(payload["data_quality"]["status"], "PARTIAL")
        self.assertEqual(payload["data_quality"]["missing_legacy_symbols"], ["MISS"])

    def test_no_data_never_exposes_zero_as_a_market_value(self):
        decision = self.decision("NODATA", "NO_TRADE")
        decision.update({"source_status": "NO_DATA", "price": 0, "day_change_pct": 0, "ma50": 0})
        payload = self.build([decision], [self.signal("NODATA", "NO_DATA")])
        row = payload["symbols"][0]
        self.assertEqual(row["research_state"]["code"], "DATA_GAP")
        self.assertIsNone(row["price"])
        self.assertIsNone(row["day_change_pct"])
        self.assertIsNone(row["ma50"])

    def test_priority_orders_ready_before_waiting_and_no_setup(self):
        decisions = [
            self.decision("NONE", "NO_TRADE", 90),
            self.decision("WAIT", "WAIT_TRIGGER", 60),
            self.decision("READY", "READY", 30),
        ]
        signals = [self.signal(symbol) for symbol in ["NONE", "WAIT", "READY"]]
        payload = self.build(decisions, signals)
        self.assertEqual([row["symbol"] for row in payload["symbols"]], ["READY", "WAIT", "NONE"])

    def test_legacy_watch_and_reject_are_valid_evidence_states(self):
        watch = self.decision("WATCH", "WAIT_TRIGGER")
        watch["source_status"] = "WATCH"
        reject = self.decision("REJECT", "NO_TRADE")
        reject["source_status"] = "REJECT"
        payload = self.build(
            [watch, reject],
            [self.signal("WATCH", "WATCH"), self.signal("REJECT", "REJECT")],
        )
        states = {row["symbol"]: row["research_state"]["code"] for row in payload["symbols"]}
        self.assertEqual(states["WATCH"], "WAIT_TRIGGER")
        self.assertEqual(states["REJECT"], "NO_SETUP")

    def test_v3_uses_v2_risk_policy_without_enabling_orders(self):
        payload = self.build([self.decision("TEST", "WAIT_TRIGGER")], [self.signal("TEST")])
        policy = payload["command"]["risk_policy"]
        self.assertEqual(policy["canonical_source"], "config/rules/v2.json")
        self.assertFalse(policy["automatic_ordering"])
        self.assertTrue(payload["meta"]["research_only"])


if __name__ == "__main__":
    unittest.main()
