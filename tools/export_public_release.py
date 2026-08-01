from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_public_site import build_public_site  # noqa: E402
from validate_public_release import validate_public_release  # noqa: E402
from semialert.public_snapshot import export_ready_engine_snapshot  # noqa: E402
from semialert.qqq_engine_public import MonitorEngine  # noqa: E402
from semialert.watchlist_config import load_config  # noqa: E402


DEFAULT_TIMEOUT_SECONDS = 15 * 60


class PublicReleaseTimeoutError(RuntimeError):
    pass


def ensure_public_evidence_placeholders(
    engine,
    *,
    now: datetime | None = None,
) -> int:
    """Create honest, non-claiming evidence gates when private AI is unavailable."""
    existing = {
        str(item.get("symbol") or "").upper()
        for item in engine.store.get_ai_analyses()
        if isinstance(item, dict) and item.get("symbol")
    }
    analyzed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    created = 0
    for signal in engine.store.get_signals():
        symbol = str(signal.get("symbol") or "").upper()
        if not symbol or symbol in existing:
            continue
        meta = engine.config.symbol_meta.get(symbol, {})
        limitation = (
            "本次公开自动更新没有取得可验证的新闻标题、SEC申报或模型结论；"
            "证据不足不是利空结论，也绝不能当作买入依据。"
        )
        engine.store.save_ai_analysis({
            "symbol": symbol,
            "company": str(meta.get("name") or signal.get("name") or symbol),
            "analyzed_at": analyzed_at,
            "verdict": "待核验",
            "buy_gate": "待确认",
            "confidence": 0,
            "risk_score": None,
            "fundamental_deterioration": False,
            "event_class": "证据不足",
            "event_urgency": "未评级",
            "move_explained": False,
            "moat": "未核验",
            "key_event": "本次公开快照没有形成可验证的关键事件结论。",
            "price_move_driver": "缺少新闻与SEC原始证据，不能解释本次股价波动。",
            "summary": limitation,
            "entry_conclusion": "等待可验证证据",
            "reasons": ["公开发布任务未配置私有AI凭据，也没有复用任何私有模型输出。"],
            "red_flags": [],
            "positive_factors": [],
            "evidence_gaps": ["新闻标题未取得或未核验", "SEC近期申报未取得或未核验"],
            "next_checks": ["等待下一轮公开快照，或在本机运行有来源的AI/SEC复核。"],
            "evidence_quality": {
                "grade": "不足",
                "news_count": 0,
                "sec_filing_count": 0,
                "limitation": limitation,
            },
            "market_context": {
                "price": signal.get("price"),
                "quote_time": signal.get("quote_time"),
                "day_change_pct": signal.get("day_change_pct"),
            },
            "news_items": [],
            "sec_filings": [],
            "fundamentals": None,
            "model": "public-evidence-gate",
        })
        existing.add(symbol)
        created += 1
    return created


def export_public_release(
    output_root: str | Path,
    runtime_root: str | Path,
) -> dict:
    output = build_public_site(output_root)
    runtime = Path(runtime_root).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    engine = MonitorEngine(load_config(ROOT / "config_watchlist.json"), runtime)
    engine._refresh_history_if_needed()
    engine.refresh()
    ensure_public_evidence_placeholders(engine)
    manifest = export_ready_engine_snapshot(
        engine,
        output / "data",
        project_root=ROOT,
        bulk_watchlist_technical=True,
    )
    validate_public_release(output / "data")
    return manifest


def run_bounded_public_release(
    output_root: str | Path,
    runtime_root: str | Path,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Run network-backed generation in a child process with a hard deadline."""
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(Path(output_root).resolve()),
        "--runtime",
        str(Path(runtime_root).resolve()),
        "--worker",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise PublicReleaseTimeoutError(
            f"public release exceeded the {timeout_seconds}s hard deadline"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "public release worker failed").strip()
        raise RuntimeError(detail[-2000:]) from exc
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("public release worker returned no valid summary") from exc
    if not isinstance(payload, dict) or not payload.get("snapshot_id"):
        raise RuntimeError("public release worker returned an invalid summary")
    return payload


def _summary(manifest: dict) -> dict:
    return {
        "snapshot_id": manifest["snapshot_id"],
        "quality": manifest["quality"],
        "module_count": len(manifest["modules"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and validate the unified ANLI GitHub Pages release."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--runtime",
        type=Path,
        default=ROOT / ".qa" / "public-runtime",
        help="Private cache/SQLite directory; never place this inside the public output.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Hard deadline for all network-backed generation work.",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    runtime = args.runtime.resolve()
    if output == runtime or output in runtime.parents or runtime in output.parents:
        raise SystemExit("public output and private runtime must be separate directories")
    if args.worker:
        summary = _summary(export_public_release(output, runtime))
    else:
        summary = run_bounded_public_release(
            output,
            runtime,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
