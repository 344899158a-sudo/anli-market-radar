from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    base_url = "https://data.alpaca.markets"

    def __init__(self, feed: str = "iex") -> None:
        self.key = os.getenv("APCA_API_KEY_ID", "").strip()
        self.secret = os.getenv("APCA_API_SECRET_KEY", "").strip()
        self.feed = feed

    @property
    def configured(self) -> bool:
        return bool(self.key and self.secret)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise AlpacaError("尚未配置 APCA_API_KEY_ID / APCA_API_SECRET_KEY")
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{self.base_url}{path}?{query}",
            headers={
                "APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "Accept": "application/json",
                "User-Agent": "Anli-Semiconductor-Alerts/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AlpacaError(f"Alpaca HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise AlpacaError(f"无法连接 Alpaca: {exc.reason}") from exc

    def historical_daily_bars(self, symbols: list[str], days: int = 220) -> dict[str, list[dict[str, Any]]]:
        start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        result: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
        token: str | None = None
        while True:
            params: dict[str, Any] = {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "start": start,
                "limit": 10000,
                "adjustment": "all",
                "feed": self.feed,
                "sort": "asc",
            }
            if token:
                params["page_token"] = token
            payload = self._get("/v2/stocks/bars", params)
            for symbol, bars in payload.get("bars", {}).items():
                result.setdefault(symbol, []).extend(bars)
            token = payload.get("next_page_token")
            if not token:
                break
        return result

    def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        payload = self._get(
            "/v2/stocks/snapshots",
            {"symbols": ",".join(symbols), "feed": self.feed},
        )
        return payload.get("snapshots", payload)
