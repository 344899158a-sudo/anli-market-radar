from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, TypedDict


SCHEMA_VERSION = "1.0.0"
QualityStatus = Literal["OK", "PARTIAL", "FAILED", "STALE"]


class PublicSource(TypedDict):
    provider: str
    feed: str
    latency: str
    is_official_realtime: bool
    session: str
    timezone: str


class PublicQuality(TypedDict):
    status: QualityStatus
    missing: list[str]
    errors: list[str]


class PublicEnvelope(TypedDict):
    schema_version: str
    snapshot_id: str
    module: str
    rule_version: str
    as_of: str
    source: PublicSource
    quality: PublicQuality
    data: Any


FORBIDDEN_EXACT_FIELDS = frozenset(
    {
        "account_id",
        "ai_job",
        "ai_jobs",
        "audit",
        "authorization",
        "dedupe_key",
        "holding",
        "holdings",
        "idempotency_key",
        "internal_note",
        "job",
        "jobs",
        "password",
        "prompt",
        "raw_model_response",
        "secret",
        "tenant_id",
        "token",
    }
)
FORBIDDEN_FIELD_FRAGMENTS = (
    "access_key",
    "account_",
    "ai_job",
    "alpaca_key",
    "audit",
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "holding",
    "password",
    "private_key",
    "secret",
    "tenant_",
    "token",
)


MODULE_FIELD_ALLOWLISTS = MappingProxyType(
    {
        "market-overview": frozenset(
            {
                "as_of",
                "calculated_at",
                "provider",
                "score",
                "regime",
                "regime_label",
                "position_label",
                "position_code",
                "exposure_guidance",
                "action",
                "scores",
                "data_quality",
                "breadth",
                "nasdaq_analysis",
                "qqq_chart",
                "nasdaq_chart",
                "assets",
                "checks",
                "limitations",
            }
        ),
        "event-calendar": frozenset(
            {
                "generated_at",
                "verified_at",
                "verification_age_hours",
                "verification_status",
                "timezone_note",
                "weeks",
                "event_count",
                "methodology",
            }
        ),
        "watchlist": frozenset(
            {
                "benchmark",
                "symbol_count",
                "sector_benchmarks",
                "sector_status",
                "sectors",
                "symbols",
            }
        ),
        "watchlist-sector": frozenset(
            {
                "name",
                "benchmark",
                "symbols",
            }
        ),
        "watchlist-symbol": frozenset(
            {
                "symbol",
                "name",
                "sector",
                "sector_benchmark",
                "quality_approved",
                "catalyst_date",
                "unlisted",
                "evidence_available",
            }
        ),
        "sector-pulse": frozenset(
            {
                "state",
                "state_label",
                "confidence",
                "action",
                "members",
                "positive_count",
                "breadth_pct",
                "median_change_pct",
                "strong_count",
                "overheat_count",
                "above_ma50_count",
                "above_ma50_pct",
                "deep_pullback_count",
                "benchmark_symbol",
                "benchmark",
                "leaders",
                "analogs",
                "decision_ladder",
            }
        ),
        "opportunity": frozenset(
            {
                "symbol",
                "name",
                "status",
                "score",
                "price",
                "ma50",
                "distance_ma50_pct",
                "drawdown20_pct",
                "day_change_pct",
                "gap_pct",
                "volume_ratio",
                "rsi14",
                "catalyst_date",
                "catalyst_days",
                "checks",
                "failed_checks",
                "quote_time",
                "market_state",
                "active_session",
                "active_session_change_pct",
                "regular_price",
                "regular_change_pct",
                "premarket_price",
                "premarket_change_pct",
                "afterhours_price",
                "afterhours_change_pct",
                "reason",
                "sector",
                "sector_benchmark",
                "opportunity",
            }
        ),
        "technical": frozenset(
            {
                "symbol",
                "price",
                "bias",
                "consensus_score",
                "confidence",
                "bullish_timeframes",
                "bearish_timeframes",
                "available_timeframes",
                "decision",
                "decision_label",
                "timeframes",
                "patterns",
                "plans",
                "backtest",
                "reasoning",
                "data",
                "warning",
                "recommendation",
                "market_context",
                "security",
            }
        ),
        "qqq-analysis": frozenset(
            {
                "symbol",
                "price",
                "bias",
                "consensus_score",
                "confidence",
                "bullish_timeframes",
                "bearish_timeframes",
                "available_timeframes",
                "decision",
                "decision_label",
                "timeframes",
                "patterns",
                "plans",
                "backtest",
                "reasoning",
                "data",
                "warning",
                "recommendation",
                "market_context",
                "security",
            }
        ),
        "evidence": frozenset(
            {
                "symbol",
                "company",
                "analyzed_at",
                "verification_status",
                "analysis",
                "evidence_quality",
                "market_context",
                "news",
                "sec_filings",
                "fundamentals",
                "limitations",
            }
        ),
        "evidence-analysis": frozenset(
            {
                "verdict",
                "event_class",
                "event_urgency",
                "move_explained",
                "fundamental_deterioration",
                "risk_score",
                "confidence",
                "moat",
                "key_event",
                "price_move_driver",
                "summary",
                "entry_conclusion",
                "buy_gate",
                "reasons",
                "red_flags",
                "positive_factors",
                "evidence_gaps",
                "next_checks",
            }
        ),
        "evidence-quality": frozenset(
            {
                "grade",
                "news_count",
                "breaking_6h",
                "news_24h",
                "news_72h",
                "trusted_breaking_count",
                "trusted_recent_count",
                "risk_keyword_count",
                "recent_sec_72h",
                "sec_filing_count",
                "latest_news_at",
                "latest_news_age_hours",
                "latest_filing_at",
                "limitation",
            }
        ),
        "evidence-market-context": frozenset(
            {
                "price",
                "day_change_pct",
                "drawdown20_pct",
                "active_session",
                "active_session_change_pct",
                "regular_price",
                "regular_change_pct",
                "premarket_price",
                "premarket_change_pct",
                "afterhours_price",
                "afterhours_change_pct",
                "quote_time",
            }
        ),
        "evidence-news": frozenset(
            {
                "title",
                "publisher",
                "url",
                "published_at",
                "source_channel",
                "session",
                "age_hours",
                "breaking_6h",
                "recent_24h",
                "risk_keyword_hit",
                "risk_keywords",
                "source_quality",
                "source_type",
            }
        ),
        "evidence-sec-filing": frozenset(
            {
                "form",
                "filed_at",
                "accepted_at",
                "report_date",
                "items",
                "description",
                "accession",
                "url",
            }
        ),
        "evidence-fundamentals": frozenset(
            {
                "cik",
                "entity",
                "metrics",
                "source_url",
            }
        ),
        "evidence-fundamental-row": frozenset(
            {
                "value",
                "unit",
                "start",
                "end",
                "filed",
                "form",
                "fiscal_year",
                "fiscal_period",
            }
        ),
    }
)


