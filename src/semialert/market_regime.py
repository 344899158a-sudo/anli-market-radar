from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MARKET_SYMBOLS = ("SPY", "QQQ", "^IXIC", "RSP", "IWM", "DIA", "^VIX", "^TNX", "DX-Y.NYB")


def _closes(bars: list[dict[str, Any]]) -> list[float]:
    return [float(row["c"]) for row in bars if row.get("c") is not None]


def _ma(values: list[float], days: int) -> float | None:
    return sum(values[-days:]) / days if len(values) >= days else None


def _pct(value: float | None, base: float | None) -> float | None:
    if value is None or not base:
        return None
    return round((value / base - 1) * 100, 2)


def _rsi(values: list[float], days: int = 14) -> float | None:
    if len(values) <= days:
        return None
    changes = [values[index] - values[index - 1] for index in range(len(values) - days, len(values))]
    gains = sum(max(change, 0) for change in changes) / days
    losses = sum(max(-change, 0) for change in changes) / days
    if losses == 0:
        return 100.0
    relative_strength = gains / losses
    return round(100 - 100 / (1 + relative_strength), 1)


def _streak(values: list[float]) -> int:
    if len(values) < 2:
        return 0
    direction = 1 if values[-1] > values[-2] else -1 if values[-1] < values[-2] else 0
    if direction == 0:
        return 0
    count = 0
    for index in range(len(values) - 1, 0, -1):
        current_direction = 1 if values[index] > values[index - 1] else -1 if values[index] < values[index - 1] else 0
        if current_direction != direction:
            break
        count += 1
    return count * direction


def _snapshot_price(snapshot: dict[str, Any], bars: list[dict[str, Any]]) -> float | None:
    trade = snapshot.get("latestTrade") or {}
    if trade.get("p") is not None:
        return float(trade["p"])
    closes = _closes(bars)
    return closes[-1] if closes else None


