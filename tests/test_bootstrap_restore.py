from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from restore_bootstrap_release import (  # noqa: E402
    BootstrapRestoreError,
    restore_bootstrap_release,
)


class BootstrapRestoreTests(unittest.TestCase):
    def test_restores_validated_v31_release_with_all_legacy_routes(self) -> None:
        archive = ROOT / ".github" / "bootstrap" / "public-release.zip"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            manifest = restore_bootstrap_release(output, archive)
            self.assertEqual(
                len((manifest.get("modules") or {})),
                108,
            )
            dashboard = json.loads(
                (output / "data" / "dashboard-v31.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(dashboard["schema_version"], "3.1.0")
            self.assertEqual(len(dashboard["symbols"]), 52)
            self.assertTrue(dashboard["meta"]["public_read_only"])
            for name in ("index.html", "v3.html", "v1.html", "playbooks.html"):
                self.assertTrue((output / name).is_file(), name)

    def test_rejects_archive_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bad.zip"
            import zipfile

            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("index.html", "missing manifest")
            with self.assertRaisesRegex(BootstrapRestoreError, "manifest"):
                restore_bootstrap_release(root / "site", archive)


if __name__ == "__main__":
    unittest.main()
