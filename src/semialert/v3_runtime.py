from __future__ import annotations

"""Compose ANLI 3.0 from the preserved 1.0 evidence and 2.0 playbook layer.

The composer is read-only.  It does not fetch market data, create orders, or
mutate either legacy engine.  The 2.0 playbook entry state is the canonical
research state; the 1.0 opportunity stage remains visible as supporting
evidence and for compatibility.
"""

from copy import deepcopy
from datetime import datetime
from typing import Any


SCHEMA_VERSION = "3.0.0"


def _state_for(
    decision: dict[str, Any],
    legacy: dict[str, Any] | None,
    rules: dict[str, Any],
) -> dict[str, Any]:
    entry = decision.get("entry") or {}
    source_status = str(decision.get("source_status") or "")
    legacy_status = str((legacy or {}).get("status") or "")
    entry_state = str(entry.get("state") or "UNKNOWN")
    if legacy is None or source_status == "NO_DATA" or legacy_status == "NO_DATA":
        entry_state = "UNKNOWN"
    mapping = rules.get("research_state_map") or {}
    state = deepcopy(mapping.get(entry_state) or mapping.get("UNKNOWN") or {})
    state.setdefault("code", "DATA_GAP")
    state.setdefault("label", "数据不足")
    state.setdefault("priority", 0)
    state["source_entry_state"] = entry_state
    state["research_only"] = True
    state["automatic_ordering"] = False
    return state


def _merged_symbol(
    decision: dict[str, Any],
    legacy: dict[str, Any] | None,
    rules: dict[str, Any],
) -> dict[str, Any]:
    state = _state_for(decision, legacy, rules)
    legacy = legacy or {}
    opportunity = deepcopy(legacy.get("opportunity") or {})
    ai_analysis = deepcopy(legacy.get("ai_analysis"))
    primary_constraint = deepcopy(decision.get("primary_constraint") or {})
    next_action = str(
        decision.get("next_best_action")
        or primary_constraint.get("next_condition")
        or opportunity.get("next_action")
        or "等待数据与规则条件完整"
    )
    price = decision.get("price")
    if price is None:
        price = legacy.get("price")
    data_gap = state.get("code") == "DATA_GAP"
    return {
        "symbol": decision.get("symbol") or legacy.get("symbol"),
        "name": decision.get("name") or legacy.get("name"),
        "sector": decision.get("sector") or legacy.get("sector"),
        "sector_benchmark": decision.get("sector_benchmark") or legacy.get("sector_benchmark"),
        "price": None if data_gap else price,
        "quote_time": decision.get("quote_time") or legacy.get("quote_time"),
        "day_change_pct": None if data_gap else decision.get("day_change_pct"),
        "distance_ma50_pct": None if data_gap else decision.get("distance_ma50_pct"),
        "drawdown20_pct": None if data_gap else decision.get("drawdown20_pct"),
        "ma50": None if data_gap else decision.get("ma50"),
        "rsi14": None if data_gap else decision.get("rsi14"),
        "volume_ratio": None if data_gap else decision.get("volume_ratio"),
        "holding": bool(legacy.get("holding")),
        "research_state": state,
        "opportunity": opportunity,
        "legacy_signal": {
            "status": legacy.get("status"),
            "score": legacy.get("score"),
            "reason": legacy.get("reason"),
            "checks": deepcopy(legacy.get("checks") or {}),
            "failed_checks": deepcopy(legacy.get("failed_checks") or []),
        },
        "playbook": deepcopy(decision.get("playbook") or {}),
        "event": deepcopy(decision.get("event")),
        "event_phase": deepcopy(decision.get("event_phase") or {}),
        "entry": deepcopy(decision.get("entry") or {}),
        "criteria": deepcopy(decision.get("criteria") or []),
        "evidence_completion_pct": decision.get("evidence_completion_pct"),
        "evidence_summary": deepcopy(decision.get("evidence_summary") or {}),
        "primary_constraint": primary_constraint,
        "next_action": next_action,
        "plan": deepcopy(decision.get("plan") or {}),
        "decision_stack": deepcopy(decision.get("decision_stack") or []),
        "driver_tree": deepcopy(decision.get("driver_tree") or {}),
        "ai_analysis": ai_analysis,
        "rank_within_playbook": decision.get("rank_within_playbook"),
        "source_status": decision.get("source_status"),
    }


