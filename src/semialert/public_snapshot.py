from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

from .advanced_technical import aggregate_bars, build_advanced_analysis
from .decision_core import load_rule_config
from .event_calendar import build_event_calendar
from .opportunity import enrich_signal
from .public_snapshot_contract import (
    SCHEMA_VERSION,
    PublicEnvelope,
    PublicQuality,
    PublicSource,
    assert_no_forbidden_fields,
    is_forbidden_field,
    make_envelope,
    make_quality,
    select_public_fields,
)
from .qqq_decision import build_qqq_recommendation


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.^_-]{0,14}$")
SENSITIVE_URL_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|token|secret|password|authorization)="
)
SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?key|token|secret|password|authorization)"
    r"\s*[:=]\s*)([^\s&,;]+)"
)
BEARER_TEXT_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
FUNDAMENTAL_METRICS = (
    "revenue",
    "net_income",
    "operating_income",
    "operating_cash_flow",
    "assets",
    "liabilities",
)


class PublicSnapshotExportError(RuntimeError):
    pass


def _market_session(now: datetime) -> str:
    now_et = now.astimezone(ZoneInfo("America/New_York"))
    minutes = now_et.hour * 60 + now_et.minute
    if now_et.weekday() >= 5:
        return "CLOSED"
    if 570 <= minutes < 960:
        return "REGULAR"
    if 240 <= minutes < 570:
        return "PREMARKET"
    if 960 <= minutes < 1200:
        return "AFTERHOURS"
    return "CLOSED"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".manifest-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _source_from_status(status: dict[str, Any], session: str) -> PublicSource:
    provider = str(status.get("provider") or "").strip()
    feed = str(status.get("feed") or "").strip()
    if not provider or not feed:
        raise PublicSnapshotExportError("行情来源或 feed 缺失，拒绝生成公开快照")
    official_realtime = bool(status.get("is_official_realtime"))
    latency = (
        "static-snapshot-of-single-exchange-realtime"
        if official_realtime
        else "static-snapshot-of-public-near-realtime-or-delayed"
    )
    return {
        "provider": provider,
        "feed": feed,
        "latency": latency,
        "is_official_realtime": official_realtime,
        "session": session,
        "timezone": "America/New_York",
    }


def _event_source(session: str) -> PublicSource:
    return {
        "provider": "ANLI 官方日历汇总",
        "feed": "verified-calendar",
        "latency": "scheduled-verification",
        "is_official_realtime": False,
        "session": session,
        "timezone": "America/New_York",
    }


def _watchlist_source(session: str) -> PublicSource:
    return {
        "provider": "ANLI watchlist configuration",
        "feed": "config-watchlist",
        "latency": "static-configuration-snapshot",
        "is_official_realtime": False,
        "session": session,
        "timezone": "America/New_York",
    }


def _evidence_source(session: str) -> PublicSource:
    return {
        "provider": "ANLI AI second-layer review with public evidence metadata",
        "feed": "state-store-ai-evidence",
        "latency": "static-unverified-ai-snapshot",
        "is_official_realtime": False,
        "session": session,
        "timezone": "America/New_York",
    }


def _bounded_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    text = SENSITIVE_TEXT_PATTERN.sub(r"\1[REDACTED]", text)
    text = BEARER_TEXT_PATTERN.sub("Bearer [REDACTED]", text)
    return text[:limit]


def _bounded_text_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        text
        for item in value[:limit]
        if (text := _bounded_text(item, item_limit)) is not None
    ]


def _safe_public_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw or SENSITIVE_URL_PATTERN.search(unquote(raw)):
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
        if not address.is_global:
            return None
    except ValueError:
        pass
    if any(is_forbidden_field(name) for name, _ in parse_qsl(parsed.query)):
        return None
    return raw


