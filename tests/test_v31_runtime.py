from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.v31_runtime import (  # noqa: E402
    build_portfolio_event_radar,
    build_portfolio_risk,
    build_v31_dashboard,
)


class V31RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = json.loads((ROOT / "config" / "rules" / "v31.json").read_text(encoding="utf-8"))
        self.account_rules = {
            "max_position_market_value_pct": "10",
            "max_positions": 5,
            "max_same_theme_exposure_pct": "25",
            "daily_drawdown_freeze_pct": "2",
            "weekly_drawdown_freeze_pct": "4",
            "monthly_drawdown_freeze_pct": "7",
            "consecutive_loss_freeze_count": 3,
        }
        self.market_rules = {"max_total_open_risk_pct": "3"}
        self.symbols = [
            {"symbol": "NVDA", "price": 100},
            {"symbol": "AMD", "price": 50},
        ]
        self.meta = {
            "NVDA": {"sector": "半导体"},
            "AMD": {"sector": "半导体"},
        }

    def risk(self, profile, marked=None):
        return build_portfolio_risk(
            profile=profile,
            marked_holdings=set(marked or []),
            symbols=self.symbols,
            symbol_meta=self.meta,
            account_rules=self.account_rules,
            market_risk_rules=self.market_rules,
            market_allocation_cap_pct="45",
            caution_utilization_fraction="0.80",
        )

    @staticmethod
    def event_calendar(status="已核验"):
        return {
            "verification_status": status,
            "weeks": [{
                "label": "本周",
                "start": "2026-08-10",
                "end": "2026-08-16",
                "events": [
                    {"id": "lite", "title": "LITE财报", "at": "2026-08-11T17:00:00-04:00", "importance": 4, "scope": ["LITE", "光电与机器视觉", "半导体"]},
                    {"id": "glw", "title": "GLW行业会", "at": "2026-08-12T10:00:00-04:00", "importance": 3, "scope": ["光电与机器视觉"]},
                    {"id": "cpi", "title": "CPI", "at": "2026-08-12T08:30:00-04:00", "importance": 4, "scope": ["全市场"]},
                ],
            }],
        }

    def event_radar(self, marked, status="已核验"):
        portfolio = {
            "marked_holdings": marked,
            "input": {"positions": []},
            "positions": [],
        }
        return build_portfolio_event_radar(
            event_calendar=self.event_calendar(status),
            portfolio_risk=portfolio,
            symbols=[
                {"symbol": "LITE", "sector": "光电与机器视觉"},
                {"symbol": "AMD", "sector": "半导体"},
            ],
            rules=self.rules,
        )

    def test_event_radar_prioritizes_direct_then_sector_then_global_risk(self):
        result = self.event_radar(["LITE"])
        self.assertEqual(result["state"], "ACTIVE")
        self.assertEqual(
            [event["relevance"] for event in result["events"]],
            ["DIRECT", "SECTOR", "GLOBAL"],
        )
        self.assertEqual(result["policy_version"], "1.0.0")
        self.assertEqual(result["decision_effect"], "NONE")

    def test_event_radar_maps_related_company_to_held_industry(self):
        result = self.event_radar(["AMD"])
        lite = next(event for event in result["events"] if event["id"] == "lite")
        self.assertEqual(lite["relevance"], "SECTOR")
        self.assertEqual(lite["matched"], ["半导体"])

    def test_event_radar_fails_closed_when_calendar_needs_verification(self):
        result = self.event_radar(["LITE"], "需要重新核验")
        self.assertEqual(result["state"], "UNVERIFIED")
        self.assertEqual(result["decision_effect"], "NONE")
        self.assertIn("重新核验", result["next_action"])

    def test_event_radar_requires_a_holding_or_sector_selection(self):
        result = self.event_radar([])
        self.assertEqual(result["state"], "NO_SELECTION")
        self.assertEqual(result["events"], [])

    def test_missing_portfolio_fails_closed(self):
        result = self.risk(None, ["NVDA"])
        self.assertEqual(result["state"], "DATA_GAP")
        self.assertFalse(result["can_add_risk"])
        self.assertEqual(result["missing_positions"], ["NVDA"])

    def test_portfolio_uses_decimal_open_risk_and_theme_exposure(self):
        profile = {
            "portfolio_id": "p1",
            "created_at": "2026-08-08T00:00:00+00:00",
            "payload": {
                "account": {"equity": "100000", "daily_drawdown_pct": "0", "weekly_drawdown_pct": "0", "monthly_drawdown_pct": "0", "consecutive_losses": 0},
                "positions": [
                    {"symbol": "NVDA", "quantity": "100", "average_cost": "90", "stop_price": "95"},
                    {"symbol": "AMD", "quantity": "100", "average_cost": "45", "stop_price": "48"},
                ],
            },
        }
        result = self.risk(profile, ["NVDA", "AMD"])
        self.assertEqual(result["open_risk_pct"], "0.70")
        self.assertEqual(result["market_value_pct"], "15.00")
        self.assertEqual(result["largest_theme"]["exposure_pct"], "15.00")
        self.assertEqual(result["state"], "PASS")

    def test_drawdown_freeze_has_priority_over_missing_position_data(self):
        profile = {
            "portfolio_id": "p2",
            "created_at": "2026-08-08T00:00:00+00:00",
            "payload": {
                "account": {"equity": "100000", "daily_drawdown_pct": "2.1", "weekly_drawdown_pct": "0", "monthly_drawdown_pct": "0", "consecutive_losses": 0},
                "positions": [],
            },
        }
        result = self.risk(profile, ["NVDA"])
        self.assertEqual(result["state"], "FROZEN")
        self.assertIn("日回撤", result["checks"][0]["evidence"])

    def test_same_theme_concentration_blocks_new_risk(self):
        profile = {
            "portfolio_id": "p3",
            "created_at": "2026-08-08T00:00:00+00:00",
            "payload": {
                "account": {"equity": "100000", "daily_drawdown_pct": "0", "weekly_drawdown_pct": "0", "monthly_drawdown_pct": "0", "consecutive_losses": 0},
                "positions": [{"symbol": "NVDA", "quantity": "300", "average_cost": "90", "stop_price": "99"}],
            },
        }
        result = self.risk(profile, ["NVDA"])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["largest_theme"]["exposure_pct"], "30.00")

    def test_v31_composes_without_mutating_v3(self):
        base = {
            "schema_version": "3.0.0",
            "system_version": "ANLI 3.0",
            "rule_version": "3.0.0",
            "meta": {"source_versions": {}, "compatibility": {}, "research_only": True},
            "command": {"stack": []},
            "methodology": {},
            "symbols": [],
        }
        validation = {"status": "COLLECTING", "label": "正在积累不可改写样本", "sample_sufficient": False, "primary_horizon_sessions": 5, "primary_sample_count": 0, "minimum_sample_count": 30, "shadow_setup_count": 0}
        portfolio = {"state": "DATA_GAP", "label": "组合风险无法计算", "open_risk_pct": None, "market_value_pct": None, "next_action": "补齐组合"}
        payload = build_v31_dashboard(base_dashboard=base, validation=validation, portfolio_risk=portfolio, rules=self.rules)
        self.assertEqual(payload["schema_version"], "3.1.0")
        self.assertEqual(payload["system_version"], "ANLI 3.1")
        self.assertEqual(base["schema_version"], "3.0.0")
        self.assertEqual(len(payload["command"]["stack"]), 2)
        self.assertFalse(payload["meta"]["automatic_ordering"])


if __name__ == "__main__":
    unittest.main()
