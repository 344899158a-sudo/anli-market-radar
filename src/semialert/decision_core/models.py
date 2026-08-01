from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class RuleStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    TRIGGERED = "TRIGGERED"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionAction(str, Enum):
    BLOCKED = "BLOCKED"
    WATCH = "WATCH"
    READY = "READY"
    PROBE = "PROBE"
    STANDARD = "STANDARD"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    FREEZE = "FREEZE"


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_name: str
    priority: str
    status: RuleStatus
    severity: Severity
    reason_code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
    rule_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["severity"] = self.severity.value
        return result


@dataclass(frozen=True)
class Decision:
    id: str
    tenant_id: str
    account_id: str
    as_of: str
    action: DecisionAction
    score: int
    market_regime: str
    account_risk_state: str
    max_contracts: int
    reduce_fraction: Decimal | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    next_conditions: tuple[str, ...]
    rule_config_version: str
    input_snapshot_id: str
    input_snapshot_hash: str
    rule_results: tuple[RuleResult, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "as_of": self.as_of,
            "action": self.action.value,
            "score": self.score,
            "market_regime": self.market_regime,
            "account_risk_state": self.account_risk_state,
            "max_contracts": self.max_contracts,
            "reduce_fraction": str(self.reduce_fraction) if self.reduce_fraction is not None else None,
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "next_conditions": list(self.next_conditions),
            "rule_config_version": self.rule_config_version,
            "input_snapshot_id": self.input_snapshot_id,
            "input_snapshot_hash": self.input_snapshot_hash,
            "rule_results": [item.to_dict() for item in self.rule_results],
            "created_at": self.created_at,
        }