def _mark_snapshot_only(analysis: dict[str, Any]) -> None:
    data = dict(analysis.get("data") or {})
    data["execution_ready"] = False
    data["snapshot_only"] = True
    analysis["data"] = data
    reasoning = dict(analysis.get("reasoning") or {})
    reasoning["data_gate"] = "Static snapshot; verify a live broker quote before execution."
    analysis["reasoning"] = reasoning


def _quality_from_errors(
    errors: dict[str, Any] | None = None,
    missing: Iterable[str] = (),
) -> PublicQuality:
    error_messages = [
        f"{name}: source unavailable"
        for name, message in sorted((errors or {}).items())
        if message
    ]
    missing_items = sorted({str(item) for item in missing if item})
    return make_quality(
        status="PARTIAL" if error_messages or missing_items else "OK",
        missing=missing_items,
        errors=error_messages,
    )


_QUALITY_PRIORITY = {"OK": 0, "PARTIAL": 1, "STALE": 2, "FAILED": 3}


def _combine_quality(*qualities: PublicQuality) -> PublicQuality:
    if not qualities:
        return make_quality()
    status = max(
        (quality["status"] for quality in qualities),
        key=lambda value: _QUALITY_PRIORITY[value],
    )
    return make_quality(
        status=status,
        missing=sorted(
            {
                item
                for quality in qualities
                for item in quality.get("missing", [])
            }
        ),
        errors=sorted(
            {
                item
                for quality in qualities
                for item in quality.get("errors", [])
            }
        ),
    )


