from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone


UTC = timezone.utc


def opportunity(
    symbol: str = "TEST",
    *,
    day_change: float = 0.5,
    drawdown: float = -4.0,
    distance_ma50: float = 2.0,
    rsi: float = 55.0,
    volume: float = 1.2,
    industry: bool | None = True,
    quality: bool | None = True,
    above_ma50: bool | None = True,
    stabilized: bool | None = True,
    not_chasing: bool | None = True,
) -> dict:
    return {
        "symbol": symbol,
        "name": f"{symbol} Corp",
        "sector": "半导体",
        "sector_benchmark": "SMH",
        "price": 100.0,
        "quote_time": "2026-08-01T20:00:00+00:00",
        "day_change_pct": day_change,
        "distance_ma50_pct": distance_ma50,
        "drawdown20_pct": drawdown,
        "ma50": 98.0,
        "rsi14": rsi,
        "volume_ratio": volume,
        "status": "WATCH",
        "score": 65,
        "checks": {
            "industry": industry,
            "quality": quality,
            "above_ma50": above_ma50,
            "stabilized": stabilized,
            "not_chasing": not_chasing,
        },
    }


def event(symbol: str, now: datetime, days: int, *, verified: bool = True) -> dict:
    at = now + timedelta(days=days)
    return {
        "id": f"{symbol.lower()}-event",
        "title": f"{symbol} 财报",
        "category": "财报",
        "at": at.isoformat(),
        "at_cn": at.astimezone(timezone(timedelta(hours=8))).isoformat(),
        "at_et": at.astimezone(timezone(timedelta(hours=-4))).isoformat(),
        "importance": 4,
        "scope": [symbol, "半导体"],
        "source": f"{symbol} Investor Relations",
        "source_url": "https://example.com/ir",
        "verification": "公司官网确认" if verified else "未核验",
        "note": "测试事件",
    }


def bundle(
    now: datetime,
    opportunities: list[dict] | None = None,
    events: list[dict] | None = None,
    *,
    regime: str = "UPTREND",
    breadth50: float = 62.0,
    qqq_above: bool = True,
    official_realtime: bool = False,
    age_hours: float = 1.0,
    quality: str = "OK",
) -> dict:
    opportunities = opportunities if opportunities is not None else [opportunity()]
    events = events or []
    snapshot_id = "fixture-snapshot"
    source = {
        "provider": "Fixture Public Feed",
        "feed": "fixture",
        "latency": "static-snapshot",
        "session": "REGULAR",
        "timezone": "America/New_York",
        "is_official_realtime": official_realtime,
    }
    modules_data = {
        "market-overview": {
            "regime": regime,
            "regime_label": "上升趋势" if regime == "UPTREND" else regime,
            "score": 72,
            "position_label": "趋势上方",
            "action": "只做符合剧本的个股",
            "breadth": {"above_ma50_pct": breadth50, "sample_size": len(opportunities), "universe_size": len(opportunities)},
            "assets": {
                "QQQ": {"above_ma50": qqq_above, "distance_ma50_pct": 2.0 if qqq_above else -2.0},
                "SPY": {"above_ma50": True, "distance_ma50_pct": 1.0},
                "^TNX": {"day_change_pct": 0.1, "price": 4.2},
                "^VIX": {"price": 16.0},
            },
        },
        "opportunities": opportunities,
        "event-calendar": {
            "weeks": [{"label": "本周", "risk_label": "高", "events": events}],
        },
        "sector-pulse": {"state": "STRONG", "state_label": "强", "breadth_pct": 66.0, "above_ma50_pct": 60.0},
        "qqq-analysis": {
            "symbol": "QQQ",
            "price": 500.0,
            "bias": "BULLISH",
            "confidence": 70.0,
            "consensus_score": 42.0,
            "decision": "WAIT",
            "decision_label": "等待触发",
            "recommendation": {"state": "SETUP", "technical_setup_ready": True, "execution_ready": official_realtime, "support": 490.0, "resistance": 510.0, "next_condition": "突破确认", "vetoes": []},
            "timeframes": {},
            "plans": {},
        },
        "watchlist": {
            "symbol_count": len(opportunities),
            "symbols": [{"symbol": item["symbol"], "name": item["name"], "sector": item["sector"]} for item in opportunities],
        },
    }
    manifest_modules = {}
    envelopes = {}
    for name, data in modules_data.items():
        envelope = {
            "snapshot_id": snapshot_id,
            "module": name,
            "data": deepcopy(data),
            "quality": {"status": "OK", "missing": [], "errors": []},
        }
        raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
        manifest_modules[name] = {
            "path": f"snapshots/{snapshot_id}/{name}.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        envelopes[name] = envelope
    return {
        "manifest": {
            "snapshot_id": snapshot_id,
            "schema_version": "1.0.0",
            "rule_version": "1.0.0",
            "as_of": (now - timedelta(hours=age_hours)).isoformat(),
            "generated_at": now.isoformat(),
            "source": source,
            "quality": {"status": quality, "missing": [], "errors": []},
            "modules": manifest_modules,
        },
        "modules": envelopes,
        "fetch": {"mode": "remote", "error": None},
    }

