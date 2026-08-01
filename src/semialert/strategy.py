from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from statistics import fmean
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def moving_average(values: list[float], window: int) -> float | None:
    return fmean(values[-window:]) if len(values) >= window else None


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    deltas = [b - a for a, b in zip(values[-window - 1 : -1], values[-window:])]
    gains = fmean(max(x, 0.0) for x in deltas)
    losses = fmean(max(-x, 0.0) for x in deltas)
    if losses == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + gains / losses))


def catalyst_days(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(value) - date.today()).days
    except ValueError:
        return None


def evaluate(
    symbol: str,
    name: str,
    bars: list[dict[str, Any]],
    snapshot: dict[str, Any],
    sector_above_ma50: bool,
    quality_approved: bool,
    catalyst_date: str | None,
    rules: dict[str, Any],
    is_holding: bool = False,
) -> dict[str, Any]:
    if len(bars) < max(int(rules["ma_days"]), int(rules["drawdown_lookback"])) + 3:
        return {"symbol": symbol, "name": name, "status": "NO_DATA", "score": 0, "reason": "历史日线不足"}

    closes = [_num(b.get("c")) for b in bars]
    lows = [_num(b.get("l")) for b in bars]
    volumes = [_num(b.get("v")) for b in bars]
    daily = snapshot.get("dailyBar") or {}
    prev_daily = snapshot.get("prevDailyBar") or {}
    latest_trade = snapshot.get("latestTrade") or {}
    session = snapshot.get("session") or {}
    price = _num(latest_trade.get("p"), _num(daily.get("c"), closes[-1]))
    today_open = _num(daily.get("o"), price)
    today_low = _num(daily.get("l"), price)
    today_volume = _num(daily.get("v"), 0)
    prev_close = _num(prev_daily.get("c"), closes[-1])

    # Do not duplicate today's partial bar if the historical endpoint already included it.
    effective = closes[:-1] if bars[-1].get("t", "")[:10] == datetime.now(timezone.utc).date().isoformat() else closes
    ma_window = int(rules["ma_days"])
    ma50 = moving_average(effective[-(ma_window - 1) :] + [price], ma_window)
    high20 = max(effective[-int(rules["drawdown_lookback"]) :])
    drawdown = (price / high20 - 1.0) * 100 if high20 else 0.0
    day_change = (price / prev_close - 1.0) * 100 if prev_close else 0.0
    gap = (today_open / prev_close - 1.0) * 100 if prev_close else 0.0
    active_session = session.get("active_session")
    if not active_session:
        try:
            quote_et = datetime.fromisoformat(str(latest_trade.get("t") or "").replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
            quote_minutes = quote_et.hour * 60 + quote_et.minute
            active_session = "PREMARKET" if 240 <= quote_minutes < 570 else "REGULAR" if 570 <= quote_minutes < 960 else "AFTERHOURS" if 960 <= quote_minutes < 1200 else "OVERNIGHT"
        except ValueError:
            active_session = "UNKNOWN"
    active_session_change = session.get("active_change_pct")
    if active_session_change is None:
        active_session_change = day_change
    avg_volume = fmean(volumes[-20:]) if volumes[-20:] else 0.0
    volume_ratio = today_volume / avg_volume if avg_volume else 0.0
    current_rsi = rsi(effective + [price])

    stabilize_n = int(rules["stabilization_days"])
    recent_lows = lows[-stabilize_n:]
    higher_lows = all(b >= a for a, b in zip(recent_lows, recent_lows[1:]))
    stabilization = higher_lows and price >= closes[-1] and today_low >= recent_lows[-1] * 0.985
    above_ma = ma50 is not None and price > ma50
    drawdown_ok = drawdown <= float(rules["black_swan_drawdown_pct"])
    not_chasing = day_change <= float(rules["max_entry_day_gain_pct"]) and gap <= float(rules["max_gap_pct"])
    volume_ok = volume_ratio >= float(rules["min_volume_ratio"])
    c_days = catalyst_days(catalyst_date)
    catalyst_ok = c_days is not None and 0 <= c_days <= 42

    checks = {
        "industry": sector_above_ma50,
        "quality": quality_approved,
        "above_ma50": above_ma,
        "stabilized": stabilization,
        "drawdown": drawdown_ok,
        "not_chasing": not_chasing,
        "volume": volume_ok,
        "catalyst": catalyst_ok,
    }
    weights = {"industry": 15, "quality": 15, "above_ma50": 20, "stabilized": 15, "drawdown": 15, "not_chasing": 10, "volume": 5, "catalyst": 5}
    score = sum(weights[key] for key, passed in checks.items() if passed)
    hard_ready = all(checks[k] for k in ("industry", "quality", "above_ma50", "stabilized", "drawdown", "not_chasing"))
    status = "READY" if hard_ready and score >= int(rules["ready_score"]) else "WATCH" if above_ma and quality_approved else "REJECT"

    exit_signal = None
    two_day = ((price / closes[-2]) - 1.0) * 100 if len(closes) >= 2 and closes[-2] else 0.0
    if is_holding and day_change >= 5.0:
        exit_signal = "SELL_1_3"
    if is_holding and two_day >= 8.0:
        exit_signal = "SELL_1_2"

    failed = [k for k, passed in checks.items() if not passed]
    return {
        "symbol": symbol,
        "name": name,
        "status": status,
        "score": score,
        "price": round(price, 4),
        "ma50": round(ma50, 4) if ma50 else None,
        "distance_ma50_pct": round((price / ma50 - 1) * 100, 2) if ma50 else None,
        "drawdown20_pct": round(drawdown, 2),
        "day_change_pct": round(day_change, 2),
        "gap_pct": round(gap, 2),
        "volume_ratio": round(volume_ratio, 2),
        "rsi14": round(current_rsi, 1) if current_rsi is not None else None,
        "catalyst_date": catalyst_date,
        "catalyst_days": c_days,
        "checks": checks,
        "failed_checks": failed,
        "exit_signal": exit_signal,
"quote_time": (latest_trade.get("t") or daily.get("t") or ""),
        "market_state": session.get("market_state"),
        "active_session": active_session,
        "active_session_change_pct": round(active_session_change, 2),
        "regular_price": session.get("regular_price"),
        "regular_change_pct": session.get("regular_change_pct"),
        "premarket_price": session.get("premarket_price"),
        "premarket_change_pct": session.get("premarket_change_pct"),
        "afterhours_price": session.get("afterhours_price"),
        "afterhours_change_pct": session.get("afterhours_change_pct"),
        "reason": "全部硬条件通过" if status == "READY" else "未通过: " + ", ".join(failed),
    }


def benchmark_above_ma50(bars: list[dict[str, Any]], snapshot: dict[str, Any], window: int = 50) -> bool:
    if len(bars) < window:
        return False
    price = _num((snapshot.get("latestTrade") or {}).get("p"), _num(bars[-1].get("c")))
    closes = [_num(bar.get("c")) for bar in bars]
    ma = moving_average(closes[-(window - 1) :] + [price], window)
    return bool(ma and price > ma)
