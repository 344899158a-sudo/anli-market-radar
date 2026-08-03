from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


class DataSourceError(RuntimeError):
    """Raised when neither a verified remote nor cached snapshot is available."""


class PublicSnapshotSource:
    """Fetch immutable public snapshot modules with hash verification and LKG fallback."""

    def __init__(
        self,
        base_url: str,
        cache_root: str | Path,
        *,
        timeout_seconds: int = 20,
        manifest_ttl_seconds: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_root = Path(cache_root).resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.manifest_ttl_seconds = int(manifest_ttl_seconds)
        self._lock = threading.RLock()
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = 0.0

    @property
    def pointer_path(self) -> Path:
        return self.cache_root / "current.json"

    def _request(self, relative_path: str) -> bytes:
        url = urllib.parse.urljoin(self.base_url, relative_path)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ANLI-Market-Radar-2.0/2.0",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise DataSourceError(f"{url} returned HTTP {response.status}")
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DataSourceError(f"failed to read {url}: {exc}") from exc

    @staticmethod
    def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"{label} is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise DataSourceError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _atomic_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        temp.write_bytes(raw)
        os.replace(temp, path)

    @staticmethod
    def _module_filename(name: str) -> str:
        safe = name.replace("/", "__").replace("\\", "__")
        if not safe or safe.startswith("."):
            raise DataSourceError(f"unsafe module name: {name!r}")
        return safe + ".json"

    def _manifest_path(self, snapshot_id: str) -> Path:
        return self.cache_root / "snapshots" / snapshot_id / "manifest.json"

    def _module_path(self, snapshot_id: str, name: str) -> Path:
        return self.cache_root / "snapshots" / snapshot_id / "modules" / self._module_filename(name)

    @staticmethod
    def validate_manifest(manifest: dict[str, Any]) -> None:
        for key in ("snapshot_id", "schema_version", "as_of", "modules", "source", "quality"):
            if key not in manifest:
                raise DataSourceError(f"manifest missing {key}")
        if not isinstance(manifest["modules"], dict) or not manifest["modules"]:
            raise DataSourceError("manifest modules are empty")
        if not isinstance(manifest["snapshot_id"], str) or not manifest["snapshot_id"]:
            raise DataSourceError("manifest snapshot_id is invalid")

    def fetch_manifest(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            fresh = time.monotonic() - self._manifest_at < self.manifest_ttl_seconds
            if self._manifest is not None and fresh and not force:
                return self._manifest
            raw = self._request("manifest.json")
            manifest = self._decode_json(raw, "manifest")
            self.validate_manifest(manifest)
            snapshot_id = manifest["snapshot_id"]
            self._atomic_write(self._manifest_path(snapshot_id), raw)
            self._manifest = manifest
            self._manifest_at = time.monotonic()
            return manifest

    def _fetch_module_from_manifest(
        self,
        name: str,
        manifest: dict[str, Any],
        *,
        allow_cached: bool = True,
    ) -> dict[str, Any]:
        modules = manifest.get("modules") or {}
        entry = modules.get(name)
        if not isinstance(entry, dict) or not entry.get("path"):
            raise DataSourceError(f"snapshot does not contain module {name}")
        snapshot_id = str(manifest["snapshot_id"])
        cache_path = self._module_path(snapshot_id, name)

        if allow_cached and cache_path.is_file():
            cached_raw = cache_path.read_bytes()
            expected = str(entry.get("sha256") or "")
            if not expected or hashlib.sha256(cached_raw).hexdigest() == expected:
                envelope = self._decode_json(cached_raw, name)
                if envelope.get("snapshot_id") == snapshot_id:
                    return envelope

        raw = self._request(str(entry["path"]))
        expected_hash = str(entry.get("sha256") or "")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_hash and actual_hash != expected_hash:
            raise DataSourceError(
                f"module {name} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
            )
        envelope = self._decode_json(raw, name)
        if envelope.get("snapshot_id") != snapshot_id:
            raise DataSourceError(
                f"module {name} belongs to {envelope.get('snapshot_id')}, expected {snapshot_id}"
            )
        if "data" not in envelope:
            raise DataSourceError(f"module {name} has no data payload")
        self._atomic_write(cache_path, raw)
        return envelope

    def fetch_module(
        self,
        name: str,
        *,
        manifest: dict[str, Any] | None = None,
        force_manifest: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            selected = manifest or self.fetch_manifest(force=force_manifest)
            try:
                return self._fetch_module_from_manifest(name, selected)
            except DataSourceError as remote_error:
                cached = self._load_cached_manifest()
                if cached and name in (cached.get("modules") or {}):
                    try:
                        return self._load_cached_module(name, cached)
                    except DataSourceError:
                        pass
                raise remote_error

    def fetch_bundle(
        self,
        module_names: Iterable[str],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        names = tuple(dict.fromkeys(str(name) for name in module_names))
        with self._lock:
            try:
                manifest = self.fetch_manifest(force=force)
                modules = {
                    name: self._fetch_module_from_manifest(name, manifest)
                    for name in names
                }
                pointer = {
                    "snapshot_id": manifest["snapshot_id"],
                    "base_url": self.base_url,
                    "saved_at_epoch": time.time(),
                }
                self._atomic_write(
                    self.pointer_path,
                    json.dumps(pointer, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                return {
                    "manifest": manifest,
                    "modules": modules,
                    "fetch": {"mode": "remote", "error": None},
                }
            except DataSourceError as remote_error:
                cached = self._cached_bundle(names)
                if cached is None:
                    raise
                cached["fetch"] = {
                    "mode": "last-known-good-cache",
                    "error": str(remote_error),
                }
                return cached

    def _load_cached_manifest(self) -> dict[str, Any] | None:
        if not self.pointer_path.is_file():
            return None
        try:
            pointer = json.loads(self.pointer_path.read_text(encoding="utf-8"))
            snapshot_id = str(pointer["snapshot_id"])
            manifest = self._decode_json(
                self._manifest_path(snapshot_id).read_bytes(),
                "cached manifest",
            )
            self.validate_manifest(manifest)
            return manifest
        except (OSError, KeyError, json.JSONDecodeError, DataSourceError):
            return None

    def _load_cached_module(self, name: str, manifest: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(manifest["snapshot_id"])
        path = self._module_path(snapshot_id, name)
        if not path.is_file():
            raise DataSourceError(f"cached module {name} is unavailable")
        raw = path.read_bytes()
        entry = (manifest.get("modules") or {}).get(name) or {}
        expected = str(entry.get("sha256") or "")
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise DataSourceError(f"cached module {name} failed SHA-256 verification")
        envelope = self._decode_json(raw, f"cached {name}")
        if envelope.get("snapshot_id") != snapshot_id:
            raise DataSourceError(f"cached module {name} snapshot id mismatch")
        return envelope

    def _cached_bundle(self, names: tuple[str, ...]) -> dict[str, Any] | None:
        manifest = self._load_cached_manifest()
        if not manifest:
            return None
        try:
            modules = {name: self._load_cached_module(name, manifest) for name in names}
        except DataSourceError:
            return None
        self._manifest = manifest
        self._manifest_at = time.monotonic()
        return {"manifest": manifest, "modules": modules}

