from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from validate_public_release import validate_public_release


class BootstrapRestoreError(RuntimeError):
    pass


def _safe_relative(name: str) -> PurePosixPath:
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BootstrapRestoreError(f"unsafe bootstrap entry: {name!r}")
    return relative


def restore_bootstrap_release(
    output_root: str | Path,
    archive_path: str | Path,
) -> dict:
    output = Path(output_root).resolve()
    archive = Path(archive_path).resolve()
    if not archive.is_file():
        raise BootstrapRestoreError(f"bootstrap archive is missing: {archive}")
    if not output.name or output.parent == output:
        raise BootstrapRestoreError("refusing to replace a broad output path")

    stage = output.with_name(f".{output.name}.bootstrap-{uuid.uuid4().hex}")
    stage.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if "data/manifest.json" not in {entry.filename for entry in entries}:
                raise BootstrapRestoreError("bootstrap archive has no data/manifest.json")
            for entry in entries:
                relative = _safe_relative(entry.filename)
                target = stage.joinpath(*relative.parts).resolve()
                try:
                    target.relative_to(stage)
                except ValueError as exc:
                    raise BootstrapRestoreError(
                        f"bootstrap entry escapes output: {entry.filename!r}"
                    ) from exc
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    dir=str(target.parent),
                )
                temporary = Path(temporary_name)
                try:
                    with bundle.open(entry) as source, os.fdopen(descriptor, "wb") as handle:
                        shutil.copyfileobj(source, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)

        manifest = validate_public_release(stage / "data")
        if output.exists():
            shutil.rmtree(output)
        os.replace(stage, output)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely restore and validate the ANLI public bootstrap release."
    )
    parser.add_argument("output_root", type=Path)
    parser.add_argument("archive_path", type=Path)
    args = parser.parse_args()
    manifest = restore_bootstrap_release(args.output_root, args.archive_path)
    print(json.dumps({
        "snapshot_id": manifest["snapshot_id"],
        "quality": manifest["quality"],
        "module_count": len(manifest["modules"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
