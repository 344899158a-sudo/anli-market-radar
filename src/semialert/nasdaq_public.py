from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .public_market import PublicMarketError


ETF_SYMBOLS = {
    "QQQ", "SPY", "RSP", "IWM", "DIA", "SOXX", "SMH",
}
INDEX_MAP = {
    "^IXIC": ("COMP", "index"),
}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("$", "").replace("%", "").replace(",", "")
    if not text or text.upper() in {"N/A", "NA", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class NasdaqPublicClient:
    """Official Nasdaq.com public API fallback.

    Quotes may be delayed and do not include pre/after-market for every asset.
    """

    configured = True
    feed = "nasdaq-public-delayed"
    active_provider = "Nasdaq.com 公开延时报价"
    base_url = "https://api.nasdaq.com/api/quote"

    def __init__(self) -> None:
        self._daily_cache: dict[str, list[dict[str, Any]]] = {}
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
            ),
        }

    @staticmethod
    def _identity(symbol: str) -> tuple[str, str] | None:
        if symbol in INDEX_MAP:
            return INDEX_MAP[symbol]
        if symbol.startswith("^") or symbol == "DX-Y.NYB":
            return None
        return symbol.replace(".", "-"), "etf" if symbol in ETF_SYMBOLS else "stocks"

    def _json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise PublicMarketError(f"Nasdaq公开数据连接失败: {exc}") from exc
        data = payload.get("data")
        if not data:
            message = ((payload.get("status") or {}).get("bCodeMessage") or [{}])[0].get("errorMessage")
            raise PublicMarketError(message or "Nasdaq公开数据未返回")
        return data

    def _history_one(self, symbol: str, days: int) -> tuple[str, list[dict[str, Any]]]:
        identity = self._identity(symbol)
        if not identity:
            return symbol, []
        api_symbol, asset_class = identity
        from_date = (datetime.now(timezone.utc).date() - timedelta(days=max(days * 2, 420))).isoformat()
        query = urllib.parse.urlencode({
            "assetclass": asset_class,
            "fromdate": from_date,
            "limit": 5000,
        })
        data = self._json(
            f"{self.base_url}/{urllib.parse.quote(api_symbol, safe='')}/historical?{query}"
        )
        rows = ((data.get("tradesTable") or {}).get("rows") or [])
        bars: list[dict[str, Any]] = []
        for row in rows:
            close = _number(row.get("close"))
            open_ = _number(row.get("open"))
            high = _number(row.get("high"))
            low = _number(row.get("low"))
            if None in {open_, high, low, close}:
                continue
            try:
                date = datetime.strptime(str(row.get("date")), "%m/%d/%Y").replace(
                    tzinfo=ZoneInfo("America/New_York")
                )
            except ValueError:
                continue
            bars.append({
                "t": date.astimezone(timezone.utc).isoformat(),
                "o": open_,
                "h": high,
                "l": low,
                "c": close,
                "v": int(_number(row.get("volume")) or 0),
                "ohlcv_complete": True,
            })
        bars.sort(key=lambda item: item["t"])
        self._daily_cache[symbol] = bars
        return symbol, bars

    def historical_daily_bars(
        self, symbols: list[str], days: int = 220
    ) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._history_one, symbol, days) for symbol in symbols]
            for future in as_completed(futures):
                try:
                    symbol, bars = future.result()
                    output[symbol] = bars
                except PublicMarketError:
                    continue
        if not any(output.values()):
            raise PublicMarketError("Nasdaq公开历史数据全部失败")
        return output

    def historical_ohlcv(self, symbol: str, range_: str = "1y") -> list[dict[str, Any]]:
        days = 2200 if range_ == "5y" else 500
        _, bars = self._history_one(symbol, days)
        if not bars:
            raise PublicMarketError(f"{symbol} Nasdaq日K未返回")
        return bars

    @staticmethod
    def _quote_time(value: Any) -> str:
        text = str(value or "").replace(" ET", "").strip()
        eastern = ZoneInfo("America/New_York")
        for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=eastern)
                if fmt == "%b %d, %Y":
                    parsed = parsed.replace(hour=16)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                continue
        return datetime.now(timezone.utc).isoformat()

    def _snapshot_one(self, symbol: str) -> tuple[str, dict[str, Any] | None]:
        identity = self._identity(symbol)
        if not identity:
            return symbol, None
        api_symbol, asset_class = identity
        query = urllib.parse.urlencode({"assetclass": asset_class})
        data = self._json(
            f"{self.base_url}/{urllib.parse.quote(api_symbol, safe='')}/info?{query}"
        )
        primary = data.get("primaryData") or data.get("secondaryData") or {}
        price = _number(primary.get("lastSalePrice"))
        if price is None:
            return symbol, None
        change = _number(primary.get("netChange")) or 0.0
        previous = price - change
        quote_time = self._quote_time(primary.get("lastTradeTimestamp"))
        daily = (self._daily_cache.get(symbol) or [{}])[-1]
        market_status = str(data.get("marketStatus") or "Closed").upper()
        session = "REGULAR" if market_status == "OPEN" else "CLOSED"
        return symbol, {
            "latestTrade": {"p": price, "t": quote_time},
            "dailyBar": {
                "o": daily.get("o", price),
                "h": daily.get("h", price),
                "l": daily.get("l", price),
                "c": price,
                "v": int(_number(primary.get("volume")) or daily.get("v") or 0),
                "t": quote_time,
            },
            "prevDailyBar": {"c": previous or price},
            "session": {
                "market_state": market_status,
                "active_session": session,
                "active_price": price,
                "active_change_pct": round(change / previous * 100, 3) if previous else None,
                "regular_price": price,
                "regular_change_pct": round(change / previous * 100, 3) if previous else None,
                "premarket_price": None,
                "premarket_change_pct": None,
                "afterhours_price": None,
                "afterhours_change_pct": None,
            },
        }

    def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._snapshot_one, symbol) for symbol in symbols]
            for future in as_completed(futures):
                try:
                    symbol, snapshot = future.result()
                    if snapshot:
                        output[symbol] = snapshot
                except PublicMarketError:
                    continue
        if not output:
            raise PublicMarketError("Nasdaq公开延时报价全部失败")
        return output

    def interval_ohlcv(self, symbol: str, range_: str, interval: str) -> list[dict[str, Any]]:
        raise PublicMarketError(
            f"Nasdaq备用源不提供本系统所需的{interval}完整历史；仅保留日K决策"
        )
