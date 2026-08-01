import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.advanced_technical import (
    _atr, _rsi, aggregate_bars, aggregate_intraday_bars, build_advanced_analysis,
)


def bars(count=320, drift=0.25):
    output = []
    price = 80.0
    for index in range(count):
        price += drift + math.sin(index / 8) * 0.35
        output.append({
            "t": f"2025-01-{index + 1:03d}T20:00:00+00:00",
            "o": price - 0.4, "h": price + 1.1, "l": price - 1.2,
            "c": price, "v": 1_000_000 + index * 1000,
            "ohlcv_complete": True,
        })
    return output


class AdvancedTechnicalTests(unittest.TestCase):
    def test_aggregate_bars_preserves_ohlcv(self):
        result = aggregate_bars(bars(8), size=4)
        self.assertEqual(len(result), 2)
        self.assertGreater(result[0]["h"], result[0]["l"])
        self.assertGreater(result[0]["v"], 0)
        self.assertTrue(result[0]["ohlcv_complete"])

    def test_rsi_uses_wilder_smoothing(self):
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(_rsi(closes, 14), 70.46, delta=0.1)

    def test_atr_uses_true_range_wilder_smoothing(self):
        sample = bars(35, drift=0.08)
        true_ranges = []
        for index in range(1, len(sample)):
            current, previous = sample[index], sample[index - 1]
            true_ranges.append(max(current["h"] - current["l"], abs(current["h"] - previous["c"]), abs(current["l"] - previous["c"])))
        expected = sum(true_ranges[:14]) / 14
        for value in true_ranges[14:]:
            expected = (expected * 13 + value) / 14
        self.assertAlmostEqual(_atr(sample, 14), expected, places=8)

    def test_four_hour_aggregation_never_crosses_dates(self):
        sample = []
        for day in ("2026-07-23", "2026-07-24"):
            for hour in range(7):
                sample.append({"t": f"{day}T{14 + hour:02d}:30:00+00:00", "o": 100 + hour,
                               "h": 101 + hour, "l": 99 + hour, "c": 100.5 + hour,
                               "v": 1000, "ohlcv_complete": True})
        result = aggregate_intraday_bars(sample, 4)
        self.assertEqual(len(result), 4)
        self.assertEqual([row["t"][:10] for row in result], ["2026-07-23", "2026-07-23", "2026-07-24", "2026-07-24"])
        self.assertEqual(result[1]["o"], 104)
        self.assertEqual(result[2]["o"], 100)
    def test_builds_multitimeframe_consensus_patterns_and_risk_plan(self):
        daily = bars()
        hourly = bars(420, drift=0.04)
        signal = {
            "price": daily[-1]["c"], "quote_time": "2026-07-24T15:00:00+00:00",
            "holding": False,
            "opportunity": {"can_act": False, "next_action": "等待原则闸门"},
        }
        result = build_advanced_analysis(
            "TEST",
            {"15m": bars(200, .02), "1h": hourly, "4h": aggregate_bars(hourly, 4),
             "1D": daily, "1W": aggregate_bars(daily, weekly=True)},
            signal, "test", "REGULAR", False,
        )
        self.assertEqual(result["symbol"], "TEST")
        self.assertGreaterEqual(len(result["available_timeframes"]), 4)
        self.assertIn(result["bias"], {"LONG", "SHORT", "NEUTRAL"})
        self.assertGreater(result["plans"]["long"]["target1"], result["plans"]["long"]["trigger"])
        self.assertLess(result["plans"]["short"]["target1"], result["plans"]["short"]["trigger"])
        self.assertIn("sample_count", result["backtest"])
        self.assertFalse(result["data"]["execution_ready"])


if __name__ == "__main__":
    unittest.main()
