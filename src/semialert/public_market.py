from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


class PublicMarketError(RuntimeError):
    pass


class YahooPublicClient:
    """No-key public Yahoo Finance reader. Near-real-time, unofficial, best-effort."""

    base_url = "https://query1.finance.yahoo.com/v7/finance/spark"
    configured = True
    feed = "yahoo-public"

    def _get(self, symbols: list[str], range_: str, interval: str) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({
            "symbols": ",".join(symbols), "range": range_, "interval": interval,
            "indicators": "close", "includeTimestamps": "true", "includePrePost": "true",
        })
        req = urllib.request.Request(
            f"{self.base_url}?{params}",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 Anli-QQQ-Radar/2.0"},
        )
        payload = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise PublicMarketError(f"公开行情 HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
        if payload is None:
            raise PublicMarketError(f"公开行情连接连续失败: {last_error}") from last_error
        result = (payload.get("spark") or {}).get("result") or []
        if not result:
            raise PublicMarketError("公开行情暂未返回数据")
        return result

    @staticmethod
    def _response(entry: dict[str, Any]) -> dict[str, Any]:
        responses = entry.get("response") or []
        return responses[0] if responses else {}

    def historical_daily_bars(self, symbols: list[str], days: int = 220) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
        for start in range(0, len(symbols), 10):
            for entry in self._get(symbols[start:start + 10], "1y", "1d"):
                symbol = entry.get("symbol")
                response = self._response(entry)
                timestamps = response.get("timestamp") or []
                quote_sets = (response.get("indicators") or {}).get("quote") or []
                quote = quote_sets[0] if quote_sets else {}
                opens, highs = quote.get("open") or [], quote.get("high") or []
                lows, closes, volumes = quote.get("low") or [], quote.get("close") or [], quote.get("volume") or []
                bars: list[dict[str, Any]] = []
                for i, ts in enumerate(timestamps):
                    close = closes[i] if i < len(closes) else None
                    if close is None:
                        continue
                    open_ = opens[i] if i < len(opens) and opens[i] is not None else close
                    high = highs[i] if i < len(highs) and highs[i] is not None else close
                    low = lows[i] if i < len(lows) and lows[i] is not None else close
                    volume = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                    bars.append({
                        "t": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                        "o": open_, "h": high, "l": low, "c": close, "v": volume,
                    })
                if symbol:
                    output[symbol] = bars
        return output

    def historical_ohlcv(self, symbol: str, range_: str = "1y") -> list[dict[str, Any]]:
        encoded = urllib.parse.quote(symbol, safe="")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={range_}&interval=1d&includePrePost=false&events=div%2Csplits"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 Anli-Market-Radar/3.0"})
        payload = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise PublicMarketError(f"公开行情 HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
        if payload is None:
            raise PublicMarketError(f"公开行情连接连续失败: {last_error}") from last_error
        results = (payload.get("chart") or {}).get("result") or []
        if not results:
            raise PublicMarketError(f"{symbol} 日K未返回数据")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_sets = (result.get("indicators") or {}).get("quote") or []
        quote = quote_sets[0] if quote_sets else {}
        opens, highs = quote.get("open") or [], quote.get("high") or []
        lows, closes, volumes = quote.get("low") or [], quote.get("close") or [], quote.get("volume") or []
        bars: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            values = [series[index] if index < len(series) else None for series in (opens, highs, lows, closes)]
            if any(value is None for value in values):
                continue
            volume = volumes[index] if index < len(volumes) and volumes[index] is not None else 0
            bars.append({
                "t": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                "o": values[0], "h": values[1], "l": values[2], "c": values[3], "v": volume,
                "ohlcv_complete": True,
            })
        if not bars:
            raise PublicMarketError(f"{symbol} 日K OHLC为空")
        return bars
    def interval_ohlcv(self, symbol: str, range_: str, interval: str) -> list[dict[str, Any]]:
        """Fetch complete OHLCV bars for one symbol and one supported Yahoo interval."""
        encoded = urllib.parse.quote(symbol, safe="")
        params = urllib.parse.urlencode({
            "range": range_, "interval": interval, "includePrePost": "false",
            "events": "div,splits",
        })
        req = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{params}",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 Anli-Structure-Radar/4.0"},
        )
        payload = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise PublicMarketError(f"公开行情 HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
        if payload is None:
            raise PublicMarketError(f"公开行情连接连续失败: {last_error}") from last_error
        results = (payload.get("chart") or {}).get("result") or []
        if not results:
            raise PublicMarketError(f"{symbol} {interval} OHLCV未返回数据")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_sets = (result.get("indicators") or {}).get("quote") or []
        quote = quote_sets[0] if quote_sets else {}
        series = [quote.get(key) or [] for key in ("open", "high", "low", "close")]
        volumes = quote.get("volume") or []
        bars = []
        for index, timestamp in enumerate(timestamps):
            values = [values[index] if index < len(values) else None for values in series]
            if any(value is None for value in values):
                continue
            bars.append({
                "t": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                "o": float(values[0]), "h": float(values[1]),
                "l": float(values[2]), "c": float(values[3]),
                "v": int(volumes[index] or 0) if index < len(volumes) else 0,
                "ohlcv_complete": True,
            })
        if not bars:
            raise PublicMarketError(f"{symbol} {interval} OHLCV为空")
        return bars
    def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for start in range(0, len(symbols), 10):
            for entry in self._get(symbols[start:start + 10], "1d", "5m"):
                symbol = entry.get("symbol")
                response = self._response(entry)
                meta = response.get("meta") or {}
                previous = meta.get("chartPreviousClose") or meta.get("previousClose")
                regular_price = meta.get("regularMarketPrice")
                regular_time = meta.get("regularMarketTime")
                pre_price = meta.get("preMarketPrice")
                pre_time = meta.get("preMarketTime")
                post_price = meta.get("postMarketPrice")
                post_time = meta.get("postMarketTime")
                market_state = str(meta.get("marketState") or "UNKNOWN").upper()
                timestamps = response.get("timestamp") or []
                quote_sets = (response.get("indicators") or {}).get("quote") or []
                closes = (quote_sets[0].get("close") or []) if quote_sets else []
                latest_pairs = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
                latest_time, latest_price = latest_pairs[-1] if latest_pairs else (regular_time, regular_price)
                if market_state == "PRE" and pre_price is not None:
                    active_session, active_price, active_time = "PREMARKET", pre_price, pre_time
                elif market_state in {"POST", "POSTPOST"} and post_price is not None:
                    active_session, active_price, active_time = "AFTERHOURS", post_price, post_time
                elif market_state == "REGULAR":
                    active_session, active_price, active_time = "REGULAR", regular_price, regular_time
                elif post_price is not None and post_time and (not regular_time or post_time > regular_time):
                    active_session, active_price, active_time = "AFTERHOURS", post_price, post_time
                else:
                    active_session, active_price, active_time = "CLOSED", regular_price, regular_time
                if latest_time and (not active_time or latest_time > active_time):
                    active_price, active_time = latest_price, latest_time
                if not symbol or active_price is None:
                    continue
                previous = previous or regular_price or active_price
                regular_price = regular_price or active_price
                def pct(value, base):
                    return round((float(value) / float(base) - 1) * 100, 3) if value is not None and base else None
                iso = datetime.fromtimestamp(active_time, timezone.utc).isoformat() if active_time else ""
                output[symbol] = {
                    "latestTrade": {"p": active_price, "t": iso},
                    "dailyBar": {
                        "o": meta.get("regularMarketOpen") or regular_price,
                        "h": meta.get("regularMarketDayHigh") or regular_price,
                        "l": meta.get("regularMarketDayLow") or regular_price,
                        "c": regular_price, "v": meta.get("regularMarketVolume") or 0,
                        "t": datetime.fromtimestamp(regular_time, timezone.utc).isoformat() if regular_time else iso,
                    },
                    "prevDailyBar": {"c": previous},
                    "session": {
                        "market_state": market_state,
                        "active_session": active_session,
                        "active_price": active_price,
                        "active_change_pct": pct(active_price, previous),
                        "regular_price": regular_price,
                        "regular_change_pct": pct(regular_price, previous),
                        "premarket_price": pre_price,
                        "premarket_change_pct": pct(pre_price, previous),
                        "afterhours_price": post_price,
                        "afterhours_change_pct": pct(post_price, regular_price),
                    },
                }
        if not output:
            raise PublicMarketError("公开行情返回为空，可能处于临时限流状态")
        return output