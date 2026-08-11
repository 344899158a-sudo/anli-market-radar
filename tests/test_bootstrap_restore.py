from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
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
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertIn("data/manifest.json", names)
            self.assertFalse(any("\\" in name for name in names))
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
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("index.html", "missing manifest")
            with self.assertRaisesRegex(BootstrapRestoreError, "manifest"):
                restore_bootstrap_release(root / "site", archive)

    def test_normalizes_legacy_windows_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = ROOT / ".github" / "bootstrap" / "public-release.zip"
            legacy = root / "legacy.zip"
            with zipfile.ZipFile(portable) as source, zipfile.ZipFile(legacy, "w") as target:
                for entry in source.infolist():
                    if entry.is_dir():
                        continue
                    target.writestr(entry.filename.replace("/", "\\"), source.read(entry))
            output = root / "site"
            manifest = restore_bootstrap_release(output, legacy)
            self.assertEqual(len(manifest["modules"]), 108)
            self.assertTrue((output / "data" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
