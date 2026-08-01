from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any


TIMEFRAME_WEIGHTS = {"15m": 0.10, "1h": 0.15, "4h": 0.25, "1D": 0.30, "1W": 0.20}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _clean_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for bar in bars:
        close = _num(bar.get("c"))
        if close <= 0:
            continue
        open_ = _num(bar.get("o"), close)
        high = max(_num(bar.get("h"), close), open_, close)
        low = min(_num(bar.get("l"), close), open_, close)
        cleaned.append({
            "t": str(bar.get("t") or ""),
            "o": open_, "h": high, "l": low, "c": close,
            "v": max(0, _num(bar.get("v"))),
            "ohlcv_complete": bool(bar.get("ohlcv_complete")),
        })
    return cleaned


def aggregate_bars(bars: list[dict[str, Any]], size: int = 4, weekly: bool = False) -> list[dict[str, Any]]:
    clean = _clean_bars(bars)
    groups: list[list[dict[str, Any]]] = []
    if weekly:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        order: list[str] = []
        for bar in clean:
            try:
                dt = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                key = f"{dt.isocalendar().year}-{dt.isocalendar().week:02d}"
            except ValueError:
                key = bar["t"][:7]
            if key not in buckets:
                order.append(key)
            buckets[key].append(bar)
        groups = [buckets[key] for key in order]
    else:
        groups = [clean[index:index + size] for index in range(0, len(clean), size)]
    output = []
    for group in groups:
        if not group:
            continue
        output.append({
            "t": group[-1]["t"], "o": group[0]["o"],
            "h": max(bar["h"] for bar in group), "l": min(bar["l"] for bar in group),
            "c": group[-1]["c"], "v": sum(bar["v"] for bar in group),
            "ohlcv_complete": all(bar.get("ohlcv_complete") for bar in group),
        })
    return output


def aggregate_intraday_bars(bars: list[dict[str, Any]], size: int = 4) -> list[dict[str, Any]]:
    """Aggregate intraday bars without combining two US trading dates."""
    clean = _clean_bars(bars)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for bar in clean:
        key = bar["t"][:10]
        if key not in buckets:
            order.append(key)
        buckets[key].append(bar)
    output: list[dict[str, Any]] = []
    for key in order:
        day = buckets[key]
        for index in range(0, len(day), size):
            group = day[index:index + size]
            if group:
                output.append({
                    "t": group[-1]["t"], "o": group[0]["o"],
                    "h": max(bar["h"] for bar in group), "l": min(bar["l"] for bar in group),
                    "c": group[-1]["c"], "v": sum(bar["v"] for bar in group),
                    "ohlcv_complete": all(bar.get("ohlcv_complete") for bar in group),
                })
    return output

def _sma(values: list[float], window: int) -> float | None:
    return sum(values[-window:]) / window if len(values) >= window else None