def is_forbidden_field(name: str) -> bool:
    lowered = name.casefold()
    return lowered in FORBIDDEN_EXACT_FIELDS or any(
        fragment in lowered for fragment in FORBIDDEN_FIELD_FRAGMENTS
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("public snapshot cannot contain NaN or infinity")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("public snapshot object keys must be strings")
            if is_forbidden_field(key):
                continue
            output[key] = _json_value(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    raise TypeError(f"unsupported public snapshot value: {type(value).__name__}")


def select_public_fields(module: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        allowed = MODULE_FIELD_ALLOWLISTS[module]
    except KeyError as exc:
        raise ValueError(f"unknown public snapshot module: {module}") from exc
    return {
        key: _json_value(payload[key])
        for key in sorted(allowed)
        if key in payload and not is_forbidden_field(key)
    }


def assert_no_forbidden_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if is_forbidden_field(str(key)):
                raise ValueError(f"forbidden public field at {path}.{key}")
            assert_no_forbidden_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_forbidden_fields(item, f"{path}[{index}]")


def make_quality(
    *,
    status: QualityStatus = "OK",
    missing: list[str] | tuple[str, ...] = (),
    errors: list[str] | tuple[str, ...] = (),
) -> PublicQuality:
    if status not in {"OK", "PARTIAL", "FAILED", "STALE"}:
        raise ValueError(f"invalid public snapshot quality status: {status}")
    return {
        "status": status,
        "missing": [str(item) for item in missing],
        "errors": [str(item) for item in errors],
    }


def make_envelope(
    *,
    snapshot_id: str,
    module: str,
    rule_version: str,
    as_of: str,
    source: PublicSource,
    quality: PublicQuality,
    data: Any,
) -> PublicEnvelope:
    if not snapshot_id or not rule_version or not as_of:
        raise ValueError("snapshot_id, rule_version and as_of are required")
    required_source = {
        "provider",
        "feed",
        "latency",
        "is_official_realtime",
        "session",
        "timezone",
    }
    missing_source = sorted(required_source.difference(source))
    if missing_source:
        raise ValueError(f"public source is incomplete: {', '.join(missing_source)}")
    envelope: PublicEnvelope = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "module": module,
        "rule_version": rule_version,
        "as_of": as_of,
        "source": _json_value(source),
        "quality": _json_value(quality),
        "data": _json_value(data),
    }
    assert_no_forbidden_fields(envelope)
    return envelope
