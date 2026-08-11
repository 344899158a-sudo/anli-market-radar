from __future__ import annotations

"""ANLI 3.1 validation and portfolio-risk overlay.

3.1 composes the immutable 3.0 dashboard. It does not change 1.0, 2.0, or
3.0 decisions and never creates brokerage orders.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any


SCHEMA_VERSION = "3.1.0"
EVENT_RISK_POLICY_VERSION = "1.0.0"


def _decimal(value: Any, fallback: str | None = None) -> Decimal | None:
    if value is None or value == "":
        return Decimal(fallback) if fallback is not None else None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(fallback) if fallback is not None else None
    return number if number.is_finite() else (Decimal(fallback) if fallback is not None else None)


def _pct(value: Decimal | None) -> str | None:
    return str(value.quantize(Decimal("0.01"))) if value is not None else None


def build_portfolio_risk(
    *,
    profile: dict[str, Any] | None,
    marked_holdings: set[str],
    symbols: list[dict[str, Any]],
    symbol_meta: dict[str, dict[str, Any]],
    account_rules: dict[str, Any],
    market_risk_rules: dict[str, Any],
    market_allocation_cap_pct: Any,
    caution_utilization_fraction: Any,
) -> dict[str, Any]:
    prices = {
        str(row.get("symbol") or "").upper(): _decimal(row.get("price"))
        for row in symbols
        if row.get("symbol")
    }
    latest = (profile or {}).get("payload") or {}
    account = latest.get("account") or {}
    positions = latest.get("positions") or []
    position_symbols = {str(item.get("symbol") or "").upper() for item in positions}
    missing_marked = sorted(symbol for symbol in marked_holdings if symbol not in position_symbols)
    missing_prices = sorted(symbol for symbol in position_symbols if prices.get(symbol) is None)

    checks: list[dict[str, Any]] = []
    if profile is None:
        checks.append({
            "key": "portfolio_profile",
            "label": "组合明细已录入",
            "status": "MISSING",
            "evidence": f"已标记持仓 {len(marked_holdings)} 只，但尚无数量、成本、止损与账户净值。",
            "next_condition": "录入账户净值以及每只持仓的数量、平均成本和止损价。",
        })
        return {
            "state": "DATA_GAP",
            "label": "组合风险无法计算",
            "can_add_risk": False,
            "account_equity": None,
            "position_count": len(marked_holdings),
            "detailed_position_count": 0,
            "coverage_pct": "0.00" if marked_holdings else "100.00",
            "market_value_pct": None,
            "open_risk_pct": None,
            "largest_theme": None,
            "missing_positions": sorted(marked_holdings),
            "missing_prices": [],
            "positions": [],
            "checks": checks,
            "next_action": "先补齐组合明细；在开放风险不可计算前，不扩大新增风险。",
            "profile": None,
            "marked_holdings": sorted(marked_holdings),
            "automatic_ordering": False,
        }

    equity = _decimal(account.get("equity"))
    if equity is None or equity <= 0:
        raise ValueError("portfolio equity must be greater than zero")
    daily = abs(_decimal(account.get("daily_drawdown_pct"), "0") or Decimal("0"))
    weekly = abs(_decimal(account.get("weekly_drawdown_pct"), "0") or Decimal("0"))
    monthly = abs(_decimal(account.get("monthly_drawdown_pct"), "0") or Decimal("0"))
    consecutive_losses = int(account.get("consecutive_losses") or 0)

    total_market_value = Decimal("0")
    total_open_risk = Decimal("0")
    theme_values: dict[str, Decimal] = {}
    detailed_positions = []
    invalid_stops: list[str] = []
    position_limit_hits: list[str] = []
    max_position_pct = _decimal(account_rules.get("max_position_market_value_pct"), "0") or Decimal("0")
    for item in positions:
        symbol = str(item.get("symbol") or "").upper()
        quantity = _decimal(item.get("quantity"), "0") or Decimal("0")
        average_cost = _decimal(item.get("average_cost"), "0") or Decimal("0")
        stop_price = _decimal(item.get("stop_price"), "0") or Decimal("0")
        price = prices.get(symbol)
        market_value = price * quantity if price is not None else None
        market_value_pct = market_value / equity * Decimal("100") if market_value is not None else None
        open_risk = None
        open_risk_pct = None
        if price is not None:
            if stop_price >= price:
                invalid_stops.append(symbol)
            else:
                open_risk = (price - stop_price) * quantity
                open_risk_pct = open_risk / equity * Decimal("100")
                total_open_risk += open_risk
            total_market_value += market_value or Decimal("0")
            theme = str((symbol_meta.get(symbol) or {}).get("sector") or "未分类")
            theme_values[theme] = theme_values.get(theme, Decimal("0")) + (market_value or Decimal("0"))
            if market_value_pct is not None and market_value_pct > max_position_pct:
                position_limit_hits.append(symbol)
        detailed_positions.append({
            "symbol": symbol,
            "sector": (symbol_meta.get(symbol) or {}).get("sector") or "未分类",
            "quantity": str(quantity),
            "average_cost": str(average_cost),
            "stop_price": str(stop_price),
            "market_price": _pct(price),
            "market_value_pct": _pct(market_value_pct),
            "open_risk_pct": _pct(open_risk_pct),
        })

    market_value_pct = total_market_value / equity * Decimal("100")
    open_risk_pct = total_open_risk / equity * Decimal("100")
    theme_pcts = {
        theme: value / equity * Decimal("100")
        for theme, value in theme_values.items()
    }
    largest_theme_name = max(theme_pcts, key=theme_pcts.get) if theme_pcts else None
    largest_theme_pct = theme_pcts.get(largest_theme_name) if largest_theme_name else None
    total_tracked = len(marked_holdings | position_symbols)
    coverage_pct = (
        Decimal(len(position_symbols - set(missing_prices))) / Decimal(total_tracked) * Decimal("100")
        if total_tracked
        else Decimal("100")
    )

    daily_limit = _decimal(account_rules.get("daily_drawdown_freeze_pct"), "0") or Decimal("0")
    weekly_limit = _decimal(account_rules.get("weekly_drawdown_freeze_pct"), "0") or Decimal("0")
    monthly_limit = _decimal(account_rules.get("monthly_drawdown_freeze_pct"), "0") or Decimal("0")
    consecutive_limit = int(account_rules.get("consecutive_loss_freeze_count") or 0)
    drawdown_hits = []
    if daily >= daily_limit:
        drawdown_hits.append(f"日回撤 {daily}% ≥ {daily_limit}%")
    if weekly >= weekly_limit:
        drawdown_hits.append(f"周回撤 {weekly}% ≥ {weekly_limit}%")
    if monthly >= monthly_limit:
        drawdown_hits.append(f"月回撤 {monthly}% ≥ {monthly_limit}%")
    if consecutive_losses >= consecutive_limit:
        drawdown_hits.append(f"连续亏损 {consecutive_losses} 次 ≥ {consecutive_limit} 次")

    max_positions = int(account_rules.get("max_positions") or 0)
    max_theme_pct = _decimal(account_rules.get("max_same_theme_exposure_pct"), "0") or Decimal("0")
    max_open_risk_pct = _decimal(market_risk_rules.get("max_total_open_risk_pct"), "0") or Decimal("0")
    market_cap = _decimal(market_allocation_cap_pct, "0") or Decimal("0")
    caution_fraction = _decimal(caution_utilization_fraction, "0.80") or Decimal("0.80")

    checks.extend([
        {
            "key": "drawdown_freeze",
            "label": "账户回撤与连续亏损熔断",
            "status": "TRIGGERED" if drawdown_hits else "PASS",
            "evidence": "；".join(drawdown_hits) if drawdown_hits else "未触及1.0账户熔断阈值。",
            "next_condition": "冻结新增风险并完成复盘；由人工确认后再恢复。" if drawdown_hits else "持续监控日、周、月回撤与连续亏损。",
        },
        {
            "key": "position_details",
            "label": "持仓明细与实时价格完整",
            "status": "MISSING" if missing_marked or missing_prices or invalid_stops else "PASS",
            "evidence": f"缺少持仓明细 {len(missing_marked)}；缺少价格 {len(missing_prices)}；无效止损 {len(invalid_stops)}。",
            "next_condition": "补齐所有已标记持仓并把止损价设在当前价格下方。",
        },
        {
            "key": "open_risk",
            "label": "组合开放风险",
            "status": "BLOCK" if open_risk_pct > max_open_risk_pct else "WARN" if open_risk_pct >= max_open_risk_pct * caution_fraction else "PASS",
            "evidence": f"开放风险 {_pct(open_risk_pct)}%；上限 {_pct(max_open_risk_pct)}%。",
            "next_condition": "降低仓位或收紧已验证止损，使开放风险回到上限以内。",
        },
        {
            "key": "market_exposure",
            "label": "市场环境仓位上限",
            "status": "BLOCK" if market_value_pct > market_cap else "WARN" if market_value_pct >= market_cap * caution_fraction else "PASS",
            "evidence": f"持仓市值 {_pct(market_value_pct)}%；当前环境上限 {_pct(market_cap)}%。",
            "next_condition": "将总持仓市值降到当前市场环境允许范围。",
        },
        {
            "key": "theme_concentration",
            "label": "同主题集中度",
            "status": "BLOCK" if largest_theme_pct is not None and largest_theme_pct > max_theme_pct else "PASS",
            "evidence": f"最大主题 {largest_theme_name or '—'} {_pct(largest_theme_pct) or '—'}%；上限 {_pct(max_theme_pct)}%。",
            "next_condition": "减少同一行业或主题的重复风险敞口。",
        },
        {
            "key": "position_limits",
            "label": "持仓数量与单仓上限",
            "status": "BLOCK" if len(positions) > max_positions or position_limit_hits else "PASS",
            "evidence": f"持仓 {len(positions)}/{max_positions}；超单仓上限：{', '.join(position_limit_hits) or '无'}。",
            "next_condition": "减少持仓数量或降低超限单仓。",
        },
    ])

    if drawdown_hits:
        state, label, next_action = "FROZEN", "账户熔断已触发", "冻结新增风险，先复盘回撤和连续亏损。"
    elif missing_marked or missing_prices or invalid_stops:
        state, label, next_action = "DATA_GAP", "组合证据不完整", "补齐持仓数量、成本、止损和实时价格后再评估新增风险。"
    elif any(item["status"] == "BLOCK" for item in checks):
        state, label, next_action = "BLOCKED", "组合风险超过边界", "先降低开放风险、总敞口或主题集中度。"
    elif any(item["status"] == "WARN" for item in checks):
        state, label, next_action = "CAUTION", "组合接近风险上限", "只允许降低风险，不主动扩大同方向敞口。"
    else:
        state, label, next_action = "PASS", "组合风险边界内", "仍需在券商实时数据下人工确认，系统不会自动下单。"

    return {
        "state": state,
        "label": label,
        "can_add_risk": state == "PASS",
        "account_equity": str(equity),
        "position_count": len(positions),
        "detailed_position_count": len(positions) - len(missing_prices),
        "coverage_pct": _pct(coverage_pct),
        "market_value_pct": _pct(market_value_pct),
        "open_risk_pct": _pct(open_risk_pct),
        "largest_theme": {"name": largest_theme_name, "exposure_pct": _pct(largest_theme_pct)} if largest_theme_name else None,
        "missing_positions": missing_marked,
        "missing_prices": missing_prices,
        "invalid_stops": invalid_stops,
        "positions": detailed_positions,
        "checks": checks,
        "next_action": next_action,
        "profile": {"portfolio_id": profile.get("portfolio_id"), "created_at": profile.get("created_at")},
        "input": latest,
        "marked_holdings": sorted(marked_holdings),
        "automatic_ordering": False,
    }


def build_portfolio_event_radar(
    *,
    event_calendar: dict[str, Any],
    portfolio_risk: dict[str, Any],
    symbols: list[dict[str, Any]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    policy = rules.get("event_risk") or {}
    if str(policy.get("version")) != EVENT_RISK_POLICY_VERSION:
        raise ValueError("ANLI 3.1 event-risk policy version mismatch")
    weeks = event_calendar.get("weeks") or []
    first_week = weeks[0] if weeks and isinstance(weeks[0], dict) else {}
    symbol_sectors = {
        str(row.get("symbol") or "").upper(): str(row.get("sector") or "").strip()
        for row in symbols
        if isinstance(row, dict) and row.get("symbol")
    }
    input_positions = ((portfolio_risk.get("input") or {}).get("positions") or [])
    detailed_positions = portfolio_risk.get("positions") or []
    focus_symbols = {
        str(value or "").upper()
        for value in portfolio_risk.get("marked_holdings") or []
        if value
    }
    focus_symbols.update(
        str(row.get("symbol") or "").upper()
        for row in [*input_positions, *detailed_positions]
        if isinstance(row, dict) and row.get("symbol")
    )
    focus_sectors = {
        symbol_sectors[symbol]
        for symbol in focus_symbols
        if symbol_sectors.get(symbol)
    }
    verified = event_calendar.get("verification_status") == "已核验"
    if not focus_symbols and not focus_sectors:
        return {
            "policy_version": EVENT_RISK_POLICY_VERSION,
            "state": "NO_SELECTION",
            "label": "尚未选择持仓或关注行业",
            "verification_status": event_calendar.get("verification_status"),
            "window": {
                "start": first_week.get("start"),
                "end": first_week.get("end"),
                "label": first_week.get("label"),
            },
            "focus_symbols": [],
            "focus_sectors": [],
            "event_count": 0,
            "critical_count": 0,
            "events": [],
            "decision_effect": "NONE",
            "next_action": "先在1.0标记持仓或在3.1录入组合；也可使用行业筛选查看相关事件。",
        }

    priority = {
        code: index
        for index, code in enumerate(policy.get("relevance_priority") or [])
    }
    global_scopes = {str(item) for item in policy.get("global_scopes") or []}
    relevant_events: list[dict[str, Any]] = []
    for raw in first_week.get("events") or []:
        if not isinstance(raw, dict):
            continue
        scopes = {str(item) for item in raw.get("scope") or [] if item}
        direct = sorted(focus_symbols.intersection(scopes))
        sector = sorted(focus_sectors.intersection(scopes))
        global_match = sorted(global_scopes.intersection(scopes))
        if direct:
            relevance, label, matched = "DIRECT", "持仓公司事件", direct
        elif sector:
            relevance, label, matched = "SECTOR", "持仓行业关联", sector
        elif global_match:
            relevance, label, matched = "GLOBAL", "全市场风险", global_match
        else:
            continue
        event = deepcopy(raw)
        event["relevance"] = relevance
        event["relevance_label"] = label
        event["matched"] = matched
        event["why_relevant"] = (
            f"直接影响持仓：{'、'.join(matched)}"
            if relevance == "DIRECT"
            else f"影响所处行业：{'、'.join(matched)}"
            if relevance == "SECTOR"
            else "宏观或指数级事件会影响全部持仓的风险预算"
        )
        relevant_events.append(event)
    relevant_events.sort(
        key=lambda event: (
            priority.get(str(event.get("relevance")), 99),
            str(event.get("at_et") or event.get("at") or ""),
        )
    )
    state = "UNVERIFIED" if not verified else "ACTIVE" if relevant_events else "NO_MATCH"
    return {
        "policy_version": EVENT_RISK_POLICY_VERSION,
        "state": state,
        "label": (
            "事件日历需要重新核验"
            if state == "UNVERIFIED"
            else "本周持仓与行业风险已匹配"
            if state == "ACTIVE"
            else "本周暂无匹配事件"
        ),
        "verification_status": event_calendar.get("verification_status"),
        "window": {
            "start": first_week.get("start"),
            "end": first_week.get("end"),
            "label": first_week.get("label"),
        },
        "focus_symbols": sorted(focus_symbols),
        "focus_sectors": sorted(focus_sectors),
        "event_count": len(relevant_events),
        "critical_count": sum(int(event.get("importance") or 0) >= 4 for event in relevant_events),
        "events": relevant_events,
        "decision_effect": "NONE",
        "next_action": (
            "先重新核验官方日历；核验完成前只把这些事件当作风险线索。"
            if not verified
            else "事件前检查盈利垫、止损和同主题总敞口；日历本身不会自动触发交易。"
        ),
    }


def build_v31_dashboard(
    *,
    base_dashboard: dict[str, Any],
    validation: dict[str, Any],
    portfolio_risk: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    if str(rules.get("version")) != SCHEMA_VERSION:
        raise ValueError("ANLI 3.1 rule configuration version mismatch")
    if str(base_dashboard.get("schema_version")) != str(rules.get("base_contract_version")):
        raise ValueError("ANLI 3.0 base contract is unavailable")
    dashboard = deepcopy(base_dashboard)
    dashboard["schema_version"] = SCHEMA_VERSION
    dashboard["system_version"] = "ANLI 3.1"
    dashboard["rule_version"] = SCHEMA_VERSION
    dashboard["meta"]["source_versions"]["validation_and_portfolio"] = SCHEMA_VERSION
    dashboard["meta"]["compatibility"] = deepcopy(rules.get("compatibility") or {})
    dashboard["meta"]["automatic_ordering"] = False
    dashboard["meta"]["research_only"] = True
    dashboard["validation"] = deepcopy(validation)
    dashboard["portfolio_risk"] = deepcopy(portfolio_risk)
    dashboard["portfolio_event_radar"] = build_portfolio_event_radar(
        event_calendar=dashboard.get("events") or {},
        portfolio_risk=portfolio_risk,
        symbols=dashboard.get("symbols") or [],
        rules=rules,
    )
    dashboard["model_labels"] = deepcopy(rules.get("model_labels") or {})
    dashboard["command"]["portfolio_state"] = portfolio_risk.get("state")
    dashboard["command"]["validation_state"] = validation.get("status")
    dashboard["command"]["stack"].extend([
        {
            "key": "portfolio",
            "label": "组合风险",
            "status": "PASS" if portfolio_risk.get("state") == "PASS" else "BLOCK" if portfolio_risk.get("state") in {"BLOCKED", "FROZEN"} else "MISSING" if portfolio_risk.get("state") == "DATA_GAP" else "CAUTION",
            "value": portfolio_risk.get("label"),
            "evidence": f"开放风险 {portfolio_risk.get('open_risk_pct') or '—'}%；总敞口 {portfolio_risk.get('market_value_pct') or '—'}%。",
            "next_condition": portfolio_risk.get("next_action"),
        },
        {
            "key": "validation",
            "label": "结果验证",
            "status": "PASS" if validation.get("sample_sufficient") else "CAUTION",
            "value": validation.get("label"),
            "evidence": f"影子设置 {validation.get('shadow_setup_count', 0)}；{validation.get('primary_horizon_sessions', 5)}日样本 {validation.get('primary_sample_count', 0)}/{validation.get('minimum_sample_count', 30)}。",
            "next_condition": "继续积累不可改写样本；达到门槛前不把后验统计称为胜率。",
        },
    ])
    dashboard["methodology"] = {
        "summary": "3.1在3.0统一决策之上增加不可改写的影子观察、结果验证和账户组合风险闸门；不改变1.0、2.0或3.0历史结论。",
        "decision_order": ["数据", "大盘", "行业", "剧本", "证据", "组合风险", "影子验证", "券商确认"],
        "automatic_ordering": False,
    }
    return dashboard
