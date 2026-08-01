from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path))
        self._init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS signals (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    dedupe_key TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS holdings (
                    symbol TEXT PRIMARY KEY,
                    held INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS ai_analyses (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS option_positions (
                    contract TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def save_signals(self, signals: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO signals(symbol,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                [(s["symbol"], json.dumps(s, ensure_ascii=False), now) for s in signals],
            )

    def get_signals(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM signals").fetchall()
        signals = [json.loads(row["payload"]) for row in rows]
        order = {"READY": 0, "WATCH": 1, "REJECT": 2, "NO_DATA": 3}
        return sorted(signals, key=lambda s: (order.get(s.get("status"), 9), -s.get("score", 0), s["symbol"]))

    def add_alert(self, symbol: str, kind: str, message: str, dedupe_key: str) -> bool:
        try:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO alerts(symbol,kind,message,created_at,dedupe_key) VALUES(?,?,?,?,?)",
                    (symbol, kind, message, datetime.now(timezone.utc).isoformat(), dedupe_key),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,symbol,kind,message,created_at FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def holdings(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT symbol FROM holdings WHERE held=1").fetchall()
        return {row["symbol"] for row in rows}

    def set_holding(self, symbol: str, held: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO holdings(symbol,held) VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET held=excluded.held",
                (symbol.upper(), int(held)),
            )
    def save_ai_analysis(self, analysis: dict[str, Any]) -> None:
        analyzed_at = str(analysis.get("analyzed_at") or datetime.now(timezone.utc).isoformat())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO ai_analyses(symbol,payload,analyzed_at) VALUES(?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload,analyzed_at=excluded.analyzed_at",
                (analysis["symbol"].upper(), json.dumps(analysis, ensure_ascii=False), analyzed_at),
            )

    def get_ai_analysis(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM ai_analyses WHERE symbol=?", (symbol.upper(),)).fetchone()
        return json.loads(row["payload"]) if row else None

    def get_ai_analyses(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM ai_analyses ORDER BY analyzed_at DESC").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_option_position(self, contract: str, symbol: str, quantity: int, avg_cost: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO option_positions(contract,symbol,quantity,avg_cost,opened_at,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(contract) DO UPDATE SET symbol=excluded.symbol,quantity=excluded.quantity,avg_cost=excluded.avg_cost,updated_at=excluded.updated_at",
                (contract.upper(), symbol.upper(), int(quantity), float(avg_cost), now, now),
            )

    def delete_option_position(self, contract: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM option_positions WHERE contract=?", (contract.upper(),))

    def get_option_positions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT contract,symbol,quantity,avg_cost,opened_at,updated_at FROM option_positions ORDER BY opened_at"
            ).fetchall()
        return [dict(row) for row in rows]
