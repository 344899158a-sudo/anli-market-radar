from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from build_public_site import build_public_site  # noqa: E402
from build_v2_overlay import load_verified_bundle  # noqa: E402
from semialert.public_snapshot_contract import (  # noqa: E402
    assert_no_forbidden_fields,
    is_forbidden_field,
)
from semialert.v3_runtime import build_v3_dashboard  # noqa: E402
from semialert.v31_runtime import build_v31_dashboard  # noqa: E402


REQUIRED_MODULES = (
    "market-overview",
    "event-calendar",
    "sector-pulse",
    "opportunities",
)


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid public overlay input: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"public overlay input must be an object: {path}")
    return payload


def _redact_for_public(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact_for_public(item)
            for key, item in value.items()
            if not is_forbidden_field(str(key))
        }
    if isinstance(value, list):
        return [_redact_for_public(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_for_public(item) for item in value]
    return value


def _aware_datetime(value: object) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _public_validation(rules: dict[str, Any]) -> dict[str, Any]:
    validation = rules["validation"]
    primary_horizon = int(validation["primary_horizon_sessions"])
    minimum = int(validation["minimum_sample_count"])
    return {
        "status": "COLLECTING",
        "label": "公开版不发布私有验证样本",
        "snapshot_count": 0,
        "observation_count": 0,
        "shadow_setup_count": 0,
        "outcome_count": 0,
        "primary_horizon_sessions": primary_horizon,
        "primary_sample_count": 0,
        "minimum_sample_count": minimum,
        "sample_sufficient": False,
        "horizons": [],
        "latest_snapshot": None,
        "recent_shadow_setups": [],
        "append_only": True,
        "public_redacted": True,
        "automatic_ordering": False,
        "warning": (
            "公开站只展示脱敏静态研究结论，不上传本机不可改写日志；"
            "后验观察也不等于真实成交收益。"
        ),
    }


def _public_portfolio() -> dict[str, Any]:
    return {
        "state": "DATA_GAP",
        "label": "组合数据仅保存在本机",
        "can_add_risk": False,
        "position_count": 0,
        "detailed_position_count": 0,
        "coverage_pct": None,
        "market_value_pct": None,
        "open_risk_pct": None,
        "largest_theme": None,
        "missing_positions": [],
        "missing_prices": [],
        "positions": [],
        "checks": [
            {
                "key": "public_privacy_gate",
                "label": "组合隐私隔离",
                "status": "MISSING",
                "evidence": "公开站不包含账户净值、持仓数量、成本或止损。",
                "next_condition": "在本机3.1录入组合资料后进行风险计算。",
            }
        ],
        "next_action": "回到本机3.1维护组合资料；公开站始终按不可扩大风险处理。",
        "profile": None,
        "public_redacted": True,
        "automatic_ordering": False,
    }


def build_v31_overlay(site_root: str | Path) -> dict[str, Any]:
    site = Path(site_root).resolve()
    data_root = site / "data"
    build_public_site(site)

    bundle = load_verified_bundle(data_root, REQUIRED_MODULES)
    manifest = bundle["manifest"]
    snapshot_id = str(manifest["snapshot_id"])
    v2_dashboard = _load_json(data_root / "dashboard-v2.json")
    if v2_dashboard.get("meta", {}).get("snapshot_id") != snapshot_id:
        raise ValueError("ANLI 2.0 overlay does not match the verified public snapshot")

    module_data = {
        name: envelope.get("data")
        for name, envelope in bundle["modules"].items()
    }
    v3_rules = _load_json(ROOT / "config" / "rules" / "v3.json")
    v31_rules = _load_json(ROOT / "config" / "rules" / "v31.json")
    generated_at = manifest.get("generated_at") or manifest.get("as_of")
    v3_dashboard = build_v3_dashboard(
        v2_dashboard=v2_dashboard,
        engine_status={"market_data_time": manifest.get("as_of")},
        market_overview=module_data["market-overview"] or {},
        legacy_signals=module_data["opportunities"] or [],
        event_calendar=module_data["event-calendar"] or {},
        sector_pulse=module_data["sector-pulse"] or {},
        alerts=[],
        rules=v3_rules,
        now=_aware_datetime(generated_at),
    )
    v3_dashboard.setdefault("meta", {})["snapshot_id"] = snapshot_id
    v3_dashboard["meta"]["public_read_only"] = True
    v3_dashboard = _redact_for_public(v3_dashboard)

    v31_dashboard = build_v31_dashboard(
        base_dashboard=v3_dashboard,
        validation=_public_validation(v31_rules),
        portfolio_risk=_public_portfolio(),
        rules=v31_rules,
    )
    v31_dashboard.setdefault("meta", {})["snapshot_id"] = snapshot_id
    v31_dashboard["meta"]["public_read_only"] = True
    v31_dashboard = _redact_for_public(v31_dashboard)

    assert_no_forbidden_fields(v3_dashboard)
    assert_no_forbidden_fields(v31_dashboard)
    v3_content = _json_bytes(v3_dashboard)
    v31_content = _json_bytes(v31_dashboard)
    _atomic_write(data_root / "dashboard-v3.json", v3_content)
    _atomic_write(data_root / "dashboard-v31.json", v31_content)

    build_manifest = {
        "schema_version": "3.1.0",
        "snapshot_id": snapshot_id,
        "as_of": manifest.get("as_of"),
        "symbol_count": len(v31_dashboard.get("symbols") or []),
        "public_read_only": True,
        "automatic_ordering": False,
        "files": {
            "dashboard-v3.json": hashlib.sha256(v3_content).hexdigest(),
            "dashboard-v31.json": hashlib.sha256(v31_content).hexdigest(),
        },
    }
    _atomic_write(
        data_root / "build-manifest-v31.json",
        _json_bytes(build_manifest),
    )
    return build_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the public read-only ANLI 3.0/3.1 overlays."
    )
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    result = build_v31_overlay(args.site_root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