def _ema_series(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result
    previous = sum(values[:window]) / window
    result[window - 1] = previous
    multiplier = 2 / (window + 1)
    for index in range(window, len(values)):
        previous += (values[index] - previous) * multiplier
        result[index] = previous
    return result


def _wilder_rma(values: list[float], window: int) -> list[float | None]:
    """Wilder's moving average: SMA seed followed by alpha=1/window smoothing."""
    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result
    average = sum(values[:window]) / window
    result[window - 1] = average
    for index in range(window, len(values)):
        average = (average * (window - 1) + values[index]) / window
        result[index] = average
    return result


def _rsi_series(values: list[float], window: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return result
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gains = _wilder_rma(gains, window)
    average_losses = _wilder_rma(losses, window)
    for change_index in range(window - 1, len(changes)):
        gain = average_gains[change_index]
        loss = average_losses[change_index]
        if gain is None or loss is None:
            continue
        result[change_index + 1] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return result


def _rsi(values: list[float], window: int = 14) -> float | None:
    return _rsi_series(values, window)[-1] if values else None


def _atr(bars: list[dict[str, Any]], window: int = 14) -> float | None:
    clean = _clean_bars(bars)
    if len(clean) <= window:
        return None
    true_ranges = []
    for index in range(1, len(clean)):
        true_ranges.append(max(
            clean[index]["h"] - clean[index]["l"],
            abs(clean[index]["h"] - clean[index - 1]["c"]),
            abs(clean[index]["l"] - clean[index - 1]["c"]),
        ))
    return _wilder_rma(true_ranges, window)[-1]


def _regression(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return 0.0, values[-1] if values else 0.0
    n = len(values)
    sx = n * (n - 1) / 2
    sxx = (n - 1) * n * (2 * n - 1) / 6
    sy = sum(values)
    sxy = sum(index * value for index, value in enumerate(values))
    denominator = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denominator if denominator else 0.0
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _swings(bars: list[dict[str, Any]], window: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for index in range(window, len(bars) - window):
        high_sample = [bar["h"] for bar in bars[index - window:index + window + 1]]
        low_sample = [bar["l"] for bar in bars[index - window:index + window + 1]]
        if bars[index]["h"] == max(high_sample):
            highs.append((index, bars[index]["h"]))
        if bars[index]["l"] == min(low_sample):
            lows.append((index, bars[index]["l"]))
    return highs, lows


def _pattern(
    name: str, direction: str, confidence: float, status: str,
    trigger: float, invalidation: float, target: float, explanation: str,
) -> dict[str, Any]:
    return {
        "name": name, "direction": direction, "confidence": round(max(0, min(99, confidence)), 1),
        "status": status, "trigger": round(trigger, 3), "invalidation": round(invalidation, 3),
        "target": round(max(0.01, target), 3), "explanation": explanation,
    }


def _detect_patterns(bars: list[dict[str, Any]], atr: float) -> list[dict[str, Any]]:
    if len(bars) < 25:
        return []
    recent = bars[-60:]
    close = recent[-1]["c"]
    highs, lows = _swings(recent)
    patterns: list[dict[str, Any]] = []
    tolerance = max(close * 0.025, atr * 0.8)

    if len(highs) >= 2:
        (i1, h1), (i2, h2) = highs[-2:]
        valley = min(bar["l"] for bar in recent[i1:i2 + 1])
        if abs(h1 - h2) <= tolerance and i2 - i1 >= 5:
            status = "已确认" if close < valley else "形成中"
            patterns.append(_pattern("双顶", "BEARISH", 78 if status == "已确认" else 65, status,
                                     valley, max(h1, h2) + atr * .3, valley - (max(h1, h2) - valley),
                                     "两次冲击相近高点；跌破颈线才算确认。"))
    if len(lows) >= 2:
        (i1, l1), (i2, l2) = lows[-2:]
        peak = max(bar["h"] for bar in recent[i1:i2 + 1])
        if abs(l1 - l2) <= tolerance and i2 - i1 >= 5:
            status = "已确认" if close > peak else "形成中"
            patterns.append(_pattern("双底", "BULLISH", 78 if status == "已确认" else 65, status,
                                     peak, min(l1, l2) - atr * .3, peak + (peak - min(l1, l2)),
                                     "两次回踩相近低点；突破颈线才算确认。"))

    if len(highs) >= 3:
        trio = highs[-3:]
        if trio[1][1] > trio[0][1] + tolerance and trio[1][1] > trio[2][1] + tolerance and abs(trio[0][1] - trio[2][1]) <= tolerance * 1.5:
            neckline = min(bar["l"] for bar in recent[trio[0][0]:trio[2][0] + 1])
            patterns.append(_pattern("头肩顶", "BEARISH", 72, "已确认" if close < neckline else "形成中",
                                     neckline, trio[1][1] + atr * .3, neckline - (trio[1][1] - neckline),
                                     "中间峰值最高、两侧肩部相近。"))
    if len(lows) >= 3:
        trio = lows[-3:]
        if trio[1][1] < trio[0][1] - tolerance and trio[1][1] < trio[2][1] - tolerance and abs(trio[0][1] - trio[2][1]) <= tolerance * 1.5:
            neckline = max(bar["h"] for bar in recent[trio[0][0]:trio[2][0] + 1])
            patterns.append(_pattern("倒头肩", "BULLISH", 72, "已确认" if close > neckline else "形成中",
                                     neckline, trio[1][1] - atr * .3, neckline + (neckline - trio[1][1]),
                                     "中间低点最低、两侧肩部相近。"))

    structure = recent[-25:]
    high_slope, high_intercept = _regression([bar["h"] for bar in structure])
    low_slope, low_intercept = _regression([bar["l"] for bar in structure])
    normalized_high = high_slope / close * 100
    normalized_low = low_slope / close * 100
    projected_high = high_intercept + high_slope * (len(structure) - 1)
    projected_low = low_intercept + low_slope * (len(structure) - 1)
    width_start = high_intercept - low_intercept
    width_end = projected_high - projected_low

    if abs(normalized_high) < .08 and normalized_low > .08:
        patterns.append(_pattern("上升三角形", "BULLISH", 68, "已确认" if close > projected_high else "形成中",
                                 projected_high, projected_low - atr * .3, projected_high + width_start,
                                 "阻力近似水平、低点逐步抬高。"))
    elif normalized_high < -.08 and abs(normalized_low) < .08:
        patterns.append(_pattern("下降三角形", "BEARISH", 68, "已确认" if close < projected_low else "形成中",
                                 projected_low, projected_high + atr * .3, projected_low - width_start,
                                 "支撑近似水平、高点逐步降低。"))
    elif normalized_high < -.05 and normalized_low > .05:
        patterns.append(_pattern("对称三角形", "NEUTRAL", 60, "形成中",
                                 projected_high, projected_low, close + width_start,
                                 "高点下降、低点上升，等待方向选择。"))
    elif normalized_high > .05 and normalized_low > .05:
        if width_end < width_start * .75:
            patterns.append(_pattern("上升楔形", "BEARISH", 64, "形成中",
                                     projected_low, projected_high + atr * .3, projected_low - width_start,
                                     "高低点同时抬升但通道收窄，动能可能衰减。"))
        elif abs(normalized_high - normalized_low) < .08:
            patterns.append(_pattern("上升通道", "BULLISH", 62, "运行中",
                                     projected_high, projected_low - atr * .3, projected_high + width_end,
                                     "高低点平行抬升。"))
    elif normalized_high < -.05 and normalized_low < -.05:
        if width_end < width_start * .75:
            patterns.append(_pattern("下降楔形", "BULLISH", 64, "形成中",
                                     projected_high, projected_low - atr * .3, projected_high + width_start,
                                     "高低点同时下降但通道收窄，抛压可能衰减。"))
        elif abs(normalized_high - normalized_low) < .08:
            patterns.append(_pattern("下降通道", "BEARISH", 62, "运行中",
                                     projected_low, projected_high + atr * .3, projected_low - width_end,
                                     "高低点平行下降。"))
    elif abs(normalized_high) < .05 and abs(normalized_low) < .05:
        patterns.append(_pattern("箱体整理", "NEUTRAL", 58, "运行中",
                                 projected_high, projected_low, projected_high + width_end,
                                 "价格在近似水平支撑与阻力之间整理。"))

    previous_high = max(bar["h"] for bar in recent[-21:-1])
    previous_low = min(bar["l"] for bar in recent[-21:-1])
    if close > previous_high:
        patterns.append(_pattern("阻力突破", "BULLISH", 76, "已确认", previous_high,
                                 previous_high - atr, close + atr * 2.5, "收盘价突破前20根K线高点。"))
    if close < previous_low:
        patterns.append(_pattern("支撑跌破", "BEARISH", 76, "已确认", previous_low,
                                 previous_low + atr, max(.01, close - atr * 2.5), "收盘价跌破前20根K线低点。"))

    impulse_start = recent[-16]["c"]
    impulse_end = recent[-6]["c"]
    impulse = (impulse_end / impulse_start - 1) * 100 if impulse_start else 0
    pullback_slope, _ = _regression([bar["c"] for bar in recent[-6:]])
    if impulse >= 8 and pullback_slope <= 0 and abs(pullback_slope) < close * .015:
        flag_high = max(bar["h"] for bar in recent[-6:])
        flag_low = min(bar["l"] for bar in recent[-6:])
        patterns.append(_pattern("牛旗", "BULLISH", 67, "已确认" if close > flag_high else "形成中",
                                 flag_high, flag_low - atr * .3, flag_high + (impulse_end - impulse_start),
                                 "快速上涨后出现窄幅回撤通道。"))
    if impulse <= -8 and pullback_slope >= 0 and abs(pullback_slope) < close * .015:
        flag_high = max(bar["h"] for bar in recent[-6:])
        flag_low = min(bar["l"] for bar in recent[-6:])
        patterns.append(_pattern("熊旗", "BEARISH", 67, "已确认" if close < flag_low else "形成中",
                                 flag_low, flag_high + atr * .3, max(.01, flag_low - abs(impulse_end - impulse_start)),
                                 "快速下跌后出现窄幅反弹通道。"))

    # Candlestick structures use the last one to three complete bars.
    a, b = recent[-2], recent[-1]
    body = abs(b["c"] - b["o"])
    candle_range = max(.0001, b["h"] - b["l"])
    upper_wick = b["h"] - max(b["o"], b["c"])
    lower_wick = min(b["o"], b["c"]) - b["l"]
    if body / candle_range <= .12:
        patterns.append(_pattern("十字星", "NEUTRAL", 52, "出现", b["h"], b["l"], b["c"],
                                 "实体很小，代表多空暂时平衡；必须结合位置确认。"))
    if lower_wick >= max(body * 2, candle_range * .5) and upper_wick <= candle_range * .2:
        patterns.append(_pattern("锤头线", "BULLISH", 58, "出现", b["h"], b["l"], b["h"] + candle_range,
                                 "下影线较长，低位出现时更有意义。"))
    if upper_wick >= max(body * 2, candle_range * .5) and lower_wick <= candle_range * .2:
        patterns.append(_pattern("射击之星", "BEARISH", 58, "出现", b["l"], b["h"], b["l"] - candle_range,
                                 "上影线较长，高位出现时更有意义。"))
    if a["c"] < a["o"] and b["c"] > b["o"] and b["o"] <= a["c"] and b["c"] >= a["o"]:
        patterns.append(_pattern("看涨吞没", "BULLISH", 63, "出现", b["h"], b["l"], b["h"] + candle_range,
                                 "阳线实体覆盖前一根阴线实体。"))
    if a["c"] > a["o"] and b["c"] < b["o"] and b["o"] >= a["c"] and b["c"] <= a["o"]:
        patterns.append(_pattern("看跌吞没", "BEARISH", 63, "出现", b["l"], b["h"], b["l"] - candle_range,
                                 "阴线实体覆盖前一根阳线实体。"))
    if len(recent) >= 3:
        first, middle, last = recent[-3:]
        middle_body = abs(middle["c"] - middle["o"])
        if first["c"] < first["o"] and middle_body < abs(first["c"] - first["o"]) * .45 and last["c"] > last["o"] and last["c"] > (first["o"] + first["c"]) / 2:
            patterns.append(_pattern("早晨之星", "BULLISH", 66, "出现", last["h"], min(first["l"], middle["l"]),
                                     last["h"] + atr * 2, "三根K线构成潜在底部反转。"))
        if first["c"] > first["o"] and middle_body < abs(first["c"] - first["o"]) * .45 and last["c"] < last["o"] and last["c"] < (first["o"] + first["c"]) / 2:
            patterns.append(_pattern("黄昏之星", "BEARISH", 66, "出现", last["l"], max(first["h"], middle["h"]),
                                     max(.01, last["l"] - atr * 2), "三根K线构成潜在顶部反转。"))

    unique: dict[str, dict[str, Any]] = {}
    for item in sorted(patterns, key=lambda row: row["confidence"], reverse=True):
        unique.setdefault(item["name"], item)
    return list(unique.values())[:8]


def _zones(bars: list[dict[str, Any]], price: float, atr: float) -> list[dict[str, Any]]:
    highs, lows = _swings(bars[-180:], 2)
    pivots = [(value, "阻力") for _, value in highs] + [(value, "支撑") for _, value in lows]
    threshold = max(price * .012, atr * .55)
    clusters: list[list[tuple[float, str]]] = []
    for pivot in sorted(pivots):
        if not clusters or abs(pivot[0] - median([value for value, _ in clusters[-1]])) > threshold:
            clusters.append([pivot])
        else:
            clusters[-1].append(pivot)
    rows = []
    for cluster in clusters:
        level = median([value for value, _ in cluster])
        if len(cluster) < 2:
            continue
        rows.append({
            "level": round(level, 3), "low": round(level - threshold * .45, 3),
            "high": round(level + threshold * .45, 3), "touches": len(cluster),
            "role": "支撑" if level < price else "阻力",
            "distance_pct": round((level / price - 1) * 100, 2),
        })
    return sorted(rows, key=lambda row: abs(row["distance_pct"]))[:6]


def _timeframe_analysis(label: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    clean = _clean_bars(bars)
    if len(clean) < 30:
        return {"timeframe": label, "sufficient": False, "bars": len(clean), "patterns": [], "chart": []}
    closes = [bar["c"] for bar in clean]
    ma20, ma50 = _sma(closes, 20), _sma(closes, 50)
    ema12, ema26 = _ema_series(closes, 12), _ema_series(closes, 26)
    macd_series = [
        fast_value - slow_value
        if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(ema12, ema26)
    ]
    macd_values = [value for value in macd_series if value is not None]
    signal_values = _ema_series(macd_values, 9)
    macd_signal_series: list[float | None] = [None] * (len(closes) - len(macd_values)) + signal_values
    rsi_series = _rsi_series(closes, 14)
    fast, slow = ema12[-1], ema26[-1]
    macd = fast - slow if fast is not None and slow is not None else 0
    rsi = _rsi(closes, 14)
    atr = _atr(clean, 14) or closes[-1] * .025
    slope, _ = _regression(closes[-20:])
    slope_pct = slope / closes[-1] * 100
    score = 0
    score += 20 if ma20 and closes[-1] > ma20 else -20
    score += 20 if ma50 and closes[-1] > ma50 else -20
    score += 20 if ma20 and ma50 and ma20 > ma50 else -20
    score += 15 if macd > 0 else -15
    score += 15 if rsi and rsi >= 55 else -15 if rsi and rsi < 45 else 0
    score += 10 if slope_pct > .05 else -10 if slope_pct < -.05 else 0
    score = max(-100, min(100, score))
    trend = "UP" if score >= 35 else "DOWN" if score <= -35 else "RANGE"
    patterns = _detect_patterns(clean, atr)
    zones = _zones(clean, closes[-1], atr)
    high_slope, high_intercept = _regression([bar["h"] for bar in clean[-30:]])
    low_slope, low_intercept = _regression([bar["l"] for bar in clean[-30:]])
    quality_count = sum(bar.get("ohlcv_complete") for bar in clean[-60:])
    ma20_series, ma50_series = [], []
    for index in range(len(clean)):
        ma20_series.append(sum(closes[index - 19:index + 1]) / 20 if index >= 19 else None)
        ma50_series.append(sum(closes[index - 49:index + 1]) / 50 if index >= 49 else None)
    start = max(0, len(clean) - 360)
    chart = [{
        "t": bar["t"], "o": round(bar["o"], 4), "h": round(bar["h"], 4),
        "l": round(bar["l"], 4), "c": round(bar["c"], 4), "v": round(bar["v"], 2),
        "ma20": round(ma20_series[index], 4) if ma20_series[index] is not None else None,
        "ma50": round(ma50_series[index], 4) if ma50_series[index] is not None else None,
        "rsi14": round(rsi_series[index], 3) if rsi_series[index] is not None else None,
        "macd": round(macd_series[index], 5) if macd_series[index] is not None else None,
        "macd_signal": round(macd_signal_series[index], 5)
        if macd_signal_series[index] is not None else None,
        "macd_hist": round(macd_series[index] - macd_signal_series[index], 5)
        if macd_series[index] is not None and macd_signal_series[index] is not None else None,
    } for index, bar in enumerate(clean) if index >= start]
    return {
        "timeframe": label, "sufficient": True, "bars": len(clean), "trend": trend,
        "trend_score": score, "price": round(closes[-1], 4),
        "indicators": {
            "ma20": round(ma20, 4) if ma20 else None, "ma50": round(ma50, 4) if ma50 else None,
            "rsi14": round(rsi, 2) if rsi is not None else None, "macd": round(macd, 4),
            "atr14": round(atr, 4), "atr_pct": round(atr / closes[-1] * 100, 2),
            "slope20_pct_per_bar": round(slope_pct, 3),
        },
        "patterns": patterns, "zones": zones,
        "trendlines": {
            "upper": {"start": round(high_intercept, 4), "end": round(high_intercept + high_slope * 29, 4)},
            "lower": {"start": round(low_intercept, 4), "end": round(low_intercept + low_slope * 29, 4)},
        },
        "quality": {
            "ohlcv_complete_pct": round(quality_count / min(60, len(clean)) * 100, 1),
            "last_bar_time": clean[-1]["t"],
        },
        "chart": chart,
    }


def _historical_structure_stats(bars: list[dict[str, Any]], current_score: int) -> dict[str, Any]:
    clean = _clean_bars(bars)
    if len(clean) < 120:
        return {"sample_count": 0, "sufficient": False, "note": "历史长度不足"}
    closes = [bar["c"] for bar in clean]
    direction = 1 if current_score >= 0 else -1
    threshold = max(35, abs(current_score) - 15)
    events = []
    last_index = -30
    for index in range(55, len(clean) - 20):
        sample = closes[:index + 1]
        ma20, ma50 = _sma(sample, 20), _sma(sample, 50)
        rsi = _rsi(sample, 14)
        slope, _ = _regression(sample[-20:])
        score = 0
        score += 25 if sample[-1] > ma20 else -25
        score += 25 if sample[-1] > ma50 else -25
        score += 20 if ma20 > ma50 else -20
        score += 15 if rsi and rsi >= 55 else -15 if rsi and rsi < 45 else 0
        score += 15 if slope > 0 else -15
        if score * direction < threshold or index - last_index < 10:
            continue
        event = {}
        for horizon in (5, 10, 20):
            raw = (closes[index + horizon] / closes[index] - 1) * 100
            event[horizon] = raw * direction
        events.append(event)
        last_index = index
    output: dict[str, Any] = {"sample_count": len(events), "sufficient": len(events) >= 8}
    for horizon in (5, 10, 20):
        values = [event[horizon] for event in events]
        output[f"day_{horizon}"] = {
            "win_rate": round(sum(value > 0 for value in values) / len(values) * 100, 1) if values else None,
            "median_return_pct": round(median(values), 2) if values else None,
        }
    output["note"] = "同方向技术结构的历史统计；已按10根K线去重，不构成未来收益保证。"
    return output


def build_advanced_analysis(
    symbol: str,
    timeframes: dict[str, list[dict[str, Any]]],
    signal: dict[str, Any],
    provider: str,
    market_session: str,
    official_realtime: bool = False,
) -> dict[str, Any]:
    analyses = {label: _timeframe_analysis(label, bars) for label, bars in timeframes.items()}
    valid = {label: row for label, row in analyses.items() if row.get("sufficient")}
    if not valid:
        raise ValueError("没有足够的多周期OHLCV数据")
    available_weight = sum(TIMEFRAME_WEIGHTS.get(label, 0.1) for label in valid)
    consensus = sum(row["trend_score"] * TIMEFRAME_WEIGHTS.get(label, .1) for label, row in valid.items()) / available_weight
    bullish_count = sum(row["trend"] == "UP" for row in valid.values())
    bearish_count = sum(row["trend"] == "DOWN" for row in valid.values())
    bias = "LONG" if consensus >= 30 else "SHORT" if consensus <= -30 else "NEUTRAL"
    confidence = min(95, abs(consensus) * .65 + max(bullish_count, bearish_count) / len(valid) * 30)
    primary = valid.get("1D") or valid.get("4h") or next(iter(valid.values()))
    price = _num(signal.get("price"), primary["price"])
    atr = primary["indicators"]["atr14"]
    supports = sorted([zone for zone in primary["zones"] if zone["level"] < price], key=lambda row: price - row["level"])
    resistances = sorted([zone for zone in primary["zones"] if zone["level"] > price], key=lambda row: row["level"] - price)
    support = supports[0]["level"] if supports else price - atr * 1.2
    resistance = resistances[0]["level"] if resistances else price + atr * 1.2
    long_entry = max(price * 1.002, resistance * 1.002)
    long_stop = min(support - atr * .15, long_entry - atr)
    long_risk = max(.01, long_entry - long_stop)
    short_entry = min(price * .998, support * .998)
    short_stop = max(resistance + atr * .15, short_entry + atr)
    short_risk = max(.01, short_stop - short_entry)
    opportunity = signal.get("opportunity") or {}
    quote_time = str(signal.get("quote_time") or "")
    try:
        parsed = datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_minutes = max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60)
    except ValueError:
        age_minutes = 999999
    execution_ready = bool(official_realtime and market_session == "REGULAR" and age_minutes <= 5)
    long_rr = 2.0
    short_rr = 2.0
    if bias == "LONG" and opportunity.get("can_act") and execution_ready:
        decision, decision_label = "LONG_READY", "做多条件齐全"
    elif bias == "SHORT" and signal.get("holding"):
        decision, decision_label = "SELL_REVIEW", "持仓减仓/退出复核"
    elif bias == "LONG":
        decision, decision_label = "LONG_WATCH", "偏多，等待原则与实时闸门"
    elif bias == "SHORT":
        decision, decision_label = "SHORT_WATCH", "偏空，等待跌破与实时闸门"
    else:
        decision, decision_label = "WAIT", "多周期未形成共振"
    all_patterns = []
    for label, row in valid.items():
        for pattern in row["patterns"]:
            all_patterns.append({**pattern, "timeframe": label})
    all_patterns.sort(key=lambda row: (row["status"] == "已确认", row["confidence"]), reverse=True)
    daily_score = int(primary["trend_score"])
    return {
        "symbol": symbol, "price": round(price, 4), "bias": bias,
        "consensus_score": round(consensus, 1), "confidence": round(confidence, 1),
        "bullish_timeframes": bullish_count, "bearish_timeframes": bearish_count,
        "available_timeframes": list(valid), "decision": decision, "decision_label": decision_label,
        "timeframes": analyses, "patterns": all_patterns[:12],
        "plans": {
            "long": {
                "trigger": round(long_entry, 2), "stop": round(long_stop, 2),
                "target1": round(long_entry + long_risk * long_rr, 2),
                "target2": round(long_entry + long_risk * 3, 2),
                "risk_reward1": long_rr, "risk_reward2": 3.0,
                "invalidation": "跌破结构支撑或AI/基本面闸门转为否决",
            },
            "short": {
                "trigger": round(short_entry, 2), "stop": round(short_stop, 2),
                "target1": round(max(.01, short_entry - short_risk * short_rr), 2),
                "target2": round(max(.01, short_entry - short_risk * 3), 2),
                "risk_reward1": short_rr, "risk_reward2": 3.0,
                "invalidation": "重新站上结构阻力；财报或强催化剂前不裸空",
            },
        },
        "backtest": _historical_structure_stats(timeframes.get("1D", []), daily_score),
        "reasoning": {
            "summary": (
                f"{len(valid)}个周期中{bullish_count}个偏多、{bearish_count}个偏空，"
                f"加权共振分{consensus:+.1f}。当前结论为“{decision_label}”。"
            ),
            "principle_gate": opportunity.get("next_action") or "等待Anli原则判断",
            "data_gate": "可执行" if execution_ready else "当前行情不是官方盘中5分钟内数据，只能制定计划",
        },
        "data": {
            "provider": provider, "official_realtime": official_realtime,
            "market_session": market_session, "quote_time": quote_time,
            "execution_ready": execution_ready,
        },
        "warning": "形态识别是结构化概率工具，不是确定预测；只有突破/跌破确认后才生效，单笔风险应预先限制。",
    }
