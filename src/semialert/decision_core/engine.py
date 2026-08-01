from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Any

from .models import Decision, DecisionAction, RuleResult, RuleStatus, Severity


PRIORITY_ORDER = {f"P{number}": number for number in range(9)}


def load_rule_config(path: str | Path) -> dict[str, Any]:
    """The checked-in .yaml is JSON-compatible YAML, avoiding a runtime parser dependency."""
    with Path(path).open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not config.get("version"):
        raise ValueError("rule config requires a version")
    return config


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} is missing")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _nested(context: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def snapshot_hash(context: dict[str, Any]) -> str:
    encoded = json.dumps(_canonical(context), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class DecisionEngine:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = deepcopy(config)
        self.version = str(config["version"])

    def _result(
        self,
        rule_id: str,
        name: str,
        priority: str,
        status: RuleStatus,
        reason_code: str,
        message: str,
        *,
        severity: Severity = Severity.INFO,
        evidence: dict[str, Any] | None = None,
        suggested_action: str | None = None,
    ) -> RuleResult:
        return RuleResult(
            rule_id=rule_id,
            rule_name=name,
            priority=priority,
            status=status,
            severity=severity,
            reason_code=reason_code,
            message=message,
            evidence=evidence or {},
            suggested_action=suggested_action,
            rule_version=self.version,
        )

    def evaluate(self, raw_context: dict[str, Any]) -> Decision:
        context = deepcopy(raw_context)
        as_of = str(context.get("as_of") or "")
        if not as_of:
            raise ValueError("as_of is required")
        parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if parsed_as_of.tzinfo is None:
            raise ValueError("as_of must include timezone")
        if parsed_as_of > datetime.now(timezone.utc):
            raise ValueError("as_of cannot be in the future")

        tenant_id = str(context.get("tenant_id") or "")
        account_id = str(context.get("account_id") or "")
        if not tenant_id or not account_id:
            raise ValueError("tenant_id and account_id are required")

        results = self._evaluate_rules(context)
        results.sort(key=lambda item: (PRIORITY_ORDER[item.priority], item.rule_id))
        score = self._score(context)
        risk_state = self._account_risk_state(context, results)
        max_contracts = self._position_size(context, results)
        action, reduce_fraction = self._map_action(context, results, score, max_contracts)

        blocking = [item for item in results if item.status in {RuleStatus.BLOCK, RuleStatus.UNKNOWN}]
        triggered = [item for item in results if item.status == RuleStatus.TRIGGERED]
        warnings = tuple(item.message for item in results if item.status == RuleStatus.WARN)
        reasons = tuple(dict.fromkeys(item.reason_code for item in [*triggered, *blocking]))
        next_conditions = tuple(
            dict.fromkeys(
                item.suggested_action
                for item in results
                if item.suggested_action and item.status in {RuleStatus.BLOCK, RuleStatus.WARN, RuleStatus.UNKNOWN}
            )
        )
        digest = snapshot_hash(context)
        snapshot_id = f"snap_{digest[:20]}"
        decision_seed = f"{tenant_id}|{account_id}|{as_of}|{self.version}|{digest}"
        decision_id = f"dec_{uuid.uuid5(uuid.NAMESPACE_URL, decision_seed).hex}"
        return Decision(
            id=decision_id,
            tenant_id=tenant_id,
            account_id=account_id,
            as_of=parsed_as_of.astimezone(timezone.utc).isoformat(),
            action=action,
            score=score,
            market_regime=str(_nested(context, "market.regime", "UNKNOWN")),
            account_risk_state=risk_state,
            max_contracts=max_contracts,
            reduce_fraction=reduce_fraction,
            reason_codes=reasons,
            warnings=warnings,
            next_conditions=next_conditions,
            rule_config_version=self.version,
            input_snapshot_id=snapshot_id,
            input_snapshot_hash=digest,
            rule_results=tuple(results),
            created_at=parsed_as_of.astimezone(timezone.utc).isoformat(),
        )

    def _evaluate_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        return [
            *self._data_rules(context),
            *self._account_rules(context),
            *self._thesis_rules(context),
            *self._position_and_option_rules(context),
            *self._strategy_rules(context),
            *self._entry_rules(context),
        ]

    def _data_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        complete = bool(_nested(context, "data.required_fields_complete", False))
        age = _nested(context, "data.quote_age_seconds")
        max_age = int(self.config["data"]["max_quote_age_seconds"])
        results = [
            self._result(
                "R-DATA-01",
                "关键数据完整",
                "P1",
                RuleStatus.PASS if complete else RuleStatus.BLOCK,
                "DATA_COMPLETE" if complete else "REQUIRED_DATA_MISSING",
                "关键决策字段完整" if complete else "关键决策字段缺失，禁止生成可执行结论",
                severity=Severity.CRITICAL if not complete else Severity.INFO,
                evidence={"required_fields_complete": complete},
                suggested_action=None if complete else "补齐必填字段并重新评估",
            )
        ]
        if age is None:
            results.append(self._result(
                "R-DATA-02", "报价时效", "P1", RuleStatus.UNKNOWN, "QUOTE_AGE_UNKNOWN",
                "报价时间未知", severity=Severity.CRITICAL,
                suggested_action="刷新报价并确认数据时间",
            ))
        else:
            fresh = int(age) <= max_age
            results.append(self._result(
                "R-DATA-02", "报价时效", "P1",
                RuleStatus.PASS if fresh else RuleStatus.BLOCK,
                "QUOTE_FRESH" if fresh else "QUOTE_STALE",
                "报价在允许时效内" if fresh else "报价已过期",
                severity=Severity.CRITICAL if not fresh else Severity.INFO,
                evidence={"quote_age_seconds": int(age), "max_age_seconds": max_age},
                suggested_action=None if fresh else "刷新行情后重新评估",
            ))
        return results

    def _account_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        risk = self.config["risk"]
        account = context.get("account") or {}
        results: list[RuleResult] = []
        required = ("equity", "planned_open_risk", "position_count", "new_position_market_value")
        if any(account.get(field) is None for field in required):
            return [self._result(
                "R-ACCOUNT-00", "账户风险数据", "P2", RuleStatus.UNKNOWN,
                "ACCOUNT_RISK_DATA_MISSING", "账户风险字段不完整",
                severity=Severity.CRITICAL, suggested_action="补齐账户净值、计划风险和持仓数据",
            )]
        equity = _decimal(account["equity"], "account.equity")
        if equity <= 0:
            return [self._result(
                "R-ACCOUNT-00", "账户净值", "P2", RuleStatus.BLOCK,
                "INVALID_ACCOUNT_EQUITY", "账户净值必须大于0",
                severity=Severity.CRITICAL,
            )]
        drawdown_hits = []
        for key, config_key in (
            ("daily_drawdown_pct", "daily_drawdown_freeze_pct"),
            ("weekly_drawdown_pct", "weekly_drawdown_freeze_pct"),
            ("monthly_drawdown_pct", "monthly_drawdown_freeze_pct"),
        ):
            if account.get(key) is not None and abs(_decimal(account[key], key)) >= _decimal(risk[config_key], config_key):
                drawdown_hits.append(key)
        consecutive = int(account.get("consecutive_losses") or 0)
        frozen = bool(drawdown_hits or consecutive >= int(risk["consecutive_loss_freeze_count"]))
        results.append(self._result(
            "R-ACCOUNT-01", "账户冻结", "P2",
            RuleStatus.TRIGGERED if frozen else RuleStatus.PASS,
            "ACCOUNT_FROZEN" if frozen else "ACCOUNT_NORMAL",
            "账户回撤或连续亏损触发冻结" if frozen else "账户未触发冻结",
            severity=Severity.CRITICAL if frozen else Severity.INFO,
            evidence={"drawdown_hits": drawdown_hits, "consecutive_losses": consecutive},
            suggested_action="只允许减仓、退出和复盘" if frozen else None,
        ))
        at_limit = int(account["position_count"]) >= int(risk["max_positions"]) and not bool(_nested(context, "position.exists", False))
        results.append(self._result(
            "R-ACCOUNT-02", "最大持仓数量", "P2",
            RuleStatus.BLOCK if at_limit else RuleStatus.PASS,
            "MAX_POSITIONS_REACHED" if at_limit else "POSITION_COUNT_OK",
            "持仓数量已达到上限" if at_limit else "持仓数量在上限内",
            severity=Severity.HIGH if at_limit else Severity.INFO,
            evidence={"position_count": int(account["position_count"]), "limit": int(risk["max_positions"])},
            suggested_action="先降低现有持仓数量" if at_limit else None,
        ))
        position_pct = _decimal(account["new_position_market_value"], "new_position_market_value") / equity * Decimal("100")
        max_position_pct = _decimal(risk["max_position_market_value_pct"], "max_position_market_value_pct")
        results.append(self._result(
            "R-ACCOUNT-03", "单仓市值上限", "P2",
            RuleStatus.BLOCK if position_pct > max_position_pct else RuleStatus.PASS,
            "POSITION_VALUE_LIMIT" if position_pct > max_position_pct else "POSITION_VALUE_OK",
            "计划单仓市值超过账户上限" if position_pct > max_position_pct else "计划单仓市值在上限内",
            severity=Severity.HIGH if position_pct > max_position_pct else Severity.INFO,
            evidence={"position_market_value_pct": str(position_pct), "limit_pct": str(max_position_pct)},
            suggested_action="缩小仓位至账户净值10%以内" if position_pct > max_position_pct else None,
        ))
        planned_risk_pct = _decimal(account["planned_open_risk"], "planned_open_risk") / equity * Decimal("100")
        max_risk_pct = _decimal(risk["max_total_open_risk_pct"], "max_total_open_risk_pct")
        results.append(self._result(
            "R-ACCOUNT-04", "总计划风险", "P2",
            RuleStatus.BLOCK if planned_risk_pct > max_risk_pct else RuleStatus.PASS,
            "TOTAL_RISK_LIMIT" if planned_risk_pct > max_risk_pct else "TOTAL_RISK_OK",
            "总计划风险超过上限" if planned_risk_pct > max_risk_pct else "总计划风险在上限内",
            severity=Severity.CRITICAL if planned_risk_pct > max_risk_pct else Severity.INFO,
            evidence={"planned_open_risk_pct": str(planned_risk_pct), "limit_pct": str(max_risk_pct)},
            suggested_action="降低计划风险后重新评估" if planned_risk_pct > max_risk_pct else None,
        ))
        theme_pct = _decimal(account.get("theme_exposure_pct", "0"), "theme_exposure_pct")
        max_theme = _decimal(risk["max_same_theme_exposure_pct"], "max_same_theme_exposure_pct")
        results.append(self._result(
            "R-THEME-01", "主题集中度", "P2",
            RuleStatus.BLOCK if theme_pct > max_theme else RuleStatus.PASS,
            "THEME_CONCENTRATION" if theme_pct > max_theme else "THEME_EXPOSURE_OK",
            "同主题风险超过上限" if theme_pct > max_theme else "主题集中度在上限内",
            severity=Severity.HIGH if theme_pct > max_theme else Severity.INFO,
            evidence={"theme_exposure_pct": str(theme_pct), "limit_pct": str(max_theme)},
            suggested_action="降低同主题风险或减少合约数量" if theme_pct > max_theme else None,
        ))
        return results

    def _thesis_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        thesis = context.get("thesis") or {}
        required = (
            thesis.get("invalidation_condition"),
            thesis.get("underlying_invalidation_price"),
            thesis.get("latest_validation_date"),
        )
        complete = all(value not in (None, "") for value in required)
        invalidated = bool(thesis.get("logic_invalidated"))
        return [
            self._result(
                "R-THESIS-01", "逻辑失效条件", "P3",
                RuleStatus.PASS if complete else RuleStatus.BLOCK,
                "THESIS_FIELDS_COMPLETE" if complete else "THESIS_INVALIDATION_MISSING",
                "逻辑失效条件完整" if complete else "缺少逻辑失效条件、正股失效位或最晚验证日期",
                severity=Severity.CRITICAL if not complete else Severity.INFO,
                suggested_action=None if complete else "补齐三项失效字段",
            ),
            self._result(
                "R-THESIS-02", "公司逻辑有效性", "P3",
                RuleStatus.TRIGGERED if invalidated else RuleStatus.PASS,
                "THESIS_INVALIDATED" if invalidated else "THESIS_VALID",
                "公司逻辑已失效，必须退出" if invalidated else "公司逻辑未被标记失效",
                severity=Severity.CRITICAL if invalidated else Severity.INFO,
                suggested_action="记录逻辑失效证据并退出持仓" if invalidated else None,
            ),
        ]

    def _position_and_option_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        option = context.get("option") or {}
        position = context.get("position") or {}
        config = self.config["option"]
        results: list[RuleResult] = []
        position_dte = position.get("dte")
        if bool(position.get("exists")) and position_dte is not None and int(position_dte) <= int(config["dte_exit"]):
            results.append(self._result(
                "R-OPTION-02", "持仓DTE退出", "P4", RuleStatus.TRIGGERED,
                "DTE_EXIT", "持仓剩余到期日不超过强制退出阈值",
                severity=Severity.CRITICAL,
                evidence={"dte": int(position_dte), "exit_dte": int(config["dte_exit"])},
                suggested_action="记录全部退出",
            ))
        else:
            results.append(self._result(
                "R-OPTION-02", "持仓DTE退出", "P4", RuleStatus.PASS,
                "DTE_NOT_EXIT", "未触发DTE强制退出",
            ))
        one_day = _decimal(position.get("day_return_pct", "0"), "position.day_return_pct")
        two_day = _decimal(position.get("two_day_return_pct", "0"), "position.two_day_return_pct")
        profit = self.config["profit_protection"]
        if bool(position.get("exists")) and two_day >= _decimal(profit["two_day_return_pct"], "two_day_return_pct"):
            results.append(self._result(
                "RULE_033B", "两日利润保护", "P4", RuleStatus.TRIGGERED,
                "REDUCE_HALF", "两日累计涨幅达到利润保护阈值",
                severity=Severity.HIGH,
                evidence={"two_day_return_pct": str(two_day), "reduce_fraction": profit["two_day_reduce_fraction"]},
                suggested_action="至少减仓1/2",
            ))
        elif bool(position.get("exists")) and one_day >= _decimal(profit["single_day_return_pct"], "single_day_return_pct"):
            results.append(self._result(
                "RULE_033A", "单日利润保护", "P4", RuleStatus.TRIGGERED,
                "REDUCE_THIRD", "单日涨幅达到利润保护阈值",
                severity=Severity.HIGH,
                evidence={"day_return_pct": str(one_day), "reduce_fraction": profit["single_day_reduce_fraction"]},
                suggested_action="至少减仓1/3",
            ))
        if not option:
            return results
        dte = option.get("dte")
        if dte is None:
            results.append(self._result(
                "R-OPTION-01", "期权到期日", "P4", RuleStatus.UNKNOWN,
                "OPTION_DTE_MISSING", "期权DTE缺失", severity=Severity.CRITICAL,
                suggested_action="选择覆盖策略与催化剂的到期日",
            ))
        else:
            valid_dte = int(dte) >= int(config["normal_long_call_min_dte"])
            results.append(self._result(
                "R-OPTION-01", "普通Long Call最低DTE", "P4",
                RuleStatus.PASS if valid_dte else RuleStatus.BLOCK,
                "OPTION_DTE_OK" if valid_dte else "OPTION_DTE_TOO_SHORT",
                "期权DTE满足最低要求" if valid_dte else "普通Long Call的DTE少于60天",
                severity=Severity.HIGH if not valid_dte else Severity.INFO,
                evidence={"dte": int(dte), "minimum": int(config["normal_long_call_min_dte"])},
                suggested_action=None if valid_dte else "选择DTE不少于60天的合约",
            ))
        deep_otm = option.get("deep_otm")
        if deep_otm is None:
            results.append(self._result(
                "R-OPTION-03", "深度虚值检查", "P4", RuleStatus.UNKNOWN,
                "MONEYNESS_UNKNOWN", "无法判断是否深度虚值",
                severity=Severity.HIGH, suggested_action="补充正股、行权价和Delta",
            ))
        else:
            results.append(self._result(
                "R-OPTION-03", "深度虚值检查", "P4",
                RuleStatus.BLOCK if bool(deep_otm) else RuleStatus.PASS,
                "DEEP_OTM" if bool(deep_otm) else "MONEYNESS_OK",
                "不允许深度虚值合约" if bool(deep_otm) else "合约虚实值程度通过",
                severity=Severity.HIGH if bool(deep_otm) else Severity.INFO,
                suggested_action="选择更接近平值或实值的合约" if bool(deep_otm) else None,
            ))
        spread = option.get("spread_pct")
        if spread is None:
            results.append(self._result(
                "R-OPTION-04", "期权价差", "P4", RuleStatus.UNKNOWN,
                "OPTION_SPREAD_UNKNOWN", "期权买卖价差缺失",
                severity=Severity.HIGH, suggested_action="取得有效Bid/Ask",
            ))
        else:
            spread_value = _decimal(spread, "option.spread_pct")
            maximum = _decimal(config["max_bid_ask_spread_pct"], "max_bid_ask_spread_pct")
            results.append(self._result(
                "R-OPTION-04", "期权价差", "P4",
                RuleStatus.BLOCK if spread_value > maximum else RuleStatus.PASS,
                "OPTION_SPREAD_TOO_WIDE" if spread_value > maximum else "OPTION_SPREAD_OK",
                "期权买卖价差过大" if spread_value > maximum else "期权买卖价差通过",
                severity=Severity.HIGH if spread_value > maximum else Severity.INFO,
                evidence={"spread_pct": str(spread_value), "maximum_pct": str(maximum)},
                suggested_action="更换流动性更好的合约" if spread_value > maximum else None,
            ))
        return results

    def _strategy_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        strategy = context.get("strategy") or {}
        strategy_type = str(strategy.get("type") or "UNKNOWN")
        results: list[RuleResult] = []
        age = context.get("recommendation_age_hours")
        if age is not None:
            minimum = int(self.config["cooling"]["external_recommendation_hours"])
            cooled = int(age) >= minimum
            results.append(self._result(
                "R-COOLING-01", "外部推荐冷静期", "P5",
                RuleStatus.PASS if cooled else RuleStatus.BLOCK,
                "COOLING_COMPLETE" if cooled else "COOLING_PERIOD_ACTIVE",
                "外部推荐已过冷静期" if cooled else "外部推荐不足48小时",
                severity=Severity.HIGH if not cooled else Severity.INFO,
                evidence={"age_hours": int(age), "minimum_hours": minimum},
                suggested_action=None if cooled else "等待冷静期结束后重新评估",
            ))
        regime = str(_nested(context, "market.regime", "UNKNOWN"))
        long_call = str(_nested(context, "option.side", "LONG_CALL")) == "LONG_CALL"
        blocked_market = long_call and regime in {"DOWNTREND", "UNKNOWN"}
        results.append(self._result(
            "R-MARKET-01", "市场状态适配", "P5",
            RuleStatus.BLOCK if blocked_market else RuleStatus.PASS,
            "MARKET_BLOCKS_LONG_CALL" if blocked_market else "MARKET_STRATEGY_OK",
            "当前市场状态不允许普通Long Call" if blocked_market else "市场状态允许继续评估",
            severity=Severity.HIGH if blocked_market else Severity.INFO,
            evidence={"regime": regime},
            suggested_action="等待市场状态改善" if blocked_market else None,
        ))
        close, sma50 = strategy.get("close"), strategy.get("sma50")
        if strategy_type == "TREND_PULLBACK":
            if close is None or sma50 is None:
                results.append(self._result(
                    "RULE_032", "趋势策略50日均线", "P5", RuleStatus.UNKNOWN,
                    "SMA50_DATA_MISSING", "趋势策略缺少收盘价或50日均线",
                    severity=Severity.HIGH, suggested_action="补齐收盘价和50日均线",
                ))
            else:
                above = _decimal(close, "strategy.close") > _decimal(sma50, "strategy.sma50")
                results.append(self._result(
                    "RULE_032", "趋势策略50日均线", "P5",
                    RuleStatus.PASS if above else RuleStatus.BLOCK,
                    "ABOVE_SMA50" if above else "BELOW_SMA50",
                    "股价位于50日均线上方" if above else "趋势回踩策略不允许在50日均线下方买入Call",
                    severity=Severity.HIGH if not above else Severity.INFO,
                    evidence={"close": str(close), "sma50": str(sma50)},
                    suggested_action=None if above else "等待重新站上50日均线",
                ))
        return results

    def _entry_rules(self, context: dict[str, Any]) -> list[RuleResult]:
        confirmed = _nested(context, "strategy.trigger_confirmed")
        if confirmed is None:
            return [self._result(
                "R-ENTRY-01", "入场触发", "P6", RuleStatus.UNKNOWN,
                "ENTRY_TRIGGER_UNKNOWN", "入场触发数据不足",
                severity=Severity.MEDIUM, suggested_action="等待止跌或趋势确认",
            )]
        return [self._result(
            "R-ENTRY-01", "入场触发", "P6",
            RuleStatus.PASS if bool(confirmed) else RuleStatus.WARN,
            "ENTRY_TRIGGER_CONFIRMED" if bool(confirmed) else "ENTRY_TRIGGER_NOT_READY",
            "入场触发已确认" if bool(confirmed) else "价格便宜但尚未形成入场触发",
            severity=Severity.MEDIUM if not confirmed else Severity.INFO,
            suggested_action=None if confirmed else "等待两天不创新低并收复前一日高点",
        )]

    @staticmethod
    def _score(context: dict[str, Any]) -> int:
        components = context.get("score_components") or {}
        caps = {
            "market": 15, "sector": 10, "thesis": 20, "catalyst": 15,
            "price": 15, "entry": 10, "option": 10, "portfolio": 5,
        }
        total = 0
        for key, cap in caps.items():
            value = components.get(key, 0)
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = 0
            total += min(cap, max(0, number))
        return min(100, max(0, total))

    def _account_risk_state(self, context: dict[str, Any], results: list[RuleResult]) -> str:
        if any(item.rule_id == "R-ACCOUNT-01" and item.status == RuleStatus.TRIGGERED for item in results):
            return "FROZEN"
        account = context.get("account") or {}
        if account.get("equity") is None or account.get("planned_open_risk") is None:
            return "UNKNOWN"
        equity = _decimal(account["equity"], "account.equity")
        ratio = _decimal(account["planned_open_risk"], "planned_open_risk") / equity * Decimal("100")
        maximum = _decimal(self.config["risk"]["max_total_open_risk_pct"], "max_total_open_risk_pct")
        if ratio >= maximum * Decimal("0.9"):
            return "DEFENSIVE"
        if ratio >= maximum * Decimal("0.7"):
            return "REDUCED"
        return "NORMAL"

    def _position_size(self, context: dict[str, Any], results: list[RuleResult]) -> int:
        if any(item.status in {RuleStatus.BLOCK, RuleStatus.UNKNOWN, RuleStatus.TRIGGERED} for item in results):
            return 0
        account = context.get("account") or {}
        option = context.get("option") or {}
        if account.get("equity") is None or option.get("planned_risk_per_contract") is None:
            return 0
        equity = _decimal(account["equity"], "account.equity")
        per_contract = _decimal(option["planned_risk_per_contract"], "planned_risk_per_contract")
        if per_contract <= 0:
            return 0
        allowed = equity * _decimal(self.config["risk"]["risk_per_trade_pct"], "risk_per_trade_pct") / Decimal("100")
        base = (allowed / per_contract).to_integral_value(rounding=ROUND_FLOOR)
        regime = str(_nested(context, "market.regime", "UNKNOWN"))
        multiplier = _decimal(self.config["market_multipliers"].get(regime, "0"), "market_multiplier")
        for path in ("multipliers.strategy", "multipliers.theme", "multipliers.event"):
            multiplier *= _decimal(_nested(context, path, "1"), path)
        sized = int((base * multiplier).to_integral_value(rounding=ROUND_FLOOR))
        contract_cost = _decimal(option.get("contract_cost", per_contract), "option.contract_cost")
        max_position_value = equity * _decimal(self.config["risk"]["max_position_market_value_pct"], "max_position_market_value_pct") / Decimal("100")
        value_cap = int((max_position_value / contract_cost).to_integral_value(rounding=ROUND_FLOOR)) if contract_cost > 0 else 0
        return max(0, min(sized, value_cap))

    def _map_action(
        self,
        context: dict[str, Any],
        results: list[RuleResult],
        score: int,
        max_contracts: int,
    ) -> tuple[DecisionAction, Decimal | None]:
        if any(item.reason_code == "THESIS_INVALIDATED" for item in results):
            return DecisionAction.EXIT, None
        if any(item.reason_code == "DTE_EXIT" for item in results):
            return DecisionAction.EXIT, None
        if any(item.reason_code == "REDUCE_HALF" for item in results):
            return DecisionAction.REDUCE, _decimal(
                self.config["profit_protection"]["two_day_reduce_fraction"], "two_day_reduce_fraction"
            )
        if any(item.reason_code == "REDUCE_THIRD" for item in results):
            return DecisionAction.REDUCE, _decimal(
                self.config["profit_protection"]["single_day_reduce_fraction"], "single_day_reduce_fraction"
            )
        if any(item.reason_code == "ACCOUNT_FROZEN" for item in results):
            return DecisionAction.FREEZE, None
        if any(item.status in {RuleStatus.BLOCK, RuleStatus.UNKNOWN} for item in results):
            return DecisionAction.BLOCKED, None
        trigger_ready = not any(item.reason_code == "ENTRY_TRIGGER_NOT_READY" for item in results)
        if not trigger_ready:
            return DecisionAction.WATCH, None
        mapping = self.config["score_mapping"]
        if score < int(mapping["watch_below"]):
            return DecisionAction.WATCH, None
        if score < int(mapping["ready_below"]):
            return DecisionAction.READY, None
        if score < int(mapping["probe_below"]):
            return (DecisionAction.PROBE if max_contracts > 0 else DecisionAction.READY), None
        return (DecisionAction.STANDARD if max_contracts > 0 else DecisionAction.READY), None

