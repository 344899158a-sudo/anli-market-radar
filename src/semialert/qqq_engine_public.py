from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .alpaca import AlpacaClient
from .public_market import YahooPublicClient
from .resilient_market import ResilientPublicClient
from .qqq_config import AppConfig
from .state import StateStore
from .strategy import benchmark_above_ma50, evaluate
from .market_regime import MARKET_SYMBOLS, build_market_overview
from .sector_pulse import build_semiconductor_pulse
from .advanced_technical import aggregate_bars, aggregate_intraday_bars


class MonitorEngine:
    def __init__(self, config: AppConfig, data_dir: str | Path) -> None:
        self.config = config
        alpaca = AlpacaClient(config.get("alpaca_feed", "iex"))
        self.client = alpaca if alpaca.configured else ResilientPublicClient()
        self.provider = "Alpaca IEX 实时" if alpaca.configured else self.client.active_provider
        self._history_cache_path = Path(data_dir) / "market_history_cache.json"
        self.store = StateStore(Path(data_dir) / "watchlist_state.db")
        for symbol in config.get("holdings", []):
            self.store.set_holding(symbol, True)
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, Any] = {
            "running": False, "configured": True, "feed": self.client.feed, "provider": self.provider,
            "is_official_realtime": alpaca.configured, "last_refresh": None, "last_history_refresh": None,
            "last_error": None, "company_count": len(config.symbols), "ticker_count": len(config.symbols), "sector_status": {},
        }
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._history_thread: threading.Thread | None = None
        self._technical_cache: dict[str, tuple[float, dict[str, list[dict[str, Any]]], dict[str, str]]] = {}
        self._technical_lock = threading.Lock()
        self._load_history_cache()

    def _load_history_cache(self) -> None:
        try:
            payload = json.loads(self._history_cache_path.read_text(encoding="utf-8"))
            saved_at = str(payload.get("saved_at") or "")
            parsed_at = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
            if parsed_at.tzinfo is None:
                raise ValueError("history cache saved_at must include a timezone")
            parsed_at = parsed_at.astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            if (parsed_at - now).total_seconds() > 300:
                raise ValueError("history cache saved_at is in the future")

            history = payload.get("history")
            if not isinstance(history, dict) or not history:
                raise ValueError("history cache is empty")
            cleaned = {
                str(symbol): bars
                for symbol, bars in history.items()
                if isinstance(symbol, str) and isinstance(bars, list)
            }
            if not cleaned:
                raise ValueError("history cache contains no valid symbols")

            age_seconds = max(0.0, (now - parsed_at).total_seconds())
            self.history = cleaned
            self.status["last_history_refresh"] = parsed_at.isoformat()
            self.status["history_cache_loaded"] = True
            self.status["history_cache_stale"] = age_seconds > 21600
            self.status.pop("history_cache_error", None)
        except FileNotFoundError:
            self.status["history_cache_loaded"] = False
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.history = {}
            self.status["history_cache_loaded"] = False
            self.status.pop("history_cache_stale", None)
            self.status["history_cache_error"] = str(exc)[:160]

    def _save_history_cache(self) -> None:
        if not self.history:
            return
        saved_at = str(
            self.status.get("last_history_refresh")
            or datetime.now(timezone.utc).isoformat()
        )
        payload = {"saved_at": saved_at, "history": self.history}
        self._history_cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._history_cache_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self._history_cache_path)
    @property
    def reference_symbols(self) -> list[str]:
        return list(dict.fromkeys([self.config.get("benchmark", "QQQ"), *self.config.sector_benchmarks.values(), *MARKET_SYMBOLS]))

    @property
    def all_symbols(self) -> list[str]:
        return self.config.symbols + [s for s in self.reference_symbols if s not in self.config.symbols]

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread = threading.Thread(target=self._loop, name="qqq-market-monitor", daemon=True); self._thread.start()

    def stop(self) -> None: self._stop.set()

    def _loop(self) -> None:
        self.status["running"] = True
        try:
            while not self._stop.is_set():
                try:
                    self.refresh()
                    self._ensure_history_refresh_async()
                    self.status["last_error"] = None
                except Exception as exc:
                    self.status["last_error"] = str(exc)
                self._stop.wait(float(self.config.get("poll_seconds", 30)))
        finally: self.status["running"] = False

    def _ensure_history_refresh_async(self) -> None:
        last = self.status.get("last_history_refresh")
        stale = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > 21600
        if (self.history and not stale) or (self._history_thread and self._history_thread.is_alive()):
            return
        self.status["history_loading"] = True
        self._history_thread = threading.Thread(
            target=self._history_worker,
            name="qqq-history-loader",
            daemon=True,
        )
        self._history_thread.start()

    def _history_worker(self) -> None:
        try:
            fresh = self.client.historical_daily_bars(
                self.all_symbols, int(self.config.get("history_days", 220))
            )
            quality_errors: dict[str, str] = {}
            if hasattr(self.client, "historical_ohlcv"):
                quality_symbols = [
                    symbol for symbol in self.config.symbols
                    if self.config.symbol_meta[symbol].get("sector") == "\u534a\u5bfc\u4f53"
                ] + ["SOXX", "QQQ", "^IXIC"]
                for symbol in dict.fromkeys(quality_symbols):
                    try:
                        history_range = "1y" if symbol == "^IXIC" else "5y"
                        fresh[symbol] = self.client.historical_ohlcv(symbol, history_range)
                    except Exception as exc:
                        quality_errors[symbol] = str(exc)[:120]
            with self._lock:
                self.history.update(fresh)
                self.status["ohlcv_quality_errors"] = quality_errors
                self.status["nasdaq_chart_error"] = quality_errors.get("^IXIC")
                self.status["last_history_refresh"] = datetime.now(timezone.utc).isoformat()
            self._save_history_cache()
            self.refresh()
        except Exception as exc:
            self.status["history_error"] = str(exc)
        finally:
            self.status["history_loading"] = False
    def _refresh_history_if_needed(self) -> None:
        last = self.status.get("last_history_refresh")
        stale = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > 21600
        if not self.history or stale:
            self.history = self.client.historical_daily_bars(self.all_symbols, int(self.config.get("history_days", 220)))
            if hasattr(self.client, "historical_ohlcv"):
                quality_symbols = [
                    symbol for symbol in self.config.symbols
                    if self.config.symbol_meta[symbol].get("sector") == "半导体"
                ] + ["SOXX", "QQQ", "^IXIC"]
                quality_errors = {}
                for symbol in dict.fromkeys(quality_symbols):
                    try:
                        history_range = "1y" if symbol == "^IXIC" else "5y"
                        self.history[symbol] = self.client.historical_ohlcv(symbol, history_range)
                    except Exception as exc:
                        quality_errors[symbol] = str(exc)[:120]
                self.status["ohlcv_quality_errors"] = quality_errors
                self.status["nasdaq_chart_error"] = quality_errors.get("^IXIC")
            self.status["last_history_refresh"] = datetime.now(timezone.utc).isoformat()
            self._save_history_cache()

    def _snapshots(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for start in range(0, len(self.all_symbols), 50):
            result.update(self.client.snapshots(self.all_symbols[start:start + 50]))
        return result

    def technical_timeframes(self, symbol: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
        now = datetime.now(timezone.utc).timestamp()
        with self._technical_lock:
            cached = self._technical_cache.get(symbol)
            if cached and now - cached[0] < 120:
                return cached[1], cached[2]
            errors: dict[str, str] = {}
            daily = self.history.get(symbol, [])
            if hasattr(self.client, "historical_ohlcv"):
                try:
                    daily = self.client.historical_ohlcv(symbol, "5y")
                    self.history[symbol] = daily
                except Exception as exc:
                    errors["1D"] = str(exc)[:160]
            frames = {"1D": daily, "1W": aggregate_bars(daily, weekly=True)}
            if hasattr(self.client, "interval_ohlcv"):
                try:
                    frames["15m"] = self.client.interval_ohlcv(symbol, "5d", "15m")
                except Exception as exc:
                    errors["15m"] = str(exc)[:160]
                try:
                    hourly = self.client.interval_ohlcv(symbol, "3mo", "60m")
                    frames["1h"] = hourly
                    frames["4h"] = aggregate_intraday_bars(hourly, size=4)
                except Exception as exc:
                    errors["1h/4h"] = str(exc)[:160]
            self._technical_cache[symbol] = (now, frames, errors)
            return frames, errors
    def refresh(self) -> None:
        with self._lock:
            snapshots = self._snapshots(); window = int(self.config.rules["ma_days"])
            active_provider = getattr(self.client, "active_provider", self.provider)
            self.provider = active_provider
            qqq = self.config.get("benchmark", "QQQ")
            qqq_ok = benchmark_above_ma50(self.history.get(qqq, []), snapshots.get(qqq, {}), window)
            sector_status = {sector: {"benchmark": benchmark, "above_ma50": benchmark_above_ma50(self.history.get(benchmark, []), snapshots.get(benchmark, {}), window)} for sector, benchmark in self.config.sector_benchmarks.items()}
            holdings = self.store.holdings(); signals: list[dict[str, Any]] = []
            for symbol in self.config.symbols:
                meta = self.config.symbol_meta[symbol]; sector = meta["sector"]; sector_info = sector_status[sector]
                signal = evaluate(symbol, meta["name"], self.history.get(symbol, []), snapshots.get(symbol, {}), sector_info["above_ma50"], bool(meta.get("quality_approved")), meta.get("catalyst_date"), self.config.rules, symbol in holdings)
                signal.update({"sector": sector, "sector_benchmark": sector_info["benchmark"], "holding": symbol in holdings})
                signals.append(signal)
            sector_pulse = build_semiconductor_pulse(signals, self.history, snapshots)
            self.store.save_signals(signals); self._emit_alerts(signals, sector_pulse)
            market_overview = build_market_overview(self.history, snapshots, self.config.symbols, active_provider)
            quote_times = [s.get("quote_time") for s in signals if s.get("quote_time")]
            self.status.update({"last_refresh": datetime.now(timezone.utc).isoformat(), "market_data_time": max(quote_times) if quote_times else None, "qqq_above_ma50": qqq_ok, "sector_status": sector_status, "market_overview": market_overview, "sector_pulse": sector_pulse, "provider": active_provider, "fallback_reason": getattr(self.client, "last_primary_error", None)})

    def _emit_alerts(self, signals: list[dict[str, Any]], sector_pulse: dict[str, Any] | None = None) -> None:
        day = date.today().isoformat()
        if sector_pulse and sector_pulse.get("state") in {"REVERSAL_ALERT", "TREND_CONFIRMATION", "RISK_OFF"}:
            state = str(sector_pulse["state"])
            leaders = "、".join(item["symbol"] for item in sector_pulse.get("leaders", [])[:3])
            message = (
                f"半导体{sector_pulse['state_label']}：{sector_pulse['positive_count']}/{sector_pulse['members']}上涨，"
                f"中位涨幅{sector_pulse['median_change_pct']:+.2f}%，领涨{leaders}。{sector_pulse['action']}"
            )
            self.store.add_alert("SOXX", f"SECTOR_{state}", message, f"{day}:SOXX:{state}")
        for s in signals:
            kind = message = None
            if s.get("status") == "READY": kind, message = "QUANT_CANDIDATE", f"{s['symbol']}（{s['sector']}）量价硬条件通过，等待AI基本面复核｜评分{s['score']}｜现价${s['price']}"
            elif s.get("exit_signal") == "SELL_1_2": kind, message = "PROTECT_HALF", f"{s['symbol']} 连续两日涨幅达到规则33：提醒止盈1/2"
            elif s.get("exit_signal") == "SELL_1_3": kind, message = "PROTECT_THIRD", f"{s['symbol']} 单日涨幅达到规则33：提醒止盈1/3"
            if kind: self.store.add_alert(s["symbol"], kind, message, f"{day}:{s['symbol']}:{kind}")
