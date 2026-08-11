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

from build_v2_overlay import build_v2_overlay  # noqa: E402
from build_v31_overlay import build_v31_overlay  # noqa: E402
from semialert.public_snapshot_contract import assert_no_forbidden_fields  # noqa: E402
from tests.v2_fixtures import bundle, opportunity  # noqa: E402


class V31OverlayTests(unittest.TestCase):
    def _release(self, site: Path) -> None:
        source = bundle(datetime.now(timezone.utc), [opportunity("TEST")])
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
        relative = f"snapshots/{manifest['snapshot_id']}/technical/TEST.json"
        path = data_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(technical_raw)
        manifest["modules"]["technical/TEST"] = {
            "path": relative,
            "sha256": hashlib.sha256(technical_raw).hexdigest(),
        }
        (data_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def test_builds_public_v31_without_private_portfolio_or_legacy_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            self._release(site)
            build_v2_overlay(site)
            result = build_v31_overlay(site)

            self.assertEqual(result["schema_version"], "3.1.0")
            self.assertEqual(result["symbol_count"], 1)
            self.assertTrue(result["public_read_only"])
            self.assertTrue((site / "index.html").is_file())
            self.assertTrue((site / "v3.html").is_file())
            self.assertTrue((site / "v1.html").is_file())
            self.assertTrue((site / "playbooks.html").is_file())

            v3 = json.loads(
                (site / "data" / "dashboard-v3.json").read_text(encoding="utf-8")
            )
            v31 = json.loads(
                (site / "data" / "dashboard-v31.json").read_text(encoding="utf-8")
            )
            self.assertEqual(v3["schema_version"], "3.0.0")
            self.assertEqual(v31["schema_version"], "3.1.0")
            self.assertTrue(v31["meta"]["public_read_only"])
            self.assertTrue(v31["portfolio_risk"]["public_redacted"])
            self.assertNotIn("account_equity", v31["portfolio_risk"])
            self.assertNotIn("input", v31["portfolio_risk"])
            self.assertEqual(v31["portfolio_event_radar"]["state"], "NO_SELECTION")
            self.assertEqual(v31["portfolio_event_radar"]["focus_symbols"], [])
            self.assertEqual(v31["validation"]["primary_sample_count"], 0)
            assert_no_forbidden_fields(v3)
            assert_no_forbidden_fields(v31)


if __name__ == "__main__":
    unittest.main()
