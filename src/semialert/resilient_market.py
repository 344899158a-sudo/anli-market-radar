from __future__ import annotations

from typing import Any, Callable

from .nasdaq_public import NasdaqPublicClient
from .public_market import PublicMarketError, YahooPublicClient


class ResilientPublicClient:
    """Use Yahoo first and transparently fall back to delayed Nasdaq.com data."""

    configured = True
    feed = "public-resilient"

    def __init__(self) -> None:
        self.yahoo = YahooPublicClient()
        self.nasdaq = NasdaqPublicClient()
        self.active_provider = "Yahoo 公开近实时"
        self.last_primary_error: str | None = None

    def _fallback(
        self,
        primary: Callable[..., Any],
        secondary: Callable[..., Any],
        *args: Any,
    ) -> Any:
        try:
            result = primary(*args)
            self.active_provider = "Yahoo 公开近实时"
            self.last_primary_error = None
            return result
        except (PublicMarketError, OSError) as exc:
            self.last_primary_error = str(exc)
            result = secondary(*args)
            self.active_provider = "Nasdaq.com 公开延时报价"
            return result

    def historical_daily_bars(
        self, symbols: list[str], days: int = 220
    ) -> dict[str, list[dict[str, Any]]]:
        return self._fallback(
            self.yahoo.historical_daily_bars,
            self.nasdaq.historical_daily_bars,
            symbols,
            days,
        )

    def historical_ohlcv(self, symbol: str, range_: str = "1y") -> list[dict[str, Any]]:
        return self._fallback(
            self.yahoo.historical_ohlcv,
            self.nasdaq.historical_ohlcv,
            symbol,
            range_,
        )

    def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return self._fallback(
            self.yahoo.snapshots,
            self.nasdaq.snapshots,
            symbols,
        )

    def interval_ohlcv(
        self, symbol: str, range_: str, interval: str
    ) -> list[dict[str, Any]]:
        return self._fallback(
            self.yahoo.interval_ohlcv,
            self.nasdaq.interval_ohlcv,
            symbol,
            range_,
            interval,
        )
