import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.advanced_technical import aggregate_bars
from semialert.public_snapshot import (
    PublicSnapshotExportError,
    PublicSnapshotExporter,
    export_ready_engine_snapshot,
)
from semialert.public_snapshot_contract import (
    SCHEMA_VERSION,
    assert_no_forbidden_fields,
)


def bars(count=320, drift=0.25):
    output = []
    price = 80.0
    for index in range(count):
        price += drift + math.sin(index / 8) * 0.35
        output.append(
            {
                "t": (
                    datetime(2025, 1, 1, 20, tzinfo=timezone.utc)
                    + timedelta(days=index)
                ).isoformat(),
                "o": price - 0.4,
                "h": price + 1.1,
                "l": price - 1.2,
                "c": price,
                "v": 1_000_000 + index * 1000,
                "ohlcv_complete": True,
            }
        )
    return output


class FakeStore:
    def get_signals(self):
        return [
            {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "status": "WATCH",
                "score": 72,
                "price": 160.0,
                "ma50": 150.0,
                "distance_ma50_pct": 6.67,
                "drawdown20_pct": -8.0,
                "day_change_pct": 1.2,
                "gap_pct": 0.4,
                "volume_ratio": 1.1,
                "rsi14": 55.0,
                "checks": {
                    "industry": True,
                    "quality": True,
                    "above_ma50": True,
                    "stabilized": True,
                    "drawdown": True,
                    "not_chasing": True,
                    "volume": True,
                    "catalyst": False,
                },
                "failed_checks": ["catalyst"],
                "exit_signal": "SELL_1_3",
                "quote_time": "2026-07-31T14:00:00+00:00",
                "reason": "等待催化剂",
                "sector": "美股巨头",
                "sector_benchmark": "QQQ",
                "holding": True,
                "holdings": ["NVDA"],
                "account_id": "private-account",
                "api_key": "never-public",
            }
        ]

    def get_ai_analyses(self):
        return [
            {
                "symbol": "NVDA",
                "verdict": "稳定",
                "buy_gate": "通过",
                "confidence": 80,
                "fundamental_deterioration": False,
                "risk_score": 20,
                "analyzed_at": "2026-07-31T13:30:00+00:00",
                "company": "NVIDIA",
                "event_class": "normal_move",
                "event_urgency": "low",
                "move_explained": True,
                "moat": "strong",
                "key_event": "No verified adverse event.",
                "price_move_driver": "Price move remains unconfirmed.",
                "summary": (
                    "AI-generated summary requiring source verification; "
                    "token=never-public and Bearer abc.private.signature."
                ),
                "entry_conclusion": "wait",
                "reasons": ["Public title evidence is limited."],
                "red_flags": [],
                "positive_factors": ["SEC facts are available."],
                "evidence_gaps": ["No full article text was reviewed."],
                "next_checks": ["Open the primary source."],
                "evidence_quality": {
                    "grade": "\u4e0d\u8db3",
                    "news_count": 2,
                    "sec_filing_count": 1,
                    "collection_errors": [
                        "https://collector.invalid?token=never-public"
                    ],
                    "limitation": "Titles are clues, not verified facts.",
                },
                "market_context": {
                    "price": 160.0,
                    "quote_time": "2026-07-31T14:00:00+00:00",
                    "account_id": "private-account",
                },
                "news_items": [
                    {
                        "title": "NVIDIA public headline",
                        "publisher": "Example News",
                        "url": "https://news.example.com/nvda",
                        "published_at": "2026-07-31T13:00:00+00:00",
                        "source_type": "NEWS_TITLE",
                        "content": "copyrighted full article must not publish",
                        "api_key": "never-public",
                    },
                    {
                        "title": "Unsafe local source",
                        "publisher": "Local",
                        "url": "http://127.0.0.1/private?token=never-public",
                    },
                ],
                "sec_filings": [
                    {
                        "form": "8-K",
                        "filed_at": "2026-07-30",
                        "accepted_at": "2026-07-30T20:00:00+00:00",
                        "description": "Public filing",
                        "accession": "0000000000-26-000001",
                        "url": "https://www.sec.gov/Archives/test.htm",
                        "secret": "never-public",
                    }
                ],
                "fundamentals": {
                    "cik": 1045810,
                    "entity": "NVIDIA CORP",
                    "source_url": "https://data.sec.gov/api/xbrl/companyfacts/test.json",
                    "metrics": {
                        "revenue": [
                            {
                                "value": 100,
                                "unit": "USD",
                                "end": "2026-06-30",
                                "form": "10-Q",
                                "private_key": "never-public",
                            }
                        ],
                        "unsupported_metric": [{"value": 999}],
                    },
                },
                "model": "private-model-name",
                "prompt": "private prompt",
                "jobs": [{"id": "private-job"}],
            }
        ]



