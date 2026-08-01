from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Decision


class DecisionAuditStore:
    """Append-only decision snapshots, idempotency records and audit events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS decision_snapshots (
                    decision_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_snapshot_identity
                    ON decision_snapshots(tenant_id, account_id, as_of, snapshot_hash, rule_version);
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, account_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_decision(self, context: dict[str, Any], decision: Decision) -> dict[str, Any]:
        payload = decision.to_dict()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO decision_snapshots
                (decision_id, tenant_id, account_id, as_of, snapshot_id, snapshot_hash,
                 rule_version, input_json, decision_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.id,
                    decision.tenant_id,
                    decision.account_id,
                    decision.as_of,
                    decision.input_snapshot_id,
                    decision.input_snapshot_hash,
                    decision.rule_config_version,
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    decision.created_at,
                ),
            )
        return payload

    def get_decision(self, decision_id: str, tenant_id: str, account_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT decision_json FROM decision_snapshots
                WHERE decision_id = ? AND tenant_id = ? AND account_id = ?
                """,
                (decision_id, tenant_id, account_id),
            ).fetchone()
        return json.loads(row["decision_json"]) if row else None

    def list_recent_decisions(
        self,
        tenant_id: str,
        account_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT decision_json FROM decision_snapshots
                WHERE tenant_id = ? AND account_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (tenant_id, account_id, safe_limit),
            ).fetchall()
        return [json.loads(row["decision_json"]) for row in rows]
    def append_audit(
        self,
        tenant_id: str,
        account_id: str,
        actor_type: str,
        action: str,
        target_type: str,
        target_id: str,
        details: dict[str, Any],
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO audit_logs
                (tenant_id, account_id, actor_type, action, target_type, target_id, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    account_id,
                    actor_type,
                    action,
                    target_type,
                    target_id,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def idempotent_response(
        self,
        tenant_id: str,
        account_id: str,
        key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT request_hash, response_json FROM idempotency_records
                WHERE tenant_id = ? AND account_id = ? AND idempotency_key = ?
                """,
                (tenant_id, account_id, key),
            ).fetchone()
        if not row:
            return None
        if row["request_hash"] != request_hash:
            raise ValueError("idempotency key reused with a different request")
        return json.loads(row["response_json"])

    def save_idempotent_response(
        self,
        tenant_id: str,
        account_id: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO idempotency_records
                (tenant_id, account_id, idempotency_key, request_hash, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    account_id,
                    key,
                    request_hash,
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

