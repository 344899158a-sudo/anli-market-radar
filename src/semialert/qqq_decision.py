from __future__ import annotations

from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _frame(analysis: dict[str, Any], label: str) -> dict[str, Any]:
    frame = (analysis.get("timeframes") or {}).get(label) or {}
    return frame if frame.get("sufficient") else {}


def _primary_frame(analysis: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for label in ("1D", "4h", "1h", "15m", "1W"):
        frame = _frame(analysis, label)
        if frame:
            return label, frame
    return "—", {}


def build_qqq_recommendation(
    analysis: dict[str, Any],
    market_overview: dict[str, Any],
) -> dict[str, Any]:
    """Explainable QQQ decision support. Scores are rule completion, not probabilities."""
    label, primary = _primary_frame(analysis)
    frames = {name: _frame(analysis, name) for name in ("15m", "1h", "4h", "1D", "1W")}
    indicators = primary.get("indicators") or {}
    price = _number(analysis.get("price"))
    atr = max(_number(indicators.get("atr14"), price * 0.015), price * 0.002)
    rsi = _number(indicators.get("rsi14"), 50)
    ma20 = _number(indicators.get("ma20"), price)
    market_score = int(_number(market_overview.get("score")))
    regime = str(market_overview.get("regime") or "UNKNOWN")
    bias = str(analysis.get("bias") or "NEUTRAL")
    structure_alignment = min(100.0, abs(_number(analysis.get("consensus_score"))))
    distance_ma20_atr = (price - ma20) / atr if atr else 0
    overextended = rsi >= 72 or distance_ma20_atr >= 1.8

    zones = primary.get("zones") or []
    supports = sorted((_number(row.get("level")) for row in zones if 0 < _number(row.get("level")) < price), reverse=True)
    resistances = sorted(_number(row.get("level")) for row in zones if _number(row.get("level")) > price)
    support = supports[0] if supports else _number((analysis.get("plans") or {}).get("long", {}).get("stop")) + atr * 0.15
    resistance = resistances[0] if resistances else _number((analysis.get("plans") or {}).get("long", {}).get("trigger"))
    near_support = price > 0 and abs(price - support) <= atr * 0.55

    patterns = analysis.get("patterns") or []
    major_bullish = [row for row in patterns if row.get("timeframe") in {"1D", "4h"} and row.get("direction") == "BULLISH" and row.get("status") == "已确认"]
    major_bearish = [row for row in patterns if row.get("timeframe") in {"1D", "4h"} and row.get("direction") == "BEARISH" and row.get("status") == "已确认"]

    daily_trend = frames["1D"].get("trend")
    four_hour_trend = frames["4h"].get("trend")
    intraday_trends = [frames[name].get("trend") for name in ("15m", "1h") if frames[name]]
    intraday_up = "UP" in intraday_trends
    intraday_down = "DOWN" in intraday_trends
    long_alignment = daily_trend == "UP" and four_hour_trend == "UP" and intraday_up
    short_alignment = daily_trend == "DOWN" and four_hour_trend == "DOWN" and intraday_down

    long_context = bias == "LONG" and market_score >= 58 and regime != "DOWNTREND"
    short_context = bias == "SHORT" and market_score <= 52
    pullback_setup = long_context and long_alignment and near_support and 42 <= rsi <= 68 and not overextended
    breakout_setup = long_context and long_alignment and bool(major_bullish) and not overextended
    bearish_setup = short_context and short_alignment and bool(major_bearish)

    plans = analysis.get("plans") or {"long": {}, "short": {}}
    if pullback_setup or breakout_setup:
        stance, state = "看多", "LONG_SETUP"
        headline = "多周期已对齐，进入做多确认区"
        entry = price
        stop = min(support - atr * 0.18, price - atr * 0.85)
        risk = max(price - stop, atr * 0.55)
        target = price + risk * 2
        next_condition = "15分钟或1小时收盘继续保持转强，且价格不跌破结构支撑，再人工核对。"
    elif bearish_setup:
        stance, state = "看空", "SHORT_SETUP"
        headline = "多周期下行对齐，等待反抽失败"
        entry = price
        stop = max(resistance + atr * 0.18, price + atr * 0.85)
        risk = max(stop - price, atr * 0.55)
        target = max(0.01, price - risk * 2)
        next_condition = f"反弹不收复 {resistance:.2f}，且15分钟/1小时再次转弱，才进入做空或对冲核对。"
    elif long_context:
        stance, state = "偏多", "WAIT_PULLBACK" if overextended else "WAIT_CONFIRM"
        headline = "趋势偏多，但条件尚未完整" if not overextended else "趋势偏多，但位置过热不追价"
        entry = _number(plans.get("long", {}).get("trigger"), price)
        stop = _number(plans.get("long", {}).get("stop"), price - atr)
        risk = max(entry - stop, 0.01)
        target = entry + risk * 2
        next_condition = "等待日线、4小时与15分钟/1小时方向一致，并在支撑企稳或完成有效突破。"
    elif short_context:
        stance, state = "偏空", "WAIT_BREAKDOWN"
        headline = "结构偏弱，但做空确认不足"
        entry = _number(plans.get("short", {}).get("trigger"), price)
        stop = _number(plans.get("short", {}).get("stop"), price + atr)
        risk = max(stop - entry, 0.01)
        target = max(0.01, entry - risk * 2)
        next_condition = f"日线与4小时同步转弱，并有效跌破 {support:.2f} 后反抽失败。"
    else:
        stance, state = "观望", "NO_EDGE"
        headline = "多空没有形成高质量共振"
        entry, stop = price, max(0.01, price - atr)
        risk = max(price - stop, 0.01)
        target = price + risk * 1.5
        next_condition = "等待日线与4小时方向一致，再用15分钟/1小时确认触发。"

    alignment_points = 25 if long_alignment or short_alignment else 12 if daily_trend == four_hour_trend and daily_trend in {"UP", "DOWN"} else 0
    location_points = 20 if near_support and not overextended else 8 if not overextended else 0
    pattern_points = 15 if major_bullish or major_bearish else 5
    context_points = max(0, min(25, market_score * 0.25))
    structure_points = max(0, min(15, structure_alignment * 0.15))
    completion_score = alignment_points + location_points + pattern_points + context_points + structure_points
    if state == "NO_EDGE":
        completion_score = min(completion_score, 49)
    grade = "条件充分" if completion_score >= 75 else "接近触发" if completion_score >= 60 else "继续等待"

    data_ready = bool((analysis.get("data") or {}).get("execution_ready"))
    risk_pct = abs(entry - stop) / entry * 100 if entry else 0
    side = "SHORT" if stance in {"看空", "偏空"} else "LONG"
    logic = [
        f"方向层：日线 {daily_trend or '不足'}、4小时 {four_hour_trend or '不足'}；短周期为 {', '.join(intraday_trends) if intraday_trends else '数据不足'}。",
        f"环境层：{market_overview.get('regime_label', '未知')}，市场环境分 {market_score}/100。",
        f"动量与位置：RSI14 {rsi:.1f}；价格距MA20 {distance_ma20_atr:+.2f} ATR。",
        f"结构层：最近支撑 {support:.2f}，阻力 {resistance:.2f}；{'位于支撑准备区' if near_support else '不在支撑准备区'}。",
        "触发层：必须由日线/4小时定方向，再由15分钟或1小时确认；单一周期形态不再触发信号。",
    ]
    vetoes = []
    if overextended:
        vetoes.append("不追涨：RSI偏热或价格明显远离MA20")
    if regime == "DOWNTREND":
        vetoes.append("市场环境否决：整体处于下跌趋势")
    if not long_alignment and not short_alignment:
        vetoes.append("周期未对齐：日线、4小时、短周期没有同向确认")
    if not data_ready:
        vetoes.append("数据闸门：执行前需用券商盘中报价复核")

    return {
        "state": state, "stance": stance, "side": side, "headline": headline,
        "grade": grade, "score": round(max(0, min(100, completion_score)), 1),
        "score_label": "条件完成度（规则分，非胜率）",
        "technical_setup_ready": state in {"LONG_SETUP", "SHORT_SETUP"},
        "execution_ready": bool(data_ready and state in {"LONG_SETUP", "SHORT_SETUP"}),
        "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
        "risk_pct": round(risk_pct, 2), "risk_reward": 2.0,
        "support": round(support, 2), "resistance": round(resistance, 2),
        "overextended": overextended, "next_condition": next_condition,
        "logic": logic, "vetoes": vetoes,
        "method": "日线/4小时定方向 → 15分钟/1小时确认 → 位置与风险过滤",
        "methodology": {
            "rsi": "RSI(14)：Wilder RMA 平滑",
            "atr": "ATR(14)：True Range 的 Wilder RMA",
            "macd": "MACD：EMA(12)-EMA(26)，Signal=EMA(9)",
            "session": "盘中技术K线仅使用美股常规时段；4小时K线不跨交易日",
            "zones": "支撑/阻力为近180根K线摆动点聚类，至少2次触及",
            "honesty": "条件完成度是规则一致度，不是胜率或收益预测",
        },
    }