def build_v3_dashboard(
    *,
    v2_dashboard: dict[str, Any],
    engine_status: dict[str, Any],
    market_overview: dict[str, Any],
    legacy_signals: list[dict[str, Any]],
    event_calendar: dict[str, Any],
    sector_pulse: dict[str, Any] | None,
    alerts: list[dict[str, Any]],
    rules: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return the single read-only contract consumed by the ANLI 3.0 UI."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if str(rules.get("version")) != SCHEMA_VERSION:
        raise ValueError("ANLI 3.0 rule configuration version mismatch")
    decisions = v2_dashboard.get("symbols")
    if not isinstance(decisions, list):
        raise ValueError("2.0 symbol decisions are unavailable")

    legacy_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in legacy_signals
        if row.get("symbol")
    }
    symbols = [
        _merged_symbol(
            decision,
            legacy_by_symbol.get(str(decision.get("symbol") or "").upper()),
            rules,
        )
        for decision in decisions
    ]
    symbols.sort(
        key=lambda row: (
            int((row.get("research_state") or {}).get("priority", 99)),
            -int(row.get("evidence_completion_pct") or 0),
            -int((row.get("opportunity") or {}).get("final_score") or 0),
            str(row.get("symbol") or ""),
        )
    )
    counts: dict[str, int] = {}
    for row in symbols:
        code = str((row.get("research_state") or {}).get("code") or "DATA_GAP")
        counts[code] = counts.get(code, 0) + 1

    quality = deepcopy(v2_dashboard.get("data_quality") or {})
    missing_legacy = sorted(
        str(row.get("symbol") or "")
        for row in decisions
        if str(row.get("symbol") or "").upper() not in legacy_by_symbol
    )
    if missing_legacy:
        quality["status"] = "PARTIAL"
        quality.setdefault("issues", []).append(
            f"1.0证据层缺少 {len(missing_legacy)} 只股票"
        )
    quality["missing_legacy_symbols"] = missing_legacy

    command = deepcopy(v2_dashboard.get("command_brief") or {})
    command["risk_policy"] = {
        "canonical_source": rules.get("canonical_risk_source"),
        "canonical_rule_version": rules.get("canonical_risk_rule_version"),
        "legacy_v1_status": "preserved-for-compatibility",
        "research_only": True,
        "automatic_ordering": False,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "system_version": "ANLI 3.0",
        "rule_version": str(rules["version"]),
        "generated_at": now.isoformat(),
        "meta": {
            "as_of": (v2_dashboard.get("meta") or {}).get("as_of")
            or engine_status.get("market_data_time"),
            "source": deepcopy((v2_dashboard.get("meta") or {}).get("source") or {}),
            "source_versions": {
                "principle_and_opportunity": "1.0-compatible",
                "playbook": v2_dashboard.get("rule_version"),
                "unified_contract": str(rules["version"]),
            },
            "compatibility": deepcopy(rules.get("compatibility") or {}),
            "automatic_ordering": False,
            "research_only": True,
        },
        "data_quality": quality,
        "command": command,
        "market": {
            "gate": deepcopy(v2_dashboard.get("market_gate") or {}),
            "overview": deepcopy(market_overview),
            "qqq": deepcopy(v2_dashboard.get("qqq") or {}),
            "sector": deepcopy(v2_dashboard.get("sector") or {}),
            "sector_pulse": deepcopy(sector_pulse or {}),
        },
        "events": deepcopy(event_calendar),
        "playbook_radar": deepcopy(v2_dashboard.get("playbook_radar") or {}),
        "queue_summary": {
            "symbol_count": len(symbols),
            "counts": counts,
            "canonical_state_source": "2.0-playbook-entry",
        },
        "symbols": symbols,
        "evidence": {
            "recent_alerts": deepcopy(alerts[:30]),
            "alert_count_returned": min(len(alerts), 30),
        },
        "methodology": {
            "summary": "1.0保留完整市场与原则证据，2.0提供剧本与保守风险口径，3.0只做统一编排与展示。",
            "decision_order": ["数据", "大盘", "行业", "剧本", "证据", "价格触发", "券商确认"],
            "automatic_ordering": False,
        },
    }