def _market_quality(
    status: dict[str, Any],
    market_as_of: str,
    generated_at: datetime,
    session: str,
) -> PublicQuality:
    try:
        parsed = datetime.fromisoformat(market_as_of.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PublicSnapshotExportError("market_data_time is invalid") from exc
    if parsed.tzinfo is None:
        raise PublicSnapshotExportError("market_data_time must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    age_seconds = (generated_at - parsed).total_seconds()
    if age_seconds < -300:
        raise PublicSnapshotExportError("market_data_time is in the future")

    missing: list[str] = []
    errors: list[str] = []
    if status.get("history_cache_stale"):
        missing.append("history_cache_stale")
    if status.get("last_error"):
        errors.append("market_refresh: source unavailable")
    if status.get("history_error"):
        errors.append("market_history: source unavailable")
    if status.get("ohlcv_quality_errors"):
        missing.append("ohlcv_quality_partial")

    stale_after_seconds = 2 * 60 * 60 if session != "CLOSED" else 96 * 60 * 60
    if age_seconds > stale_after_seconds:
        missing.append("market_data_stale")
        quality_status = "STALE"
    elif errors or missing:
        quality_status = "PARTIAL"
    else:
        quality_status = "OK"
    return make_quality(
        status=quality_status,
        missing=sorted(set(missing)),
        errors=sorted(set(errors)),
    )

def _clean_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not SYMBOL_PATTERN.fullmatch(normalized):
        raise PublicSnapshotExportError(f"非法技术分析代码：{symbol}")
    return normalized


def _watchlist_payload(
    engine: Any,
    *,
    evidence_symbols: set[str],
) -> dict[str, Any]:
    config = getattr(engine, "config", None)
    if config is None:
        raise PublicSnapshotExportError("MonitorEngine config is unavailable")
    try:
        symbols = [_clean_symbol(symbol) for symbol in config.symbols]
        symbol_meta = dict(config.symbol_meta)
        sector_benchmarks = dict(config.sector_benchmarks)
        benchmark = _clean_symbol(config.get("benchmark", "QQQ"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PublicSnapshotExportError("MonitorEngine watchlist config is incomplete") from exc

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        meta = dict(symbol_meta.get(symbol) or {})
        sector = str(meta.get("sector") or "").strip()
        if not sector:
            raise PublicSnapshotExportError(f"{symbol} is missing a watchlist sector")
        row = {
            "symbol": symbol,
            "name": meta.get("name"),
            "sector": sector,
            "sector_benchmark": sector_benchmarks.get(sector),
            "quality_approved": bool(meta.get("quality_approved")),
            "catalyst_date": meta.get("catalyst_date"),
            "unlisted": bool(meta.get("unlisted")),
            "evidence_available": symbol in evidence_symbols,
        }
        rows.append(select_public_fields("watchlist-symbol", row))

    sector_order = list(sector_benchmarks)
    for row in rows:
        if row["sector"] not in sector_order:
            sector_order.append(row["sector"])
    sectors = [
        select_public_fields(
            "watchlist-sector",
            {
                "name": sector,
                "benchmark": sector_benchmarks.get(sector),
                "symbols": [
                    row["symbol"] for row in rows if row["sector"] == sector
                ],
            },
        )
        for sector in sector_order
    ]
    raw_sector_status = dict(
        (getattr(engine, "status", {}) or {}).get("sector_status") or {}
    )
    sector_status: dict[str, dict[str, Any]] = {}
    for sector in sector_order:
        raw = dict(raw_sector_status.get(sector) or {})
        above_ma50 = raw.get("above_ma50")
        sector_status[sector] = {
            "benchmark": raw.get("benchmark") or sector_benchmarks.get(sector),
            "above_ma50": above_ma50 if isinstance(above_ma50, bool) else None,
        }
    return select_public_fields(
        "watchlist",
        {
            "benchmark": benchmark,
            "symbol_count": len(rows),
            "sector_benchmarks": sector_benchmarks,
            "sector_status": sector_status,
            "sectors": sectors,
            "symbols": rows,
        },
    )


def _evidence_payload(raw: dict[str, Any]) -> dict[str, Any]:
    symbol = _clean_symbol(str(raw.get("symbol") or ""))
    analyzed_at = str(raw.get("analyzed_at") or "").strip()
    if not analyzed_at:
        raise PublicSnapshotExportError(f"{symbol} AI evidence has no analyzed_at")

    analysis = select_public_fields("evidence-analysis", raw)
    for field, limit in {
        "verdict": 40,
        "event_class": 40,
        "event_urgency": 20,
        "moat": 20,
        "key_event": 300,
        "price_move_driver": 400,
        "summary": 500,
        "entry_conclusion": 80,
        "buy_gate": 40,
    }.items():
        if field in analysis:
            analysis[field] = _bounded_text(analysis[field], limit)
    for field, count in {
        "reasons": 6,
        "red_flags": 12,
        "positive_factors": 12,
        "evidence_gaps": 12,
        "next_checks": 4,
    }.items():
        analysis[field] = _bounded_text_list(
            analysis.get(field),
            limit=count,
            item_limit=500,
        )

    evidence_quality = select_public_fields(
        "evidence-quality",
        dict(raw.get("evidence_quality") or {}),
    )
    if "limitation" in evidence_quality:
        evidence_quality["limitation"] = _bounded_text(
            evidence_quality["limitation"],
            800,
        )
    market_context = select_public_fields(
        "evidence-market-context",
        dict(raw.get("market_context") or {}),
    )

    news: list[dict[str, Any]] = []
    for item in list(raw.get("news_items") or [])[:24]:
        if not isinstance(item, dict):
            continue
        row = select_public_fields("evidence-news", item)
        row["title"] = _bounded_text(row.get("title"), 400)
        row["publisher"] = _bounded_text(row.get("publisher"), 120)
        row["url"] = _safe_public_url(row.get("url"))
        row["risk_keywords"] = _bounded_text_list(
            row.get("risk_keywords"),
            limit=12,
            item_limit=80,
        )
        if row.get("title") and row.get("url"):
            news.append(row)

    filings: list[dict[str, Any]] = []
    for item in list(raw.get("sec_filings") or [])[:12]:
        if not isinstance(item, dict):
            continue
        row = select_public_fields("evidence-sec-filing", item)
        row["description"] = _bounded_text(row.get("description"), 500)
        row["items"] = _bounded_text(row.get("items"), 200)
        row["url"] = _safe_public_url(row.get("url"))
        if row.get("form") and row.get("url"):
            filings.append(row)

    fundamentals = None
    raw_fundamentals = raw.get("fundamentals")
    if isinstance(raw_fundamentals, dict):
        base = {
            key: raw_fundamentals.get(key)
            for key in ("cik", "entity", "source_url")
        }
        fundamentals = select_public_fields("evidence-fundamentals", base)
        fundamentals["source_url"] = _safe_public_url(
            fundamentals.get("source_url")
        )
        metrics: dict[str, list[dict[str, Any]]] = {}
        raw_metrics = raw_fundamentals.get("metrics") or {}
        if isinstance(raw_metrics, dict):
            for metric in FUNDAMENTAL_METRICS:
                values = raw_metrics.get(metric) or []
                metrics[metric] = [
                    select_public_fields("evidence-fundamental-row", row)
                    for row in list(values)[:4]
                    if isinstance(row, dict)
                ]
        fundamentals["metrics"] = metrics

    limitations = [
        "AI output is unverified and cannot change trading state.",
        "News entries contain title metadata only; open the source URL and verify the full text.",
    ]
    quality_limitation = _bounded_text(evidence_quality.get("limitation"), 800)
    if quality_limitation:
        limitations.append(quality_limitation)
    return select_public_fields(
        "evidence",
        {
            "symbol": symbol,
            "company": _bounded_text(raw.get("company"), 200),
            "analyzed_at": analyzed_at,
            "verification_status": "AI_UNVERIFIED",
            "analysis": analysis,
            "evidence_quality": evidence_quality,
            "market_context": market_context,
            "news": news,
            "sec_filings": filings,
            "fundamentals": fundamentals,
            "limitations": limitations,
        },
    )


def _evidence_quality(raw: dict[str, Any]) -> PublicQuality:
    missing: list[str] = []
    if not raw.get("news_items"):
        missing.append("news_titles")
    if not raw.get("sec_filings") and not raw.get("fundamentals"):
        missing.append("sec_evidence")
    evidence_quality = dict(raw.get("evidence_quality") or {})
    grade = str(evidence_quality.get("grade") or "").strip().casefold()
    if grade in {"\u4e0d\u8db3", "low", "insufficient"}:
        missing.append("independent_corroboration")
    errors = {"collection": True} if evidence_quality.get("collection_errors") else {}
    return _quality_from_errors(errors, missing)


class PublicSnapshotExporter:
    def __init__(
        self,
        engine: Any,
        output_root: str | Path,
        *,
        rule_version: str,
        event_calendar_builder: Callable[[], dict[str, Any]] = build_event_calendar,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.engine = engine
        self.output_root = Path(output_root).resolve()
        self.rule_version = str(rule_version).strip()
        self.event_calendar_builder = event_calendar_builder
        self._now = now or (lambda: datetime.now(timezone.utc))
        if not self.rule_version:
            raise ValueError("rule_version is required")

    def export(
        self,
        *,
        technical_symbols: Iterable[str] = (),
        evidence_symbols: Iterable[str] | None = None,
        bulk_watchlist_technical: bool = False,
    ) -> dict[str, Any]:
        generated_at = self._now()
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        generated_at = generated_at.astimezone(timezone.utc)
        snapshot_id = (
            generated_at.strftime("%Y%m%dT%H%M%S%fZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        try:
            documents = self._build_documents(
                snapshot_id,
                generated_at,
                technical_symbols=technical_symbols,
                evidence_symbols=evidence_symbols,
                bulk_watchlist_technical=bulk_watchlist_technical,
            )
            return self._publish(snapshot_id, generated_at, documents)
        except PublicSnapshotExportError:
            raise
        except Exception as exc:
            raise PublicSnapshotExportError(
                f"公开快照生成失败，上一版 manifest 保持不变：{exc}"
            ) from exc

    def _build_documents(
        self,
        snapshot_id: str,
        generated_at: datetime,
        *,
        technical_symbols: Iterable[str],
        evidence_symbols: Iterable[str] | None,
        bulk_watchlist_technical: bool,
    ) -> dict[str, PublicEnvelope]:
        status = dict(getattr(self.engine, "status", {}) or {})
        session = _market_session(generated_at)
        market_source = _source_from_status(status, session)
        market_as_of = str(
            status.get("market_data_time")
            or status.get("last_refresh")
            or ""
        )
        if not market_as_of:
            raise PublicSnapshotExportError(
                "引擎尚无 market_data_time/last_refresh，拒绝覆盖公开快照"
            )

        market_overview = status.get("market_overview")
        if not isinstance(market_overview, dict) or not market_overview:
            raise PublicSnapshotExportError("市场环境尚未就绪")
        overview_as_of = str(market_overview.get("as_of") or market_as_of)
        market_quality = _market_quality(
            status, overview_as_of, generated_at, session
        )
        sector_pulse = status.get("sector_pulse")
        if not isinstance(sector_pulse, dict) or not sector_pulse:
            raise PublicSnapshotExportError("半导体板块信号尚未就绪")

        raw_signals = list(self.engine.store.get_signals())
        if not raw_signals:
            raise PublicSnapshotExportError("StateStore 尚无股票信号")
        ai_by_symbol = {
            str(item.get("symbol") or "").upper(): item
            for item in self.engine.store.get_ai_analyses()
            if isinstance(item, dict) and item.get("symbol")
        }
        public_signals: list[dict[str, Any]] = []
        analysis_signals: dict[str, dict[str, Any]] = {}
        for raw_signal in raw_signals:
            symbol = _clean_symbol(str(raw_signal.get("symbol") or ""))
            signal = dict(raw_signal)
            signal["symbol"] = symbol
            signal["holding"] = False
            signal["exit_signal"] = None
            enriched = enrich_signal(signal, ai_by_symbol.get(symbol))
            analysis_signals[symbol] = enriched
            public_signals.append(select_public_fields("opportunity", enriched))
        public_signals.sort(
            key=lambda row: (
                -bool((row.get("opportunity") or {}).get("can_act")),
                -int((row.get("opportunity") or {}).get("final_score") or 0),
                str(row.get("symbol") or ""),
            )
        )


        if evidence_symbols is None:
            selected_evidence_symbols = sorted(
                set(ai_by_symbol).intersection(analysis_signals)
            )
        else:
            selected_evidence_symbols = list(
                dict.fromkeys(_clean_symbol(symbol) for symbol in evidence_symbols)
            )
            unknown_evidence = sorted(
                set(selected_evidence_symbols).difference(analysis_signals)
            )
            if unknown_evidence:
                raise PublicSnapshotExportError(
                    "Evidence symbols are outside the current watchlist: "
                    + ", ".join(unknown_evidence)
                )
            missing_evidence = sorted(
                set(selected_evidence_symbols).difference(ai_by_symbol)
            )
            if missing_evidence:
                raise PublicSnapshotExportError(
                    "StateStore has no AI evidence for: "
                    + ", ".join(missing_evidence)
                )
        watchlist = _watchlist_payload(
            self.engine,
            evidence_symbols=set(ai_by_symbol),
        )
        calendar = self.event_calendar_builder()
        if not isinstance(calendar, dict) or not calendar:
            raise PublicSnapshotExportError("事件日历为空")
        calendar_as_of = str(calendar.get("generated_at") or generated_at.isoformat())
        calendar_verified = (
            str(calendar.get("verification_status") or "").strip() == "已核验"
        )

        missing_signal_data = [
            str(row.get("symbol"))
            for row in public_signals
            if row.get("status") == "NO_DATA"
        ]
        documents: dict[str, PublicEnvelope] = {
            "watchlist.json": make_envelope(
                snapshot_id=snapshot_id,
                module="watchlist",
                rule_version=self.rule_version,
                as_of=generated_at.isoformat(),
                source=_watchlist_source(session),
                quality=_quality_from_errors(),
                data=watchlist,
            ),
            "market-overview.json": make_envelope(
                snapshot_id=snapshot_id,
                module="market-overview",
                rule_version=self.rule_version,
                as_of=overview_as_of,
                source=market_source,
                quality=market_quality,
                data=select_public_fields("market-overview", market_overview),
            ),
            "event-calendar.json": make_envelope(
                snapshot_id=snapshot_id,
                module="event-calendar",
                rule_version=self.rule_version,
                as_of=calendar_as_of,
                source=_event_source(session),
                quality=_quality_from_errors(
                    missing=[] if calendar_verified else ["calendar_verification"]
                ),
                data=select_public_fields("event-calendar", calendar),
            ),
            "sector-pulse.json": make_envelope(
                snapshot_id=snapshot_id,
                module="sector-pulse",
                rule_version=self.rule_version,
                as_of=market_as_of,
                source=market_source,
                quality=_combine_quality(
                    market_quality,
                    _quality_from_errors(
                        missing=["sector_members"]
                        if not sector_pulse.get("members")
                        else []
                    ),
                ),
                data=select_public_fields("sector-pulse", sector_pulse),
            ),
            "opportunities.json": make_envelope(
                snapshot_id=snapshot_id,
                module="opportunities",
                rule_version=self.rule_version,
                as_of=market_as_of,
                source=market_source,
                quality=_combine_quality(
                    market_quality,
                    _quality_from_errors(missing=missing_signal_data),
                ),
                data=public_signals,
            ),
        }

        for symbol in selected_evidence_symbols:
            raw_evidence = ai_by_symbol[symbol]
            evidence = _evidence_payload(raw_evidence)
            documents[f"evidence/{symbol}.json"] = make_envelope(
                snapshot_id=snapshot_id,
                module="evidence",
                rule_version=self.rule_version,
                as_of=evidence["analyzed_at"],
                source=_evidence_source(session),
                quality=_evidence_quality(raw_evidence),
                data=evidence,
            )

        qqq_analysis = self._build_qqq_analysis(
            market_overview,
            market_source,
            session,
        )
        qqq_errors = qqq_analysis.get("timeframe_errors") or {}
        qqq_as_of = str(
            (qqq_analysis.get("data") or {}).get("quote_time") or market_as_of
        )
        documents["qqq-analysis.json"] = make_envelope(
            snapshot_id=snapshot_id,
            module="qqq-analysis",
            rule_version=self.rule_version,
            as_of=qqq_as_of,
            source=market_source,
            quality=_combine_quality(
                market_quality, _quality_from_errors(qqq_errors)
            ),
            data=select_public_fields("qqq-analysis", qqq_analysis),
        )

        if bulk_watchlist_technical:
            selected_symbols = [
                str(row["symbol"]) for row in watchlist["symbols"]
            ]
        else:
            selected_symbols = list(
                dict.fromkeys(_clean_symbol(symbol) for symbol in technical_symbols)
            )
        unknown_symbols = sorted(set(selected_symbols).difference(analysis_signals))
        if unknown_symbols:
            raise PublicSnapshotExportError(
                "技术分析代码不在当前观察池："
                + "、".join(unknown_symbols)
            )
        for symbol in selected_symbols:
            missing_timeframes: list[str] = []
            if bulk_watchlist_technical:
                technical, errors, missing_timeframes = self._build_bulk_technical(
                    symbol,
                    analysis_signals[symbol],
                    market_source,
                    session,
                )
            else:
                technical = self._build_technical(
                    symbol,
                    analysis_signals[symbol],
                    market_source,
                    session,
                )
                errors = technical.get("timeframe_errors") or {}
            as_of = str(
                (technical.get("data") or {}).get("quote_time")
                or analysis_signals[symbol].get("quote_time")
                or market_as_of
            )
            documents[f"technical/{symbol}.json"] = make_envelope(
                snapshot_id=snapshot_id,
                module="technical",
                rule_version=self.rule_version,
                as_of=as_of,
                source=market_source,
                quality=_combine_quality(
                    market_quality,
                    _quality_from_errors(errors, missing_timeframes),
                ),
                data=select_public_fields("technical", technical),
            )
        return documents

    def _build_bulk_technical(
        self,
        symbol: str,
        signal: dict[str, Any],
        source: PublicSource,
        session: str,
    ) -> tuple[dict[str, Any], dict[str, str], list[str]]:
        missing = ["15m", "1h", "4h"]
        errors: dict[str, str] = {}
        daily = list((getattr(self.engine, "history", {}) or {}).get(symbol) or [])
        if len(daily) < 35:
            missing = ["1D", "1W", *missing]
            errors["1D/1W"] = "insufficient cached daily history"
            return {"symbol": symbol}, errors, missing
        weekly = aggregate_bars(daily, weekly=True)
        try:
            analysis = build_advanced_analysis(
                symbol,
                {"1D": daily, "1W": weekly},
                signal,
                source["provider"],
                session,
                source["is_official_realtime"],
            )
        except ValueError:
            missing = ["1D", "1W", *missing]
            errors["1D/1W"] = "cached daily history failed the data gate"
            return {"symbol": symbol}, errors, missing
        _mark_snapshot_only(analysis)
        analysis["timeframe_errors"] = errors
        return analysis, errors, missing

    def _build_technical(
        self,
        symbol: str,
        signal: dict[str, Any],
        source: PublicSource,
        session: str,
    ) -> dict[str, Any]:
        timeframes, errors = self.engine.technical_timeframes(symbol)
        analysis = build_advanced_analysis(
            symbol,
            timeframes,
            signal,
            source["provider"],
            session,
            source["is_official_realtime"],
        )
        _mark_snapshot_only(analysis)
        analysis["timeframe_errors"] = dict(errors or {})
        return analysis

    def _build_qqq_analysis(
        self,
        market_overview: dict[str, Any],
        source: PublicSource,
        session: str,
    ) -> dict[str, Any]:
        qqq = ((market_overview.get("assets") or {}).get("QQQ") or {})
        if not qqq.get("price"):
            raise PublicSnapshotExportError("QQQ 最新行情缺失")
        signal = {
            "symbol": "QQQ",
            "price": qqq["price"],
            "quote_time": qqq.get("quote_time") or market_overview.get("as_of"),
            "holding": False,
            "opportunity": {
                "can_act": market_overview.get("regime")
                in {"STRONG_LOW_VOL", "STRONG_HIGH_VOL"},
                "next_action": market_overview.get("action")
                or "等待市场环境确认",
            },
        }
        timeframes, errors = self.engine.technical_timeframes("QQQ")
        result = build_advanced_analysis(
            "QQQ",
            timeframes,
            signal,
            source["provider"],
            session,
            source["is_official_realtime"],
        )
        _mark_snapshot_only(result)
        result["timeframe_errors"] = dict(errors or {})
        result["recommendation"] = build_qqq_recommendation(
            result,
            market_overview,
        )
        result["market_context"] = {
            "score": market_overview.get("score"),
            "regime": market_overview.get("regime"),
            "regime_label": market_overview.get("regime_label"),
            "position_label": market_overview.get("position_label"),
            "action": market_overview.get("action"),
            "breadth": market_overview.get("breadth"),
            "qqq": qqq,
            "vix": (market_overview.get("assets") or {}).get("^VIX"),
        }
        return result

    def _publish(
        self,
        snapshot_id: str,
        generated_at: datetime,
        documents: dict[str, PublicEnvelope],
    ) -> dict[str, Any]:
        self.output_root.mkdir(parents=True, exist_ok=True)
        snapshots_root = self.output_root / "snapshots"
        snapshots_root.mkdir(exist_ok=True)
        final_snapshot = snapshots_root / snapshot_id
        if final_snapshot.exists():
            raise PublicSnapshotExportError(
                f"快照目录已存在：{final_snapshot.name}"
            )

        module_entries: dict[str, dict[str, Any]] = {}
        with tempfile.TemporaryDirectory(
            prefix=".snapshot-staging-",
            dir=str(self.output_root),
        ) as staging_name:
            staged_snapshot = Path(staging_name) / snapshot_id
            staged_snapshot.mkdir()
            for relative_name, envelope in sorted(documents.items()):
                assert_no_forbidden_fields(envelope)
                content = _json_bytes(envelope)
                target = staged_snapshot / relative_name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                module_key = relative_name.removesuffix(".json")
                module_entries[module_key] = {
                    "path": (
                        f"snapshots/{snapshot_id}/"
                        + relative_name.replace("\\", "/")
                    ),
                    "as_of": envelope["as_of"],
                    "quality": envelope["quality"],
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                }

            aggregate_status = max(
                (
                    entry["quality"]["status"]
                    for entry in module_entries.values()
                ),
                key=lambda value: _QUALITY_PRIORITY[value],
                default="FAILED",
            )
            status = dict(getattr(self.engine, "status", {}) or {})
            session = _market_session(generated_at)
            source = _source_from_status(status, session)
            manifest: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "rule_version": self.rule_version,
                "generated_at": generated_at.isoformat(),
                "as_of": str(
                    status.get("market_data_time")
                    or status.get("last_refresh")
                    or generated_at.isoformat()
                ),
                "source": source,
                "quality": make_quality(status=aggregate_status),
                "modules": module_entries,
            }
            assert_no_forbidden_fields(manifest)
            manifest_content = _json_bytes(manifest)
            (staged_snapshot / "manifest.json").write_bytes(manifest_content)

            os.replace(staged_snapshot, final_snapshot)
            _atomic_write_bytes(
                self.output_root / "manifest.json",
                manifest_content,
            )
        return manifest


def export_current_snapshot(
    engine: Any,
    output_root: str | Path,
    *,
    rule_version: str,
    technical_symbols: Iterable[str] = (),
    evidence_symbols: Iterable[str] | None = None,
    bulk_watchlist_technical: bool = False,
    event_calendar_builder: Callable[[], dict[str, Any]] = build_event_calendar,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    return PublicSnapshotExporter(
        engine,
        output_root,
        rule_version=rule_version,
        event_calendar_builder=event_calendar_builder,
        now=now,
    ).export(
        technical_symbols=technical_symbols,
        evidence_symbols=evidence_symbols,
        bulk_watchlist_technical=bulk_watchlist_technical,
    )


def export_ready_engine_snapshot(
    engine: Any,
    output_root: str | Path,
    *,
    project_root: str | Path | None = None,
    technical_symbols: Iterable[str] = (),
    evidence_symbols: Iterable[str] | None = None,
    bulk_watchlist_technical: bool = True,
    event_calendar_builder: Callable[[], dict[str, Any]] = build_event_calendar,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Export from an already-refreshed in-process MonitorEngine.

    This entry never starts another engine or refresh cycle. Bulk mode uses only
    the engine's cached daily history for watchlist technical shards; QQQ keeps
    the existing full multi-timeframe builder.
    """
    status = dict(getattr(engine, "status", {}) or {})
    required = ("last_refresh", "market_overview", "sector_pulse")
    missing = [name for name in required if not status.get(name)]
    if missing:
        raise PublicSnapshotExportError(
            "MonitorEngine is not ready: " + ", ".join(missing)
        )
    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    rule_config = load_rule_config(root / "config" / "rules" / "v1.yaml")
    return export_current_snapshot(
        engine,
        output_root,
        rule_version=str(rule_config["version"]),
        technical_symbols=technical_symbols,
        evidence_symbols=evidence_symbols,
        bulk_watchlist_technical=bulk_watchlist_technical,
        event_calendar_builder=event_calendar_builder,
        now=now,
    )
