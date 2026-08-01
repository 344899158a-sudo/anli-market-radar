from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_public_release import (  # noqa: E402
    PublicReleaseTimeoutError,
    ensure_public_evidence_placeholders,
    run_bounded_public_release,
)


class _Store:
    def __init__(self) -> None:
        self.saved = []

    def get_signals(self):
        return [{"symbol": "NVDA", "name": "NVIDIA", "price": 160.0}]

    def get_ai_analyses(self):
        return list(self.saved)

    def save_ai_analysis(self, analysis):
        self.saved.append(dict(analysis))


class _Engine:
    def __init__(self) -> None:
        self.store = _Store()
        self.config = type("Config", (), {
            "symbol_meta": {"NVDA": {"name": "NVIDIA"}}
        })()


class BoundedPublicReleaseTests(unittest.TestCase):
    def test_missing_private_ai_gets_an_honest_public_evidence_gate(self) -> None:
        engine = _Engine()
        created = ensure_public_evidence_placeholders(
            engine,
            now=datetime(2026, 8, 1, 5, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(created, 1)
        saved = engine.store.saved[0]
        self.assertEqual(saved["event_class"], "证据不足")
        self.assertEqual(saved["buy_gate"], "待确认")
        self.assertEqual(saved["news_items"], [])
        self.assertEqual(saved["sec_filings"], [])
        self.assertEqual(ensure_public_evidence_placeholders(engine), 0)

    @patch("export_public_release.subprocess.run")
    def test_worker_is_separate_and_summary_is_returned(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"snapshot_id":"snapshot-1","quality":{"status":"OK"},"module_count":9}\n',
            stderr="",
        )
        summary = run_bounded_public_release("site", "runtime", timeout_seconds=30)
        self.assertEqual(summary["snapshot_id"], "snapshot-1")
        command = run.call_args.args[0]
        self.assertIn("--worker", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertEqual(run.call_args.kwargs["errors"], "replace")
        self.assertEqual(Path(command[2]).name, "site")

    @patch("export_public_release.subprocess.run")
    def test_timeout_fails_closed(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=2)
        with self.assertRaises(PublicReleaseTimeoutError):
            run_bounded_public_release("site", "runtime", timeout_seconds=2)


if __name__ == "__main__":
    unittest.main()
