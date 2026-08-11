from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_CORE_MODULES = {
    "watchlist",
    "market-overview",
    "event-calendar",
    "sector-pulse",
    "opportunities",
    "qqq-analysis",
}
STRICT_OK_MODULES = {
    "watchlist",
    "market-overview",
    "event-calendar",
    "sector-pulse",
    "opportunities",
}
PUBLIC_RELEASE_POLICY_VERSION = "1.1.0"


class PublicReleaseValidationError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicReleaseValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PublicReleaseValidationError(f"JSON root must be an object: {path}")
    return payload


def _core_quality_is_acceptable(
    name: str,
    envelopes: dict[str, dict[str, Any]],
) -> bool:
    quality = envelopes[name].get("quality", {})
    if quality.get("status") == "OK":
        return True
    if quality.get("status") != "PARTIAL" or quality.get("errors"):
        return False
    if name == "event-calendar":
        missing = {str(item) for item in quality.get("missing", []) if item}
        data = envelopes[name].get("data", {})
        if not isinstance(data, dict):
            return False
        weeks = data.get("weeks")
        if missing != {"calendar_verification"}:
            return False
        if data.get("verification_status") != "需要重新核验":
            return False
        if not all(
            isinstance(data.get(field), str) and data[field].strip()
            for field in ("generated_at", "verified_at", "timezone_note", "methodology")
        ):
            return False
        if not isinstance(weeks, list) or len(weeks) != 4:
            return False
        if not all(
            isinstance(week, dict)
            and isinstance(week.get("start"), str)
            and isinstance(week.get("end"), str)
            and isinstance(week.get("events"), list)
            for week in weeks
        ):
            return False
        event_count = data.get("event_count")
        return (
            type(event_count) is int
            and event_count >= 0
            and event_count == sum(len(week["events"]) for week in weeks)
        )
    if name != "opportunities":
        return False
    unlisted_symbols = {
        str(item.get("symbol") or "").upper()
        for item in envelopes["watchlist"].get("data", {}).get("symbols", [])
        if isinstance(item, dict) and item.get("unlisted")
    }
    missing = {
        str(symbol or "").upper()
        for symbol in quality.get("missing", [])
        if symbol
    }
    return bool(missing) and missing.issubset(unlisted_symbols)


def validate_public_release(data_root: str | Path) -> dict[str, Any]:
    root = Path(data_root).resolve()
    manifest_path = root / "manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("quality", {}).get("status") in {"FAILED", "STALE"}:
        raise PublicReleaseValidationError("manifest is failed or stale")
    modules = manifest.get("modules")
    if not isinstance(modules, dict):
        raise PublicReleaseValidationError("manifest modules are missing")
    missing = sorted(REQUIRED_CORE_MODULES.difference(modules))
    if missing:
        raise PublicReleaseValidationError(
            "required public modules are missing: " + ", ".join(missing)
        )

    envelopes: dict[str, dict[str, Any]] = {}
    for name, entry in modules.items():
        if not isinstance(entry, dict) or not entry.get("path"):
            raise PublicReleaseValidationError(f"invalid module entry: {name}")
        path = (root / str(entry["path"])).resolve()
        if root not in path.parents:
            raise PublicReleaseValidationError(f"module path escapes data root: {name}")
        content = path.read_bytes()
        if len(content) != entry.get("bytes"):
            raise PublicReleaseValidationError(f"module byte count mismatch: {name}")
        if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
            raise PublicReleaseValidationError(f"module digest mismatch: {name}")
        envelope = _load_json(path)
        if envelope.get("snapshot_id") != manifest.get("snapshot_id"):
            raise PublicReleaseValidationError(f"snapshot mismatch: {name}")
        if envelope.get("schema_version") != manifest.get("schema_version"):
            raise PublicReleaseValidationError(f"schema mismatch: {name}")
        if envelope.get("quality", {}).get("status") in {"FAILED", "STALE"}:
            raise PublicReleaseValidationError(f"module is failed or stale: {name}")
        envelopes[name] = envelope

    for name in STRICT_OK_MODULES:
        if not _core_quality_is_acceptable(name, envelopes):
            raise PublicReleaseValidationError(
                f"core module must be OK before deploy: {name}"
            )

    symbols = envelopes["watchlist"].get("data", {}).get("symbols") or []
    expected_technical = {
        f"technical/{row.get('symbol')}"
        for row in symbols
        if isinstance(row, dict) and row.get("symbol")
    }
    missing_technical = sorted(expected_technical.difference(envelopes))
    if missing_technical:
        raise PublicReleaseValidationError(
            "technical shards are missing: " + ", ".join(missing_technical)
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an ANLI Pages snapshot.")
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    manifest = validate_public_release(args.data_root)
    print(manifest["snapshot_id"])


if __name__ == "__main__":
    main()
