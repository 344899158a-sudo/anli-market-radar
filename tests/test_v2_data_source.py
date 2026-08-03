from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anli_v2.data_source import DataSourceError, PublicSnapshotSource  # noqa: E402


class FakeSource(PublicSnapshotSource):
    def __init__(self, cache_root: Path, responses: dict[str, bytes]):
        super().__init__("https://example.test/data/", cache_root, manifest_ttl_seconds=0)
        self.responses = responses

    def _request(self, relative_path: str) -> bytes:
        if relative_path not in self.responses:
            raise DataSourceError(f"offline: {relative_path}")
        return self.responses[relative_path]


class PublicSnapshotSourceTests(unittest.TestCase):
    def test_manifest_requires_core_identity_fields(self) -> None:
        with self.assertRaises(DataSourceError):
            PublicSnapshotSource.validate_manifest({"snapshot_id": "x"})

    def test_hash_verified_bundle_and_last_known_good_fallback(self) -> None:
        snapshot_id = "snapshot-a"
        envelope = {"snapshot_id": snapshot_id, "module": "market-overview", "data": {"score": 61}}
        module_raw = json.dumps(envelope, separators=(",", ":")).encode()
        manifest = {
            "snapshot_id": snapshot_id,
            "schema_version": "1.0.0",
            "as_of": "2026-08-01T20:00:00+00:00",
            "source": {},
            "quality": {},
            "modules": {
                "market-overview": {
                    "path": f"snapshots/{snapshot_id}/market-overview.json",
                    "sha256": hashlib.sha256(module_raw).hexdigest(),
                }
            },
        }
        manifest_raw = json.dumps(manifest, separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource(Path(tmp), {
                "manifest.json": manifest_raw,
                f"snapshots/{snapshot_id}/market-overview.json": module_raw,
            })
            first = source.fetch_bundle(["market-overview"], force=True)
            self.assertEqual(first["fetch"]["mode"], "remote")
            self.assertEqual(first["modules"]["market-overview"]["data"]["score"], 61)
            source.responses.clear()
            second = source.fetch_bundle(["market-overview"], force=True)
            self.assertEqual(second["fetch"]["mode"], "last-known-good-cache")
            self.assertIn("offline", second["fetch"]["error"])

    def test_sha_mismatch_is_rejected_without_cache(self) -> None:
        snapshot_id = "snapshot-b"
        envelope = {"snapshot_id": snapshot_id, "module": "x", "data": {}}
        module_raw = json.dumps(envelope).encode()
        manifest = {
            "snapshot_id": snapshot_id,
            "schema_version": "1.0.0",
            "as_of": "2026-08-01T20:00:00+00:00",
            "source": {},
            "quality": {},
            "modules": {"x": {"path": "x.json", "sha256": "0" * 64}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource(Path(tmp), {
                "manifest.json": json.dumps(manifest).encode(),
                "x.json": module_raw,
            })
            with self.assertRaises(DataSourceError):
                source.fetch_bundle(["x"], force=True)


if __name__ == "__main__":
    unittest.main()