class FakeConfig:
    symbols = ["NVDA"]
    symbol_meta = {
        "NVDA": {
            "symbol": "NVDA",
            "name": "NVIDIA",
            "sector": "US Mega Cap",
            "quality_approved": True,
            "catalyst_date": None,
        }
    }
    sector_benchmarks = {"US Mega Cap": "QQQ"}

    @staticmethod
    def get(key, default=None):
        return {"benchmark": "QQQ"}.get(key, default)


class FakeEngine:
    def __init__(self, *, fail_technical=False):

        self.store = FakeStore()
        self.config = FakeConfig()
        self.fail_technical = fail_technical
        self.technical_calls = []
        self.history = {"NVDA": bars()}
        self.status = {
            "provider": "测试公开延时源",
            "feed": "test-delayed",
            "is_official_realtime": False,
            "last_refresh": "2026-07-31T14:01:00+00:00",
            "market_data_time": "2026-07-31T14:00:00+00:00",
            "market_overview": {
                "as_of": "2026-07-31T14:00:00+00:00",
                "provider": "测试公开延时源",
                "score": 64,
                "regime": "STRONG_LOW_VOL",
                "regime_label": "趋势偏强",
                "position_label": "中位",
                "position_code": "MID",
                "action": "等待确认",
                "breadth": {"positive_pct": 62},
                "assets": {
                    "QQQ": {
                        "price": 160.0,
                        "quote_time": "2026-07-31T14:00:00+00:00",
                    },
                    "^VIX": {"price": 17.0},
                },
                "holdings": ["NVDA"],
                "tenant_id": "private-tenant",
            },
            "sector_pulse": {
                "state": "TREND_CONFIRMATION",
                "state_label": "趋势确认",
                "confidence": 78,
                "action": "等待回踩",
                "members": 20,
                "positive_count": 13,
                "breadth_pct": 65.0,
                "median_change_pct": 1.1,
                "benchmark_symbol": "SOXX",
                "leaders": [{"symbol": "NVDA"}],
                "audit": {"private": True},
            },
        }

    def technical_timeframes(self, symbol):
        self.technical_calls.append(symbol)
        if self.fail_technical:
            raise RuntimeError(f"{symbol} technical unavailable")
        daily = bars()
        return {
            "1D": daily,
            "1W": aggregate_bars(daily, weekly=True),
        }, {}


def calendar():
    return {
        "generated_at": "2026-07-31T14:00:00+00:00",
        "verified_at": "2026-07-31T13:00:00+00:00",
        "verification_status": "已核验",
        "timezone_note": "北京时间展示",
        "weeks": [],
        "event_count": 0,
        "methodology": "测试官方日历",
        "secret": "never-public",
    }