def _asset(symbol: str, history: dict[str, list[dict[str, Any]]], snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bars = history.get(symbol, [])
    values = _closes(bars)
    snapshot = snapshots.get(symbol, {})
    price = _snapshot_price(snapshot, bars)
    ma20, ma50, ma200 = _ma(values, 20), _ma(values, 50), _ma(values, 200)
    high_52w = max(values[-252:]) if values else None
    previous = (snapshot.get("prevDailyBar") or {}).get("c")
    session = snapshot.get("session") or {}
    day_change = session.get("active_change_pct")
    if day_change is None:
        day_change = _pct(price, float(previous) if previous else None)
    ma20_five_days_ago = _ma(values[:-5], 20) if len(values) >= 25 else None
    return {
        "symbol": symbol,
        "price": round(price, 3) if price is not None else None,
        "day_change_pct": day_change,
        "ma20": round(ma20, 3) if ma20 is not None else None,
        "ma50": round(ma50, 3) if ma50 is not None else None,
        "ma200": round(ma200, 3) if ma200 is not None else None,
        "distance_ma20_pct": _pct(price, ma20),
        "distance_ma50_pct": _pct(price, ma50),
        "distance_ma200_pct": _pct(price, ma200),
        "distance_high_52w_pct": _pct(price, high_52w),
        "return20_pct": _pct(price, values[-21] if len(values) >= 21 else None),
        "rsi14": _rsi(values),
        "daily_streak": _streak(values),
        "above_ma20": bool(price is not None and ma20 is not None and price >= ma20),
        "above_ma50": bool(price is not None and ma50 is not None and price >= ma50),
        "above_ma200": bool(price is not None and ma200 is not None and price >= ma200),
        "ma20_rising": bool(ma20 is not None and ma20_five_days_ago is not None and ma20 > ma20_five_days_ago),
        "quote_time": (snapshot.get("latestTrade") or {}).get("t"),
    }


def _breadth(history: dict[str, list[dict[str, Any]]], company_symbols: list[str]) -> dict[str, Any]:
    counts = {20: 0, 50: 0, 200: 0}
    eligible = {20: 0, 50: 0, 200: 0}
    for symbol in company_symbols:
        values = _closes(history.get(symbol, []))
        if not values:
            continue
        price = values[-1]
        for days in counts:
            average = _ma(values, days)
            if average is not None:
                eligible[days] += 1
                counts[days] += int(price >= average)
    def ratio(days: int) -> float | None:
        return round(counts[days] / eligible[days] * 100, 1) if eligible[days] else None
    return {
        "above_ma20_pct": ratio(20), "above_ma50_pct": ratio(50), "above_ma200_pct": ratio(200),
        "sample_size": eligible[50], "universe_size": len(company_symbols),
    }


def _daily_chart(bars: list[dict[str, Any]], limit: int = 180) -> list[dict[str, Any]]:
    closes: list[float] = []
    rows: list[dict[str, Any]] = []
    for bar in bars:
        if bar.get("c") is None or not bar.get("ohlcv_complete"):
            continue
        close = float(bar["c"])
        closes.append(close)
        ma20, ma50, ma200 = _ma(closes, 20), _ma(closes, 50), _ma(closes, 200)
        rows.append({
            "date": str(bar.get("t") or "")[:10],
            "open": round(float(bar.get("o", close)), 3),
            "high": round(float(bar.get("h", close)), 3),
            "low": round(float(bar.get("l", close)), 3),
            "close": round(close, 3),
            "volume": int(bar.get("v") or 0),
            "ma20": round(ma20, 3) if ma20 is not None else None,
            "ma50": round(ma50, 3) if ma50 is not None else None,
            "ma200": round(ma200, 3) if ma200 is not None else None,
        })
    return rows[-limit:]

def build_market_overview(
    history: dict[str, list[dict[str, Any]]],
    snapshots: dict[str, dict[str, Any]],
    company_symbols: list[str],
    provider: str,
) -> dict[str, Any]:
    assets = {symbol: _asset(symbol, history, snapshots) for symbol in MARKET_SYMBOLS}
    spy, qqq, ixic, rsp, iwm, vix = (assets[s] for s in ("SPY", "QQQ", "^IXIC", "RSP", "IWM", "^VIX"))
    breadth = _breadth(history, company_symbols)

    trend_score = sum((
        8 if spy["above_ma20"] else 0, 7 if spy["above_ma50"] else 0, 5 if spy["above_ma200"] else 0,
        8 if qqq["above_ma20"] else 0, 7 if qqq["above_ma50"] else 0, 5 if qqq["above_ma200"] else 0,
        5 if spy["ma20_rising"] else 0, 5 if qqq["ma20_rising"] else 0,
    ))
    breadth_score = 0
    above50 = breadth.get("above_ma50_pct")
    if above50 is not None:
        breadth_score += 12 if above50 >= 65 else 8 if above50 >= 50 else 4 if above50 >= 35 else 0
    breadth_score += 7 if rsp["above_ma50"] else 0
    breadth_score += 6 if iwm["above_ma50"] else 0

    vix_value = vix.get("price")
    # Missing VIX is a data-quality gap, not evidence of maximum volatility.
    # Keep the score neutral and expose the lower confidence to the UI.
    volatility_available = vix_value is not None
    volatility_score = 10 if not volatility_available else 20 if vix_value < 18 else 15 if vix_value < 22 else 8 if vix_value < 28 else 2
    tnx = assets["^TNX"]
    dollar = assets["DX-Y.NYB"]
    macro_inputs_available = sum((tnx.get("price") is not None, dollar.get("price") is not None))
    macro_score = 15 if macro_inputs_available == 2 else 11 if macro_inputs_available == 1 else 8
    if (tnx.get("day_change_pct") or 0) > 1.5:
        macro_score -= 6
    if (dollar.get("day_change_pct") or 0) > 0.6:
        macro_score -= 5
    macro_score = max(0, macro_score)
    score = max(0, min(100, trend_score + breadth_score + volatility_score + macro_score))

    indices_up = spy["above_ma50"] and qqq["above_ma50"] and ixic["above_ma50"]
    indices_down = not spy["above_ma50"] and not qqq["above_ma50"] and not ixic["above_ma50"]
    if indices_up and trend_score >= 35 and volatility_available and vix_value < 22 and (above50 is None or above50 >= 50):
        regime, label = "STRONG_LOW_VOL", "强趋势·低波动"
        action = "允许寻找强势股回调机会；按计划分批，仍然禁止追涨。"
        exposure = "正常风险预算"
    elif indices_up and trend_score >= 30:
        regime, label = "STRONG_HIGH_VOL", "强趋势·高波动"
        action = "方向仍偏多，但降低单笔仓位；等待回踩确认，避免追逐盘中加速。"
        exposure = "正常仓位的1/2–2/3"
    elif indices_down and (not spy["above_ma200"] or not qqq["above_ma200"]):
        regime, label = "DOWNTREND", "下跌趋势"
        action = "优先保留现金；不因跌幅大而抄底，只有基本面未恶化且出现明确止跌才观察。"
        exposure = "防守，0–1/4风险预算"
    else:
        regime, label = "ROTATION", "震荡轮动"
        action = "减少突破交易，优先选择强于SPY/QQQ的板块，并等待支撑位或收复均线。"
        exposure = "正常仓位的1/3–1/2"

    high_distance = qqq.get("distance_high_52w_pct")
    qqq_rsi = qqq.get("rsi14")
    qqq_ma50_distance = qqq.get("distance_ma50_pct")
    if (
        high_distance is not None and high_distance >= -3
        and ((qqq_rsi or 0) >= 68 or (qqq_ma50_distance or 0) >= 8)
    ):
        position_code, position_label = "HIGH_RISK", "高位危险区"
    elif high_distance is not None and high_distance >= -5:
        position_code, position_label = "HIGH", "高位震荡区"
    elif qqq["above_ma50"] and qqq["above_ma200"]:
        position_code, position_label = "MID", "趋势中段"
    elif qqq["above_ma200"]:
        position_code, position_label = "RECOVERY", "长期趋势上方的修复区"
    else:
        position_code, position_label = "LOW", "低位/长期趋势下方"

    ixic_relative = None
    if ixic.get("return20_pct") is not None and qqq.get("return20_pct") is not None:
        ixic_relative = round(ixic["return20_pct"] - qqq["return20_pct"], 2)
    nasdaq_trend = "强势" if ixic["above_ma20"] and ixic["above_ma50"] and ixic["above_ma200"] else "修复/震荡" if ixic["above_ma200"] else "弱势"
    nasdaq_position = "接近52周高位" if (ixic.get("distance_high_52w_pct") or -100) >= -3 else "50日线上方" if ixic["above_ma50"] else "50日线下方"
    checks = [
        {"step": 1, "name": "指数趋势", "status": "通过" if trend_score >= 30 else "谨慎" if trend_score >= 20 else "不通过", "detail": f"SPY/QQQ/纳指综合 50日线：{'全部在上' if spy['above_ma50'] and qqq['above_ma50'] and ixic['above_ma50'] else '全部在下' if indices_down else '分化'}；趋势分 {trend_score}/50"},
        {"step": 2, "name": "市场宽度", "status": "通过" if (above50 or 0) >= 50 else "谨慎" if (above50 or 0) >= 35 else "不通过", "detail": f"观察池站上50日线 {above50 if above50 is not None else '—'}%；RSP/IWM 50日线：{'上' if rsp['above_ma50'] else '下'}/{'上' if iwm['above_ma50'] else '下'}"},
        {
            "step": 3,
            "name": "波动率",
            "status": "数据待补" if not volatility_available else "通过" if volatility_score >= 15 else "谨慎" if volatility_score >= 8 else "不通过",
            "detail": (
                f"VIX {vix_value}；波动率分 {volatility_score}/20"
                if volatility_available
                else "VIX 当前源未返回；采用中性 10/20，不把缺失值当作极端风险"
            ),
        },
        {
            "step": 4,
            "name": "利率与美元",
            "status": "数据待补" if macro_inputs_available < 2 else "通过" if macro_score >= 12 else "谨慎" if macro_score >= 7 else "不通过",
            "detail": (
                f"10年期收益率日变动 {tnx.get('day_change_pct')}%；美元指数日变动 {dollar.get('day_change_pct')}%"
                if macro_inputs_available == 2
                else f"利率/美元仅取得 {macro_inputs_available}/2 项；采用中性基准 {macro_score}/15"
            ),
        },
        {"step": 5, "name": "操作结论", "status": "允许" if regime == "STRONG_LOW_VOL" else "降仓" if regime in {"STRONG_HIGH_VOL", "ROTATION"} else "防守", "detail": action},
    ]
    quote_times = [item.get("quote_time") for item in assets.values() if item.get("quote_time")]
    return {
        "as_of": max(quote_times) if quote_times else None,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "score": score,
        "regime": regime,
        "regime_label": label,
        "position_label": position_label,
        "position_code": position_code,
        "exposure_guidance": exposure,
        "action": action,
        "scores": {"trend": trend_score, "breadth": breadth_score, "volatility": volatility_score, "macro": macro_score},
        "data_quality": {
            "confidence": "HIGH" if volatility_available and macro_inputs_available == 2 else "MEDIUM" if macro_inputs_available >= 1 else "LOW",
            "missing_inputs": (
                ([] if volatility_available else ["VIX"])
                + ([] if tnx.get("price") is not None else ["10年期美债收益率"])
                + ([] if dollar.get("price") is not None else ["美元指数"])
            ),
            "score_policy": "缺失输入采用中性分；缺失VIX时不确认低波动环境",
        },
        "breadth": breadth,
        "nasdaq_analysis": {"trend": nasdaq_trend, "position": nasdaq_position, "return20_pct": ixic.get("return20_pct"), "vs_qqq_20d_pct": ixic_relative, "summary": f"纳斯达克综合指数处于{nasdaq_trend}、{nasdaq_position}；近20日相对QQQ {ixic_relative if ixic_relative is not None else '—'}%"},
        "qqq_chart": _daily_chart(history.get("QQQ", [])),
        "nasdaq_chart": _daily_chart(history.get("^IXIC", [])),
        "assets": assets,
        "checks": checks,
        "limitations": (
            "公开延时行情；市场宽度使用当前重点观察股作为代理，不等同于NYSE全市场涨跌家数。"
            + (" 当前备用源缺少部分宏观输入，缺失项采用中性分且不会触发低波动确认。" if (not volatility_available or macro_inputs_available < 2) else "")
        ),
    }
