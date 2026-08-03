from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from anli_v2.data_source import DataSourceError  # noqa: E402
from build_v2_overlay import build_v2_overlay  # noqa: E402
from tests.v2_fixtures import bundle, opportunity  # noqa: E402


class V2OverlayTests(unittest.TestCase):
    def _release(self, site: Path) -> tuple[Path, bytes]:
        now = datetime.now(timezone.utc)
        source = bundle(now, [opportunity("TEST")])
        data_root = site / "data"
        manifest = source["manifest"]
        for name, envelope in source["modules"].items():
            path = data_root / manifest["modules"][name]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

        technical = {
            "snapshot_id": manifest["snapshot_id"],
            "module": "technical",
            "data": {"symbol": "TEST", "timeframes": {}},
            "quality": {"status": "OK", "missing": [], "errors": []},
        }
        technical_raw = json.dumps(
            technical,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        technical_name = "technical/TEST"
        technical_relative = (
            f"snapshots/{manifest['snapshot_id']}/technical/TEST.json"
        )
        technical_path = data_root / technical_relative
        technical_path.parent.mkdir(parents=True, exist_ok=True)
        technical_path.write_bytes(technical_raw)
        manifest["modules"][technical_name] = {
            "path": technical_relative,
            "sha256": hashlib.sha256(technical_raw).hexdigest(),
        }

        manifest_raw = json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_path = data_root / "manifest.json"
        manifest_path.write_bytes(manifest_raw)
        (site / "index.html").write_text("legacy shell", encoding="utf-8")
        return manifest_path, manifest_raw

    def test_overlays_v2_without_rewriting_verified_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            manifest_path, manifest_before = self._release(site)
            result = build_v2_overlay(site)
            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertEqual(result["rule_version"], "2.1.0")
            self.assertEqual(result["symbol_count"], 1)
            self.assertEqual(result["technical_generated"], 1)
            self.assertEqual(result["technical_failed"], {})
            self.assertIn("ANLI 2.0", (site / "index.html").read_text(encoding="utf-8"))
            self.assertTrue((site / "styles.css").is_file())
            self.assertTrue((site / "app.js").is_file())
            self.assertNotIn("今日纪律", (site / "app.js").read_text(encoding="utf-8"))
            self.assertNotIn("disciplinePanel", (site / "app.js").read_text(encoding="utf-8"))
            self.assertTrue((site / "data" / "dashboard-v2.json").is_file())
            self.assertTrue((site / "data" / "symbols" / "TEST.json").is_file())

    def test_rejects_tampered_source_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            manifest_path, _ = self._release(site)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            module_path = site / "data" / manifest["modules"]["market-overview"]["path"]
            module_path.write_bytes(module_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(DataSourceError, "SHA-256"):
                build_v2_overlay(site)


if __name__ == "__main__":
    unittest.main()