class PublicSnapshotTests(unittest.TestCase):
    def test_exports_partitioned_atomic_public_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            exporter = PublicSnapshotExporter(
                FakeEngine(),
                output,
                rule_version="1.0.0",
                event_calendar_builder=calendar,
                now=lambda: datetime(
                    2026, 7, 31, 14, 2, tzinfo=timezone.utc
                ),
            )
            manifest = exporter.export(technical_symbols=["NVDA"])

            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(manifest["rule_version"], "1.0.0")
            self.assertIn("market-overview", manifest["modules"])
            self.assertIn("event-calendar", manifest["modules"])
            self.assertIn("sector-pulse", manifest["modules"])
            self.assertIn("watchlist", manifest["modules"])
            self.assertIn("evidence/NVDA", manifest["modules"])
            self.assertIn("opportunities", manifest["modules"])
            self.assertIn("qqq-analysis", manifest["modules"])
            self.assertIn("technical/NVDA", manifest["modules"])

            current_manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                current_manifest["snapshot_id"],
                manifest["snapshot_id"],
            )
            immutable_manifest = (
                output
                / "snapshots"
                / manifest["snapshot_id"]
                / "manifest.json"
            )
            self.assertTrue(immutable_manifest.is_file())

            for entry in manifest["modules"].values():
                path = output / entry["path"]
                self.assertTrue(path.is_file(), path)
                envelope = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    envelope["snapshot_id"],
                    manifest["snapshot_id"],
                )
                self.assertEqual(envelope["schema_version"], SCHEMA_VERSION)
                self.assertEqual(envelope["rule_version"], "1.0.0")
                self.assertTrue(envelope["as_of"])
                self.assertIn("source", envelope)
                self.assertIn("quality", envelope)
                assert_no_forbidden_fields(envelope)

            opportunities_path = (
                output / manifest["modules"]["opportunities"]["path"]
            )
            opportunities = json.loads(
                opportunities_path.read_text(encoding="utf-8")
            )["data"]
            self.assertEqual(len(opportunities), 1)
            self.assertNotIn("holding", opportunities[0])
            self.assertNotIn("holdings", opportunities[0])
            self.assertNotIn("account_id", opportunities[0])
            self.assertNotIn("api_key", opportunities[0])
            self.assertNotIn("exit_signal", opportunities[0])

            watchlist = json.loads(
                (output / manifest["modules"]["watchlist"]["path"]).read_text(
                    encoding="utf-8"
                )
            )["data"]
            self.assertEqual(watchlist["symbol_count"], 1)
            self.assertTrue(watchlist["symbols"][0]["evidence_available"])
            self.assertNotIn("holding", watchlist["symbols"][0])

            evidence_envelope = json.loads(
                (
                    output
                    / manifest["modules"]["evidence/NVDA"]["path"]
                ).read_text(encoding="utf-8")
            )
            evidence = evidence_envelope["data"]
            self.assertEqual(evidence["verification_status"], "AI_UNVERIFIED")
            self.assertEqual(len(evidence["news"]), 1)
            self.assertEqual(len(evidence["sec_filings"]), 1)
            self.assertIn("revenue", evidence["fundamentals"]["metrics"])
            self.assertNotIn(
                "unsupported_metric",
                evidence["fundamentals"]["metrics"],
            )
            self.assertNotIn("collection_errors", evidence["evidence_quality"])
            self.assertEqual(evidence_envelope["quality"]["status"], "PARTIAL")
            self.assertIn(
                "independent_corroboration",
                evidence_envelope["quality"]["missing"],
            )
            published = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*.json")
            )
            self.assertNotIn("never-public", published)
            self.assertNotIn("abc.private.signature", published)
            self.assertIn("[REDACTED]", evidence["analysis"]["summary"])
            self.assertNotIn("private-model-name", published)
            self.assertNotIn("copyrighted full article", published)

    def test_failure_does_not_replace_previous_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            output.mkdir()
            previous = b'{"snapshot_id":"last-known-good"}\n'
            (output / "manifest.json").write_bytes(previous)
            exporter = PublicSnapshotExporter(
                FakeEngine(fail_technical=True),
                output,
                rule_version="1.0.0",
                event_calendar_builder=calendar,
                now=lambda: datetime(
                    2026, 7, 31, 14, 2, tzinfo=timezone.utc
                ),
            )

            with self.assertRaises(PublicSnapshotExportError):
                exporter.export(technical_symbols=["NVDA"])

            self.assertEqual(
                (output / "manifest.json").read_bytes(),
                previous,
            )
            snapshots = output / "snapshots"
            self.assertFalse(
                snapshots.exists() and any(snapshots.iterdir())
            )

    def test_unknown_technical_symbol_is_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "public-data"
            output.mkdir()
            previous = b'{"snapshot_id":"last-known-good"}\n'
            (output / "manifest.json").write_bytes(previous)
            exporter = PublicSnapshotExporter(
                FakeEngine(),
                output,
                rule_version="1.0.0",
                event_calendar_builder=calendar,
            )

            with self.assertRaises(PublicSnapshotExportError):
                exporter.export(technical_symbols=["../../secret"])

            self.assertEqual(
                (output / "manifest.json").read_bytes(),
                previous,
            )

    def test_ready_engine_bulk_mode_uses_cached_daily_history(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = FakeEngine()
            output = Path(folder) / "public-data"
            manifest = export_ready_engine_snapshot(
                engine,
                output,
                project_root=ROOT,
                evidence_symbols=["NVDA"],
                event_calendar_builder=calendar,
                now=lambda: datetime(
                    2026, 7, 31, 14, 2, tzinfo=timezone.utc
                ),
            )

            self.assertIn("technical/NVDA", manifest["modules"])
            self.assertEqual(engine.technical_calls, ["QQQ"])
            technical = json.loads(
                (
                    output
                    / manifest["modules"]["technical/NVDA"]["path"]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(technical["data"]["available_timeframes"]),
                {"1D", "1W"},
            )
            self.assertEqual(technical["quality"]["status"], "PARTIAL")
            self.assertEqual(
                set(technical["quality"]["missing"]),
                {"15m", "1h", "4h"},
            )
            self.assertTrue(technical["data"]["data"]["snapshot_only"])
            self.assertFalse(technical["data"]["data"]["execution_ready"])

    def test_ready_engine_entry_fails_before_replacing_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = FakeEngine()
            engine.status["last_refresh"] = None
            output = Path(folder) / "public-data"
            output.mkdir()
            previous = b'{"snapshot_id":"last-known-good"}\n'
            (output / "manifest.json").write_bytes(previous)

            with self.assertRaises(PublicSnapshotExportError):
                export_ready_engine_snapshot(
                    engine,
                    output,
                    project_root=ROOT,
                    event_calendar_builder=calendar,
                )

            self.assertEqual(
                (output / "manifest.json").read_bytes(),
                previous,
            )


if __name__ == "__main__":
    unittest.main()
