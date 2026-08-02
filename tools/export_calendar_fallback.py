from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_public_site import build_public_site  # noqa: E402
from validate_public_release import validate_public_release  # noqa: E402
from semialert.event_calendar import build_event_calendar  # noqa: E402
from semialert.public_snapshot_contract import (  # noqa: E402
    SCHEMA_VERSION,
    assert_no_forbidden_fields,
    make_envelope,
    make_quality,
    select_public_fields,
)


DEFAULT_BASE_URL = "https://344899158a-sudo.github.io/anli-market-radar/"
Download = Callable[[str], bytes]


class CalendarFallbackError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _download_bytes(url: str, *, timeout_seconds: int = 30) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ANLI-calendar-fallback/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except Exception as exc:  # network errors differ across runners
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise CalendarFallbackError(f"failed to download validated base release: {url}") from last_error


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CalendarFallbackError(f"unsafe module path in base manifest: {value}")
    return path


def _download_base_release(
    data_root: Path,
    base_url: str,
    *,
    fetcher: Download,
) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    root_url = base_url.rstrip("/") + "/"
    manifest_url = urljoin(root_url, "data/manifest.json")
    manifest_content = fetcher(manifest_url)
    try:
        manifest = json.loads(manifest_content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CalendarFallbackError("published base manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("modules"), dict):
        raise CalendarFallbackError("published base manifest has no modules")
    (data_root / "manifest.json").write_bytes(manifest_content)
    relatives: list[PurePosixPath] = []
    for entry in manifest["modules"].values():
        if not isinstance(entry, dict) or not entry.get("path"):
            raise CalendarFallbackError("published base manifest contains an invalid module")
        relatives.append(_safe_relative_path(str(entry["path"])))

    def fetch_module(relative: PurePosixPath) -> tuple[PurePosixPath, bytes]:
        url = urljoin(root_url, "data/" + quote(relative.as_posix(), safe="/"))
        return relative, fetcher(url)

    worker_count = min(8, max(1, len(relatives)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for relative, content in executor.map(fetch_module, relatives):
            target = data_root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return validate_public_release(data_root)


def _load_envelope(data_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    relative = _safe_relative_path(str(entry.get("path") or ""))
    path = data_root.joinpath(*relative.parts)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CalendarFallbackError(f"base module is invalid: {relative}") from exc
    if not isinstance(envelope, dict):
        raise CalendarFallbackError(f"base module is not an object: {relative}")
    return envelope


def _calendar_quality(calendar: dict[str, Any]) -> dict[str, Any]:
    if str(calendar.get("verification_status") or "").strip() != "已核验":
        raise CalendarFallbackError("event calendar is no longer within its verification window")
    return make_quality(status="OK")


def _compose_calendar_snapshot(
    data_root: Path,
    base_manifest: dict[str, Any],
    *,
    generated_at: datetime,
    calendar_builder: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    generated_at = generated_at.astimezone(timezone.utc)
    snapshot_id = generated_at.strftime("%Y%m%dT%H%M%S%fZ") + "-calendar-" + uuid.uuid4().hex[:8]
    calendar = calendar_builder()
    if not isinstance(calendar, dict) or not calendar:
        raise CalendarFallbackError("event calendar builder returned no data")

    final_snapshot = data_root / "snapshots" / snapshot_id
    if final_snapshot.exists():
        raise CalendarFallbackError(f"fallback snapshot already exists: {snapshot_id}")
    final_snapshot.mkdir(parents=True)
    entries: dict[str, dict[str, Any]] = {}
    base_snapshot_id = str(base_manifest.get("snapshot_id") or "")
    rule_version = str(base_manifest.get("rule_version") or "")
    if not base_snapshot_id or not rule_version:
        raise CalendarFallbackError("base manifest identity is incomplete")

    for name, entry in sorted(base_manifest["modules"].items()):
        if not isinstance(entry, dict):
            raise CalendarFallbackError(f"invalid base module entry: {name}")
        envelope = _load_envelope(data_root, entry)
        if envelope.get("snapshot_id") != base_snapshot_id:
            raise CalendarFallbackError(f"base snapshot mismatch: {name}")
        if name == "event-calendar":
            envelope = make_envelope(
                snapshot_id=snapshot_id,
                module="event-calendar",
                rule_version=rule_version,
                as_of=str(calendar.get("generated_at") or generated_at.isoformat()),
                source=dict(envelope.get("source") or {}),
                quality=_calendar_quality(calendar),
                data=select_public_fields("event-calendar", calendar),
            )
        else:
            envelope = dict(envelope)
            envelope["snapshot_id"] = snapshot_id
            assert_no_forbidden_fields(envelope)

        relative = _safe_relative_path(f"{name}.json")
        content = _json_bytes(envelope)
        target = final_snapshot.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries[name] = {
            "path": f"snapshots/{snapshot_id}/{relative.as_posix()}",
            "as_of": envelope["as_of"],
            "quality": envelope["quality"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }

    base_quality = dict(base_manifest.get("quality") or {})
    missing = sorted(
        {
            *[str(item) for item in base_quality.get("missing", [])],
            "full_refresh_failed",
            "validated_market_snapshot_reused",
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "rule_version": rule_version,
        "generated_at": generated_at.isoformat(),
        "as_of": str(base_manifest.get("as_of") or ""),
        "source": dict(base_manifest.get("source") or {}),
        "quality": make_quality(status="PARTIAL", missing=missing),
        "refresh_mode": "calendar-only-fallback",
        "base_snapshot_id": base_snapshot_id,
        "modules": entries,
    }
    if not manifest["as_of"]:
        raise CalendarFallbackError("base manifest has no market as_of timestamp")
    assert_no_forbidden_fields(manifest)
    manifest_content = _json_bytes(manifest)
    (final_snapshot / "manifest.json").write_bytes(manifest_content)
    (data_root / "manifest.json").write_bytes(manifest_content)
    return validate_public_release(data_root)


def export_calendar_fallback(
    output_root: str | Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
    fetcher: Download = _download_bytes,
    calendar_builder: Callable[[], dict[str, Any]] = build_event_calendar,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_at = (now or (lambda: datetime.now(timezone.utc)))()
    if generated_at.tzinfo is None:
        raise CalendarFallbackError("fallback generation time must include a timezone")

    with tempfile.TemporaryDirectory(prefix=".calendar-fallback-", dir=output.parent) as staging_name:
        staging = Path(staging_name)
        build_public_site(staging)
        data_root = staging / "data"
        base_manifest = _download_base_release(data_root, base_url, fetcher=fetcher)
        manifest = _compose_calendar_snapshot(
            data_root,
            base_manifest,
            generated_at=generated_at,
            calendar_builder=calendar_builder,
        )
        if output.exists():
            shutil.rmtree(output)
        os.replace(staging, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reuse the latest validated market snapshot and refresh only the verified event calendar."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()
    manifest = export_calendar_fallback(args.output, base_url=args.base_url)
    print(
        json.dumps(
            {
                "snapshot_id": manifest["snapshot_id"],
                "base_snapshot_id": manifest["base_snapshot_id"],
                "refresh_mode": manifest["refresh_mode"],
                "quality": manifest["quality"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()