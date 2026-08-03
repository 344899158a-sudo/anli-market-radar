from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anli_v2.engine import DecisionEngineV2  # noqa: E402
from tests.v2_fixtures import bundle, event, opportunity  # noqa: E402


class DecisionEngineV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
        self.engine = DecisionEngineV2(
            ROOT / "config" / "rules" / "v2.json",
            ROOT / "config" / "driver_trees.json",
        )

    def decide(self, source_bundle):
        return self.engine.build_dashboard(source_bundle, now=self.now)

    def test_leadership_playbook_can_be_research_ready_but_not_executable_on_public_data(self) -> None:
        result = self.decide(bundle(self.now, [opportunity(drawdown=-4, volume=1.25)]))
        stock = result["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "LEADERSHIP_PULLBACK")
        self.assertEqual(stock["entry"]["state"], "BROKER_CONFIRMATION")
        self.assertTrue(stock["entry"]["setup_ready"])
        self.assertFalse(stock["entry"]["can_act"])
        self.assertTrue(all(item["status"] == "PASS" for item in stock["criteria"]))

    def test_leadership_volume_block_waits_for_trigger(self) -> None:
        result = self.decide(bundle(self.now, [opportunity(drawdown=-4, volume=0.7)]))
        stock = result["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "LEADERSHIP_PULLBACK")
        self.assertEqual(stock["entry"]["state"], "WAIT_TRIGGER")
        self.assertIn("BLOCK", {item["status"] for item in stock["criteria"]})

    def test_expectation_playbook_requires_revision_and_options_evidence(self) -> None:
        amd = opportunity("AMD", drawdown=-3)
        source = bundle(self.now, [amd], [event("AMD", self.now, 10)])
        stock = self.decide(source)["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "EXPECTATION_BUILD")
        self.assertEqual(stock["event_phase"]["code"], "EXPECTATION_BUILD")
        self.assertEqual(stock["entry"]["state"], "EVIDENCE_INSUFFICIENT")
        missing = {item["key"] for item in stock["criteria"] if item["status"] == "MISSING"}
        self.assertEqual(missing, {"revision", "options"})

    def test_pre_event_risk_overrides_missing_evidence(self) -> None:
        amd = opportunity("AMD", drawdown=-3)
        source = bundle(self.now, [amd], [event("AMD", self.now, 3)])
        stock = self.decide(source)["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "EXPECTATION_BUILD")
        self.assertEqual(stock["entry"]["state"], "PRE_EVENT_RISK")

    def test_post_event_playbook_requires_actual_guidance_and_price_confirmation(self) -> None:
        amd = opportunity("AMD", day_change=7, drawdown=-2, volume=2.0)
        source = bundle(self.now, [amd], [event("AMD", self.now, 0)])
        stock = self.decide(source)["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "POST_EVENT_CONFIRMATION")
        self.assertEqual(stock["entry"]["state"], "EVIDENCE_INSUFFICIENT")
        missing = {item["key"] for item in stock["criteria"] if item["status"] == "MISSING"}
        self.assertTrue({"actual", "guidance", "implied_move", "avwap"}.issubset(missing))

    def test_washout_has_priority_over_pre_event_expectation(self) -> None:
        amd = opportunity("AMD", day_change=-8, drawdown=-15, stabilized=False)
        source = bundle(self.now, [amd], [event("AMD", self.now, 10)])
        stock = self.decide(source)["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "WASHOUT_RECOVERY")
        self.assertNotEqual(stock["playbook"]["code"], "EXPECTATION_BUILD")

    def test_washout_missing_fundamental_cause_never_becomes_ready(self) -> None:
        nvo = opportunity("NVO", day_change=-9, drawdown=-13, stabilized=True)
        stock = self.decide(bundle(self.now, [nvo]))["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "WASHOUT_RECOVERY")
        self.assertEqual(stock["entry"]["state"], "EVIDENCE_INSUFFICIENT")
        self.assertIn("cause", {item["key"] for item in stock["criteria"] if item["status"] == "MISSING"})

    def test_no_matching_setup_defaults_to_no_trade(self) -> None:
        flat = opportunity(drawdown=-0.2, above_ma50=False, distance_ma50=-2)
        stock = self.decide(bundle(self.now, [flat]))["symbols"][0]
        self.assertEqual(stock["playbook"]["code"], "NO_TRADE")
        self.assertEqual(stock["entry"]["state"], "NO_TRADE")

    def test_market_risk_off_overrides_valid_symbol_setup(self) -> None:
        source = bundle(self.now, [opportunity(drawdown=-4, volume=1.3)], regime="DOWNTREND", breadth50=12)
        stock = self.decide(source)["symbols"][0]
        self.assertEqual(stock["entry"]["state"], "MARKET_BLOCKED")
        self.assertEqual(self.decide(source)["market_gate"]["allocation_cap_pct"], "0")

    def test_stale_snapshot_blocks_research(self) -> None:
        source = bundle(self.now, [opportunity(drawdown=-4)], age_hours=120)
        result = self.decide(source)
        self.assertEqual(result["data_quality"]["status"], "BLOCKED")
        self.assertEqual(result["symbols"][0]["entry"]["state"], "DATA_BLOCKED")

    def test_partial_snapshot_is_visible_but_public_data_remains_non_executable(self) -> None:
        result = self.decide(bundle(self.now, quality="PARTIAL"))
        self.assertEqual(result["data_quality"]["status"], "PARTIAL")
        self.assertTrue(result["data_quality"]["can_research"])
        self.assertFalse(result["data_quality"]["execution_ready"])

    def test_risk_thresholds_are_decimal_safe_strings(self) -> None:
        risk = self.engine.rules["risk"]
        self.assertEqual(Decimal(risk["research_risk_per_trade_pct"]), Decimal("0.50"))
        self.assertEqual(Decimal(risk["max_total_open_risk_pct"]), Decimal("3.00"))

    def test_playbook_radar_exposes_full_decision_path_and_real_bottlenecks(self) -> None:
        amd = opportunity("AMD", drawdown=-3)
        source = bundle(self.now, [amd], [event("AMD", self.now, 10)])
        result = self.decide(source)
        radar = result["playbook_radar"]
        self.assertEqual(
            {row["code"] for row in radar["playbooks"]},
            {
                "LEADERSHIP_PULLBACK",
                "EXPECTATION_BUILD",
                "POST_EVENT_CONFIRMATION",
                "WASHOUT_RECOVERY",
            },
        )
        expectation = next(
            row for row in radar["playbooks"] if row["code"] == "EXPECTATION_BUILD"
        )
        self.assertEqual(len(expectation["decision_path"]), 5)
        self.assertEqual(expectation["state"], "EVIDENCE_GAP")
        self.assertIn(
            expectation["primary_bottleneck"]["key"],
            {"revision", "options"},
        )
        self.assertEqual(expectation["leaders"][0]["symbol"], "AMD")

    def test_command_brief_is_auditable_and_keeps_public_data_non_executable(self) -> None:
        result = self.decide(bundle(self.now, [opportunity(drawdown=-4, volume=1.25)]))
        brief = result["command_brief"]
        self.assertEqual(len(brief["stack"]), 5)
        self.assertEqual(brief["risk_budget"]["risk_per_trade_pct"], "0.50")
        self.assertEqual(brief["stack"][0]["status"], "PASS")
        self.assertFalse(result["symbols"][0]["entry"]["can_act"])
        self.assertEqual(result["symbols"][0]["decision_stack"][-1]["status"], "BLOCK")

    def test_symbol_focus_names_one_next_action(self) -> None:
        amd = opportunity("AMD", drawdown=-3)
        stock = self.decide(bundle(self.now, [amd], [event("AMD", self.now, 10)]))["symbols"][0]
        self.assertIsNotNone(stock["primary_constraint"])
        self.assertTrue(stock["next_best_action"])
        self.assertEqual(len(stock["decision_stack"]), 5)
    def test_event_phase_boundaries(self) -> None:
        expected = {
            40: "DISCOVERY",
            30: "EXPECTATION_BUILD",
            7: "EXPECTATION_BUILD",
            5: "PRE_EVENT_RISK",
            0: "FACT_RELEASED",
            -3: "POST_EVENT_DISCOVERY",
            -4: "POST_EVENT_TREND",
            -21: "INACTIVE",
        }
        for days, phase in expected.items():
            with self.subTest(days=days):
                self.assertEqual(self.engine._event_phase(days)["code"], phase)


if __name__ == "__main__":
    unittest.main()

