from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anli_v2.data_source import DataSourceError, PublicSnapshotSource  # noqa: E402
from anli_v2.engine import DecisionEngineV2  # noqa: E402


ASSETS = {
    "v2_styles.css": "v2_styles.css",
    "v2_app.js": "v2_app.js",
}

ROOT_ATTRIBUTE = re.compile(
    r'(?P<attribute>href|src)="/(?P<value>[^"]*)"'
)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_module_path(data_root: Path, value: object) -> Path:
    relative = PurePosixPath(str(value or ""))
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise DataSourceError(f"unsafe public module path: {value!r}")
    target = data_root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(data_root.resolve())
    except ValueError as exc:
        raise DataSourceError(f"public module escapes data root: {value!r}") from exc
    return target


def _read_manifest(data_root: Path) -> dict[str, Any]:
    path = data_root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataSourceError("published manifest is unavailable or invalid") from exc
    if not isinstance(manifest, dict):
        raise DataSourceError("published manifest must be an object")
    PublicSnapshotSource.validate_manifest(manifest)
    return manifest


def _read_envelope(
    data_root: Path,
    manifest: dict[str, Any],
    module_name: str,
) -> dict[str, Any]:
    entry = (manifest.get("modules") or {}).get(module_name)
    if not isinstance(entry, dict) or not entry.get("path"):
        raise DataSourceError(f"published snapshot does not contain {module_name}")
    path = _safe_module_path(data_root, entry["path"])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataSourceError(f"published module is unavailable: {module_name}") from exc
    expected = str(entry.get("sha256") or "")
    actual = hashlib.sha256(raw).hexdigest()
    if not expected or actual != expected:
        raise DataSourceError(f"published module failed SHA-256: {module_name}")
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataSourceError(f"published module is invalid JSON: {module_name}") from exc
    if not isinstance(envelope, dict) or "data" not in envelope:
        raise DataSourceError(f"published module has no data: {module_name}")
    if envelope.get("snapshot_id") != manifest.get("snapshot_id"):
        raise DataSourceError(f"published module snapshot mismatch: {module_name}")
    return envelope


def load_verified_bundle(
    data_root: Path,
    required_modules: Iterable[str],
) -> dict[str, Any]:
    manifest = _read_manifest(data_root)
    modules = {
        name: _read_envelope(data_root, manifest, name)
        for name in dict.fromkeys(str(item) for item in required_modules)
    }
    return {
        "manifest": manifest,
        "modules": modules,
        "fetch": {"mode": "verified-local-release", "error": None},
    }


def build_v2_overlay(site_root: str | Path) -> dict[str, Any]:
    site = Path(site_root).resolve()
    data_root = site / "data"
    rules_path = ROOT / "config" / "rules" / "v2.json"
    driver_path = ROOT / "config" / "driver_trees.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    bundle = load_verified_bundle(data_root, rules["data"]["required_modules"])
    engine = DecisionEngineV2(rules_path, driver_path)
    dashboard = engine.build_dashboard(bundle)

    for source_name, target_name in ASSETS.items():
        source = ROOT / "web" / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, site / target_name)

    playbooks_path = site / "playbooks.html"
    if not playbooks_path.is_file():
        html = (ROOT / "web" / "v2_index.html").read_text(encoding="utf-8")
        html = ROOT_ATTRIBUTE.sub(
            lambda match: (
                f'{match.group("attribute")}="./{match.group("value")}"'
            ),
            html,
        )
        _atomic_write(playbooks_path, html.encode("utf-8"))

    _atomic_write(data_root / "dashboard-v2.json", _json_bytes(dashboard))
    generated = 0
    failed: dict[str, str] = {}
    for decision in dashboard["symbols"]:
        symbol = str(decision["symbol"])
        try:
            envelope = _read_envelope(
                data_root,
                bundle["manifest"],
                f"technical/{symbol}",
            )
            payload = {
                "schema_version": "2.0.0",
                "symbol": symbol,
                "decision": decision,
                "technical": envelope.get("data"),
                "technical_error": None,
                "data_quality": dashboard["data_quality"],
                "meta": dashboard["meta"],
            }
            _atomic_write(
                data_root / "symbols" / f"{symbol}.json",
                _json_bytes(payload),
            )
            generated += 1
        except DataSourceError as exc:
            failed[symbol] = str(exc)

    build_manifest = {
        "schema_version": "2.0.0",
        "rule_version": dashboard["rule_version"],
        "snapshot_id": dashboard["meta"]["snapshot_id"],
        "as_of": dashboard["meta"]["as_of"],
        "data_quality": dashboard["data_quality"]["status"],
        "symbol_count": len(dashboard["symbols"]),
        "technical_generated": generated,
        "technical_failed": failed,
        "automatic_ordering": False,
    }
    _atomic_write(data_root / "build-manifest.json", _json_bytes(build_manifest))
    if failed:
        raise DataSourceError(
            "ANLI 2.1 technical detail generation is incomplete: "
            + ", ".join(sorted(failed))
        )
    return build_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overlay the ANLI 2.1 decision UI on a verified public release."
    )
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    result = build_v2_overlay(args.site_root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
