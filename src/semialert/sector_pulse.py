from __future__ import annotations

from statistics import median
from typing import Any

from .strategy import moving_average


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _benchmark_snapshot(bars: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    closes = [_num(bar.get("c")) for bar in bars if bar.get("c") is not None]
    latest = snapshot.get("latestTrade") or {}
    daily = snapshot.get("dailyBar") or {}
    previous = snapshot.get("prevDailyBar") or {}
    price = _num(latest.get("p"), _num(daily.get("c"), closes[-1] if closes else 0.0))
    prev_close = _num(previous.get("c"), closes[-1] if closes else price)
    ma50 = moving_average(closes[-49:] + [price], 50) if len(closes) >= 49 else None
    return {
        "price": round(price, 3),
        "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else None,
        "ma50": round(ma50, 3) if ma50 else None,
        "distance_ma50_pct": round((price / ma50 - 1) * 100, 2) if ma50 else None,
        "above_ma50": bool(ma50 and price > ma50),
    }


def _historical_analogs(
    histories: dict[str, list[dict[str, Any]]],
    semiconductor_symbols: list[str],
    benchmark_symbol: str = "SOXX",
) -> dict[str, Any]:
    benchmark = histories.get(benchmark_symbol, [])
    benchmark_by_date = {str(bar.get("t") or "")[:10]: _num(bar.get("c")) for bar in benchmark}
    benchmark_dates = [str(bar.get("t") or "")[:10] for bar in benchmark if bar.get("c") is not None]
    symbol_maps = {
        symbol: {str(bar.get("t") or "")[:10]: _num(bar.get("c")) for bar in histories.get(symbol, [])}
        for symbol in semiconductor_symbols
    }
    events: list[dict[str, float]] = []
    last_event_index = -10
    for index in range(50, max(50, len(benchmark_dates) - 5)):
        date = benchmark_dates[index]
        previous_date = benchmark_dates[index - 1]
        changes = []
        for values in symbol_maps.values():
            current, previous = values.get(date), values.get(previous_date)
            if current and previous:
                changes.append((current / previous - 1) * 100)
        if len(changes) < max(5, len(semiconductor_symbols) // 2):
            continue
        breadth = sum(value > 0 for value in changes) / len(changes)
        median_change = median(changes)
        prior_closes = [benchmark_by_date.get(day) for day in benchmark_dates[index - 49:index + 1]]
        prior_closes = [value for value in prior_closes if value]
        benchmark_close = benchmark_by_date.get(date)
        if len(prior_closes) < 50 or not benchmark_close:
            continue
        below_ma50 = benchmark_close < sum(prior_closes) / len(prior_closes)
        if breadth < 0.75 or median_change < 2.0 or not below_ma50:
            continue
        result: dict[str, float] = {}
        for horizon in (1, 3, 5):
            future = benchmark_by_date.get(benchmark_dates[index + horizon])
            if future:
                result[f"d{horizon}"] = (future / benchmark_close - 1) * 100
        if len(result) == 3:
            events.append(result)

    output: dict[str, Any] = {"sample_count": len(events), "sufficient": len(events) >= 5}
    for horizon in (1, 3, 5):
        values = [event[f"d{horizon}"] for event in events]
        output[f"day_{horizon}"] = {
            "win_rate": round(sum(value > 0 for value in values) / len(values) * 100, 1) if values else None,
            "median_return_pct": round(median(values), 2) if values else None,
        }
    output["note"] = (
        "仅基于本机约1年日线的同类事件统计，样本不足时不作为交易概率。"
        if len(events) < 5 else
        "历史相似日仅用于情景参考，不代表未来必然重复。"
    )
    return output


def build_semiconductor_pulse(
    signals: list[dict[str, Any]],
    histories: dict[str, list[dict[str, Any]]],
    snapshots: dict[str, dict[str, Any]],
    sector_name: str = "半导体",
    benchmark_symbol: str = "SOXX",
) -> dict[str, Any]:
    members = [signal for signal in signals if signal.get("sector") == sector_name and signal.get("status") != "NO_DATA"]
    if not members:
        return {"state": "NO_DATA", "state_label": "数据不足", "members": 0, "leaders": []}

    changes = [_num(signal.get("day_change_pct")) for signal in members]
    positive_count = sum(change > 0 for change in changes)
    strong_count = sum(change >= 3 for change in changes)
    overheat_count = sum(change > 5 or _num(signal.get("gap_pct")) > 3 for signal, change in zip(members, changes))
    above_ma_count = sum(bool((signal.get("checks") or {}).get("above_ma50")) for signal in members)
    deep_pullback_count = sum(_num(signal.get("drawdown20_pct")) <= -8 for signal in members)
    breadth = positive_count / len(members)
    median_change = median(changes)
    benchmark = _benchmark_snapshot(histories.get(benchmark_symbol, []), snapshots.get(benchmark_symbol, {}))

    if breadth >= 0.75 and median_change >= 2 and not benchmark["above_ma50"]:
        state, label, confidence = "REVERSAL_ALERT", "超跌反弹首日", "中"
        action = "板块转折已出现，但趋势尚未确认。今天不追高；收盘后筛选站回50日线且次日不跌破今日中位价的股票。"
    elif breadth >= 0.65 and median_change >= 0.8 and benchmark["above_ma50"] and above_ma_count / len(members) >= 0.5:
        state, label, confidence = "TREND_CONFIRMATION", "趋势恢复确认", "中高"
        action = "板块与多数个股趋势同步恢复，可从通过AI风险闸门且未过热的领涨股中分批试仓。"
    elif breadth <= 0.30 and median_change <= -2:
        state, label, confidence = "RISK_OFF", "板块风险释放", "中"
        action = "停止新增仓位，优先检查持仓风险与公司级坏消息，等待广度恢复。"
    else:
        state, label, confidence = "MIXED", "分化观察", "低"
        action = "板块尚无一致方向，只跟踪相对强度，不提前下注。"

    def priority(signal: dict[str, Any]) -> float:
        change = _num(signal.get("day_change_pct"))
        above = bool((signal.get("checks") or {}).get("above_ma50"))
        deep = _num(signal.get("drawdown20_pct")) <= -8
        overheat = change > 5 or _num(signal.get("gap_pct")) > 3
        distance = max(-10, min(5, _num(signal.get("distance_ma50_pct"))))
        return (30 if above else 0) + (15 if deep else 0) + max(0, 12 - abs(change - 3) * 2) - (20 if overheat else 0) + distance
    leaders = []
    for signal in sorted(members, key=priority, reverse=True)[:6]:
        change = _num(signal.get("day_change_pct"))
        checks = signal.get("checks") or {}
        overheat = change > 5 or _num(signal.get("gap_pct")) > 3
        if overheat:
            decision, decision_label = "WAIT_PULLBACK", "强势但不追"
            trigger = "等待回踩后不破今日中位价/缺口低点，再观察承接"
        elif checks.get("above_ma50") and _num(signal.get("drawdown20_pct")) <= -8 and change > 0:
            decision, decision_label = "ENTRY_WATCH", "进入确认名单"
            trigger = "若收盘站稳50日线且次日继续放量，可考虑小仓分批"
        else:
            decision, decision_label = "WATCH_CONFIRM", "等待趋势确认"
            trigger = f"先收复50日线 ${_num(signal.get('ma50')):.2f}" if signal.get("ma50") else "等待50日线数据"
        leaders.append({
            "symbol": signal["symbol"], "name": signal.get("name"),
            "change_pct": round(change, 2), "drawdown20_pct": signal.get("drawdown20_pct"),
            "distance_ma50_pct": signal.get("distance_ma50_pct"),
            "priority_score": round(priority(signal), 1),
            "decision": decision, "decision_label": decision_label, "trigger": trigger,
        })

    return {
        "state": state, "state_label": label, "confidence": confidence, "action": action,
        "members": len(members), "positive_count": positive_count,
        "breadth_pct": round(breadth * 100, 1), "median_change_pct": round(median_change, 2),
        "strong_count": strong_count, "overheat_count": overheat_count,
        "above_ma50_count": above_ma_count, "above_ma50_pct": round(above_ma_count / len(members) * 100, 1),
        "deep_pullback_count": deep_pullback_count,
        "benchmark_symbol": benchmark_symbol, "benchmark": benchmark,
        "leaders": leaders,
        "analogs": _historical_analogs(histories, [member["symbol"] for member in members], benchmark_symbol),
        "decision_ladder": [
            "发现：板块广度≥75%且中位涨幅≥2%，立即发板块异动提醒。",
            "确认：SOXX重回50日线，且至少一半个股同步站上50日线。",
            "执行：只选AI未发现基本面恶化、涨幅不过热的个股，小仓分批并预设失效位。",
        ],
    }
