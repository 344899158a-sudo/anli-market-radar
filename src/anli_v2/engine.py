from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable


UTC = timezone.utc


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or isinstance(value, bool):
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _num(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _criterion(
    key: str,
    label: str,
    value: Any,
    predicate: Callable[[Any], bool],
    *,
    evidence: str,
    next_condition: str,
) -> dict[str, Any]:
    if value is None:
        status = "MISSING"
    else:
        try:
            status = "PASS" if predicate(value) else "BLOCK"
        except (TypeError, ValueError, InvalidOperation):
            status = "MISSING"
    return {
        "key": key,
        "label": label,
        "status": status,
        "evidence": evidence,
        "next_condition": next_condition,
    }


class DecisionEngineV2:
    """Multi-playbook decision engine. It never executes orders."""

    def __init__(
        self,
        rules_path: str | Path,
        driver_trees_path: str | Path,
    ) -> None:
        self.rules_path = Path(rules_path).resolve()
        self.rules = json.loads(self.rules_path.read_text(encoding="utf-8"))
        self.driver_trees = json.loads(
            Path(driver_trees_path).resolve().read_text(encoding="utf-8")
        )
        if self.rules.get("version") != "2.1.0":
            raise ValueError("ANLI 2.0 requires rules version 2.1.0")

    def build_dashboard(
        self,
        bundle: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=UTC)
        manifest = bundle["manifest"]
        envelopes = bundle["modules"]
        data = {name: envelope.get("data") for name, envelope in envelopes.items()}

        quality = self._data_quality(manifest, data, bundle.get("fetch") or {}, clock)
        overview = data.get("market-overview") or {}
        market_gate = self._market_gate(overview, quality)
        events = self._flatten_events(data.get("event-calendar") or {}, clock)
        watchlist = data.get("watchlist") or {}
        symbol_meta = {
            str(item.get("symbol") or "").upper(): item
            for item in watchlist.get("symbols") or []
            if isinstance(item, dict) and item.get("symbol")
        }

        decisions = []
        for raw in data.get("opportunities") or []:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol") or "").upper()
            decision = self._evaluate_symbol(
                raw,
                symbol_meta.get(symbol) or {},
                events,
                market_gate,
                quality,
                clock,
            )
            decisions.append(decision)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in decisions:
            grouped.setdefault(item["playbook"]["code"], []).append(item)
        for items in grouped.values():
            items.sort(
                key=lambda row: (
                    row["entry"]["state_priority"],
                    row["evidence_completion_pct"],
                    row.get("day_change_pct") or -999,
                ),
                reverse=True,
            )
            for index, row in enumerate(items, 1):
                row["rank_within_playbook"] = index

        qqq = self._qqq_summary(data.get("qqq-analysis") or {}, market_gate, quality)
        sector = self._sector_summary(data.get("sector-pulse") or {})
        counts_by_playbook = {
            code: len(items) for code, items in sorted(grouped.items())
        }
        counts_by_state: dict[str, int] = {}
        for item in decisions:
            state = item["entry"]["state"]
            counts_by_state[state] = counts_by_state.get(state, 0) + 1

        playbook_radar = self._playbook_radar(decisions, market_gate)
        command_brief = self._command_brief(
            decisions, market_gate, quality, qqq, sector
        )
        event_radar = self._event_radar(events, decisions)

        return {
            "schema_version": "2.0.0",
            "rule_version": self.rules["version"],
            "generated_at": clock.astimezone(UTC).isoformat(),
            "meta": {
                "snapshot_id": manifest.get("snapshot_id"),
                "source_schema_version": manifest.get("schema_version"),
                "source_rule_version": manifest.get("rule_version"),
                "as_of": manifest.get("as_of"),
                "source": manifest.get("source") or {},
                "source_quality": manifest.get("quality") or {},
                "fetch": bundle.get("fetch") or {},
                "automatic_ordering": False,
                "research_only": True,
            },
            "data_quality": quality,
            "market_gate": market_gate,
            "qqq": qqq,
            "sector": sector,
            "events": events,
            "command_brief": command_brief,
            "playbook_radar": playbook_radar,
            "event_radar": event_radar,
            "playbook_counts": counts_by_playbook,
            "state_counts": counts_by_state,
            "symbols": decisions,
            "sell_fact_rules": self._sell_fact_rules(),
            "methodology": {
                "ranking": "只在同一交易剧本内按证据完成度排序；不跨剧本使用统一总分。",
                "default": "NO_TRADE",
                "execution": "公开延时或静态快照只能形成研究候选；执行前必须用券商实时行情复核。",
                "ai": "AI 只能补充或下调证据等级，不能升级交易状态。",
            },
        }

    def _command_brief(
        self,
        decisions: list[dict[str, Any]],
        market_gate: dict[str, Any],
        quality: dict[str, Any],
        qqq: dict[str, Any],
        sector: dict[str, Any],
    ) -> dict[str, Any]:
        setup_ready = [item for item in decisions if item["entry"]["setup_ready"]]
        waiting = [
            item for item in decisions
            if item["entry"]["state"] in {"WAIT_TRIGGER", "BROKER_CONFIRMATION"}
        ]
        evidence_gaps = [
            item for item in decisions
            if item["entry"]["state"] == "EVIDENCE_INSUFFICIENT"
        ]
        constraint_counts: dict[str, dict[str, Any]] = {}
        for item in decisions:
            if item["playbook"]["code"] == "NO_TRADE":
                continue
            for criterion in item["criteria"]:
                if criterion["status"] not in {"BLOCK", "MISSING"}:
                    continue
                key = criterion["key"]
                bucket = constraint_counts.setdefault(
                    key,
                    {"label": criterion["label"], "count": 0, "missing": 0, "blocked": 0},
                )
                bucket["count"] += 1
                bucket["missing" if criterion["status"] == "MISSING" else "blocked"] += 1
        constraints = sorted(
            constraint_counts.values(),
            key=lambda item: (item["count"], item["missing"]),
            reverse=True,
        )
        dominant = constraints[0] if constraints else None

        if not quality["can_research"]:
            verdict = "数据阻断，保持现金"
            posture = "先恢复完整且未陈旧的数据快照；不生成研究升级。"
        elif market_gate["state"] == "RISK_OFF":
            verdict = "系统性风险优先"
            posture = "暂停新增风险，只管理已有仓位与核验反转条件。"
        elif market_gate["state"] == "SELECTIVE":
            verdict = "选择性等待，不追价格"
            posture = "只保留行业与个股相对强度最好的单一剧本，等待明确触发。"
        elif setup_ready:
            verdict = "环境允许，逐个剧本确认"
            posture = "研究条件已接近完整，但仍需按每只股票的触发位和券商实时行情复核。"
        else:
            verdict = "环境可研究，尚无完整触发"
            posture = "继续观察证据缺口与量价触发，不用总分替代必要条件。"

        market_status = (
            "PASS" if market_gate["state"] == "RISK_ON"
            else "CAUTION" if market_gate["state"] == "SELECTIVE"
            else "BLOCK"
        )
        qqq_status = "PASS" if qqq.get("setup_ready") else "CAUTION"
        sector_status = "PASS" if sector.get("state") in {"STRONG", "RISK_ON", "BULLISH"} else "CAUTION"
        symbol_status = "PASS" if setup_ready else "CAUTION" if waiting or evidence_gaps else "MISSING"
        return {
            "verdict": verdict,
            "posture": posture,
            "risk_cap_pct": market_gate["allocation_cap_pct"],
            "ready_count": len(setup_ready),
            "waiting_count": len(waiting),
            "evidence_gap_count": len(evidence_gaps),
            "dominant_constraint": dominant,
            "top_constraints": constraints[:3],
            "risk_budget": {
                "risk_per_trade_pct": self.rules["risk"]["research_risk_per_trade_pct"],
                "max_open_risk_pct": self.rules["risk"]["max_total_open_risk_pct"],
                "max_position_value_pct": self.rules["risk"]["max_position_market_value_pct"],
                "max_positions": self.rules["risk"]["max_positions"],
            },
            "stack": [
                {
                    "key": "data",
                    "label": "数据闸门",
                    "status": "PASS" if quality["can_research"] else "BLOCK",
                    "value": quality["status"],
                    "evidence": f"{quality['provider']} · {quality['latency']} · 截至 {quality['as_of']}",
                    "next_condition": "执行前仍需券商实时价格、成交量与点差确认。",
                },
                {
                    "key": "market",
                    "label": "大盘环境",
                    "status": market_status,
                    "value": market_gate["label"],
                    "evidence": f"{market_gate['regime_label']} · 风险上限 {market_gate['allocation_cap_pct']}%",
                    "next_condition": "；".join(market_gate["next_conditions"]),
                },
                {
                    "key": "qqq",
                    "label": "QQQ结构",
                    "status": qqq_status,
                    "value": qqq.get("decision_label") or "等待数据",
                    "evidence": qqq.get("reasoning", {}).get("summary") or "多周期证据不足",
                    "next_condition": qqq.get("next_condition") or "等待多周期共振",
                },
                {
                    "key": "sector",
                    "label": "行业领导力",
                    "status": sector_status,
                    "value": sector.get("label") or "数据不足",
                    "evidence": f"行业宽度 {sector.get('breadth_pct')}%；MA50宽度 {sector.get('above_ma50_pct')}%",
                    "next_condition": sector.get("action") or "等待行业ETF与领先股同步确认",
                },
                {
                    "key": "symbols",
                    "label": "个股触发",
                    "status": symbol_status,
                    "value": f"{len(setup_ready)} 只研究就绪 · {len(waiting)} 只等待触发",
                    "evidence": f"{len(evidence_gaps)} 只存在必要证据缺口",
                    "next_condition": dominant["label"] if dominant else "逐只按剧本核验触发与失效位",
                },
            ],
        }

    def _playbook_radar(
        self,
        decisions: list[dict[str, Any]],
        market_gate: dict[str, Any],
    ) -> dict[str, Any]:
        codes = [
            "LEADERSHIP_PULLBACK",
            "EXPECTATION_BUILD",
            "POST_EVENT_CONFIRMATION",
            "WASHOUT_RECOVERY",
        ]
        radar_rows = []
        for code in codes:
            items = [item for item in decisions if item["playbook"]["code"] == code]
            items.sort(
                key=lambda row: (
                    row["entry"]["state_priority"],
                    row["evidence_completion_pct"],
                ),
                reverse=True,
            )
            ready_count = sum(item["entry"]["setup_ready"] for item in items)
            wait_count = sum(item["entry"]["state"] == "WAIT_TRIGGER" for item in items)
            missing_count = sum(
                item["entry"]["state"] == "EVIDENCE_INSUFFICIENT" for item in items
            )
            blocked_count = sum(
                item["entry"]["state"] in {"DATA_BLOCKED", "MARKET_BLOCKED"}
                for item in items
            )
            bottlenecks: dict[str, dict[str, Any]] = {}
            for item in items:
                for criterion in item["criteria"]:
                    if criterion["status"] not in {"BLOCK", "MISSING"}:
                        continue
                    bucket = bottlenecks.setdefault(
                        criterion["key"],
                        {
                            "key": criterion["key"],
                            "label": criterion["label"],
                            "count": 0,
                            "missing": 0,
                            "blocked": 0,
                            "next_condition": criterion["next_condition"],
                        },
                    )
                    bucket["count"] += 1
                    bucket["missing" if criterion["status"] == "MISSING" else "blocked"] += 1
            ranked_bottlenecks = sorted(
                bottlenecks.values(),
                key=lambda item: (item["count"], item["missing"]),
                reverse=True,
            )
            if market_gate["state"] in {"BLOCKED", "RISK_OFF"}:
                state, state_label = "BLOCKED", "市场闸门阻断"
            elif ready_count:
                state, state_label = "READY", "研究条件就绪"
            elif wait_count:
                state, state_label = "FORMING", "正在形成触发"
            elif missing_count:
                state, state_label = "EVIDENCE_GAP", "关键证据缺失"
            elif items:
                state, state_label = "WATCH", "仅观察"
            else:
                state, state_label = "EMPTY", "暂无候选"
            cfg = self.rules["playbooks"][code]
            radar = cfg.get("radar") or {}
            radar_rows.append({
                "code": code,
                "label": cfg["label"],
                "state": state,
                "state_label": state_label,
                "candidate_count": len(items),
                "ready_count": ready_count,
                "wait_count": wait_count,
                "evidence_gap_count": missing_count,
                "blocked_count": blocked_count,
                "average_completion_pct": round(
                    sum(item["evidence_completion_pct"] for item in items) / len(items)
                ) if items else 0,
                "thesis": radar.get("thesis"),
                "market_fit": radar.get("market_fit"),
                "setup": radar.get("setup"),
                "trigger": radar.get("trigger"),
                "avoid": radar.get("avoid"),
                "exit": radar.get("exit"),
                "primary_bottleneck": ranked_bottlenecks[0] if ranked_bottlenecks else None,
                "bottlenecks": ranked_bottlenecks[:4],
                "leaders": [
                    {
                        "symbol": item["symbol"],
                        "name": item["name"],
                        "entry_state": item["entry"]["state"],
                        "entry_label": item["entry"]["label"],
                        "completion_pct": item["evidence_completion_pct"],
                        "next_action": item["next_best_action"],
                    }
                    for item in items[:4]
                ],
                "decision_path": [
                    {"step": 1, "label": "环境", "detail": radar.get("market_fit")},
                    {"step": 2, "label": "结构", "detail": radar.get("setup")},
                    {"step": 3, "label": "触发", "detail": radar.get("trigger")},
                    {"step": 4, "label": "失效", "detail": radar.get("avoid")},
                    {"step": 5, "label": "退出", "detail": radar.get("exit")},
                ],
            })
        return {
            "summary": {
                "active_playbooks": sum(row["candidate_count"] > 0 for row in radar_rows),
                "ready_playbooks": sum(row["state"] == "READY" for row in radar_rows),
                "forming_playbooks": sum(row["state"] == "FORMING" for row in radar_rows),
                "evidence_gap_playbooks": sum(row["state"] == "EVIDENCE_GAP" for row in radar_rows),
                "no_trade_count": sum(
                    item["playbook"]["code"] == "NO_TRADE" for item in decisions
                ),
            },
            "pipeline": ["市场闸门", "唯一剧本", "必要证据", "价格触发", "券商确认", "持仓管理"],
            "playbooks": radar_rows,
        }

    def _event_radar(
        self,
        events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        upcoming = [
            event for event in events
            if isinstance(event.get("days_to_event"), int) and event["days_to_event"] >= 0
        ]
        critical = [event for event in upcoming if int(event.get("importance") or 0) >= 4]
        next_event = min(upcoming, key=lambda item: item["days_to_event"]) if upcoming else None
        nearest = next_event.get("days_to_event") if next_event else None
        if nearest is None:
            policy = "没有已核验的未来事件；不因传闻建立预期仓。"
        elif nearest <= self.rules["event_lifecycle"]["pre_event_risk_days"]:
            policy = "已进入事前风险窗口：停止追买，优先保护利润并降低隔夜事件暴露。"
        elif nearest <= self.rules["event_lifecycle"]["expectation_build_max_days"]:
            policy = "处于买预期窗口：只交易预期上修与价格确认，不把事件日期本身当作利好。"
        else:
            policy = "处于催化发现期：建立观察清单，等待预期修订与价格结构出现。"
        phase_counts: dict[str, int] = {}
        for item in decisions:
            code = item["event_phase"]["code"]
            phase_counts[code] = phase_counts.get(code, 0) + 1
        return {
            "upcoming_count": len(upcoming),
            "critical_count": len(critical),
            "within_7d_count": sum(event["days_to_event"] <= 7 for event in upcoming),
            "verified_count": sum(bool(event.get("verified")) for event in upcoming),
            "next_event": next_event,
            "policy": policy,
            "phase_counts": phase_counts,
            "lifecycle": [
                {"code": "DISCOVERY", "label": "发现催化", "window": "31–45天", "action": "建立观察清单", "required": "官方日期与影响范围"},
                {"code": "EXPECTATION_BUILD", "label": "预期形成", "window": "7–30天", "action": "核验预期上修与定价差", "required": "一致预期、期权定价、趋势结构"},
                {"code": "PRE_EVENT_RISK", "label": "事前风控", "window": "1–5天", "action": "停止追买并保护利润", "required": "利润垫、仓位与隔夜风险"},
                {"code": "FACT_RELEASED", "label": "事实公布", "window": "0天", "action": "比较实际值与已定价预期", "required": "收入、利润率、KPI与指引"},
                {"code": "POST_EVENT_DISCOVERY", "label": "价格发现", "window": "1–3天后", "action": "观察事件VWAP与开盘区间", "required": "相对成交量与价格承接"},
                {"code": "POST_EVENT_TREND", "label": "事件趋势", "window": "4–20天后", "action": "保留或退出趋势仓", "required": "跟随、相对强度与预期修订"},
            ],
            "expectation_components": [
                {"label": "实际业绩惊喜", "question": "实际值相对一致预期高了多少？"},
                {"label": "指引变化", "question": "下一季与全年指引中点是否上调？"},
                {"label": "核心KPI质量", "question": "收入结构、毛利率、现金流和业务KPI是否同步改善？"},
                {"label": "事件前已定价涨幅", "question": "事件前价格已经提前上涨了多少？"},
                {"label": "期权隐含涨跌幅", "question": "实际价格反应是否超过事件前ATM定价？"},
                {"label": "拥挤度惩罚", "question": "高估值、高持仓与单边共识是否压缩赔率？"},
            ],
        }
    def _data_quality(
        self,
        manifest: dict[str, Any],
        modules: dict[str, Any],
        fetch: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        required = list(self.rules["data"]["required_modules"])
        missing = [name for name in required if name not in modules or modules[name] is None]
        as_of = _parse_time(manifest.get("as_of"))
        age_hours = None
        if as_of:
            age_hours = max(Decimal("0"), Decimal(str((now - as_of).total_seconds())) / Decimal("3600"))
        weekend = now.astimezone(UTC).weekday() >= 5
        max_age = _d(
            self.rules["data"][
                "max_weekend_age_hours" if weekend else "max_regular_age_hours"
            ]
        )
        issues: list[dict[str, Any]] = []
        if missing:
            issues.append({
                "severity": "CRITICAL",
                "code": "MISSING_CORE_MODULES",
                "message": "缺少核心模块：" + "、".join(missing),
            })
        if as_of is None:
            issues.append({
                "severity": "CRITICAL",
                "code": "INVALID_AS_OF",
                "message": "快照缺少可解析的 as_of 时间。",
            })
        elif age_hours is not None and age_hours > max_age:
            issues.append({
                "severity": "HIGH",
                "code": "STALE_SNAPSHOT",
                "message": f"快照已陈旧 {float(age_hours):.1f} 小时，超过 {max_age} 小时闸门。",
            })
        source = manifest.get("source") or {}
        official_realtime = bool(source.get("is_official_realtime"))
        if not official_realtime:
            issues.append({
                "severity": "HIGH",
                "code": "NOT_OFFICIAL_REALTIME",
                "message": "当前是公开近实时、延时或静态快照，不具备执行资格。",
            })
        if str((manifest.get("quality") or {}).get("status")) != "OK":
            issues.append({
                "severity": "MEDIUM",
                "code": "PARTIAL_SOURCE_QUALITY",
                "message": "上游快照质量不是完整 OK，必须保留证据缺口。",
            })
        if fetch.get("mode") == "last-known-good-cache":
            issues.append({
                "severity": "HIGH",
                "code": "CACHE_FALLBACK",
                "message": "在线刷新失败，当前展示最后一次有效缓存。",
            })

        blocked = bool(missing or as_of is None or (age_hours is not None and age_hours > max_age))
        status = "BLOCKED" if blocked else "PARTIAL" if issues else "READY"
        return {
            "status": status,
            "can_research": not blocked,
            "execution_ready": not blocked and official_realtime and source.get("session") == "REGULAR",
            "as_of": manifest.get("as_of"),
            "age_hours": round(float(age_hours), 2) if age_hours is not None else None,
            "max_age_hours": str(max_age),
            "weekend_tolerance": weekend,
            "provider": source.get("provider") or "未知来源",
            "feed": source.get("feed") or "unknown",
            "latency": source.get("latency") or "unknown",
            "session": source.get("session") or "UNKNOWN",
            "official_realtime": official_realtime,
            "missing_modules": missing,
            "issues": issues,
        }

    def _market_gate(
        self,
        overview: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        regime = str(overview.get("regime") or "UNKNOWN")
        breadth = overview.get("breadth") or {}
        breadth50 = _num(breadth.get("above_ma50_pct"))
        assets = overview.get("assets") or {}
        qqq = assets.get("QQQ") or {}
        spy = assets.get("SPY") or {}
        tnx = assets.get("^TNX") or {}
        vix = assets.get("^VIX") or {}
        selective_cut = _d(self.rules["market_gate"]["selective_breadth_ma50_pct"])
        risk_off_cut = _d(self.rules["market_gate"]["risk_off_breadth_ma50_pct"])
        rate_pressure_cut = _d(self.rules["market_gate"]["rate_pressure_day_change_pct"])
        breadth_value = _d(breadth50) if breadth50 is not None else None
        qqq_above = qqq.get("above_ma50")
        spy_above = spy.get("above_ma50")
        rate_change = _num(tnx.get("day_change_pct"))
        rate_pressure = rate_change is not None and _d(rate_change) >= rate_pressure_cut

        if not quality["can_research"]:
            state, label = "BLOCKED", "数据闸门阻断"
        elif regime == "DOWNTREND" or (breadth_value is not None and breadth_value < risk_off_cut):
            state, label = "RISK_OFF", "风险关闭"
        elif (
            breadth_value is None
            or breadth_value < selective_cut
            or qqq_above is not True
            or rate_pressure
        ):
            state, label = "SELECTIVE", "选择性交易"
        else:
            state, label = "RISK_ON", "风险可开"

        cap = self.rules["market_gate"]["regime_exposure_cap_pct"].get(regime, "0")
        if state in {"BLOCKED", "RISK_OFF"}:
            cap = "0"
        evidence = [
            {
                "label": "市场状态",
                "value": overview.get("regime_label") or regime,
                "status": "PASS" if state == "RISK_ON" else "CAUTION",
            },
            {
                "label": "MA50宽度",
                "value": breadth50,
                "unit": "%",
                "status": "PASS" if breadth_value is not None and breadth_value >= selective_cut else "BLOCK",
            },
            {
                "label": "QQQ / MA50",
                "value": qqq.get("distance_ma50_pct"),
                "unit": "%",
                "status": "PASS" if qqq_above is True else "BLOCK" if qqq_above is False else "MISSING",
            },
            {
                "label": "SPY / MA50",
                "value": spy.get("distance_ma50_pct"),
                "unit": "%",
                "status": "PASS" if spy_above is True else "BLOCK" if spy_above is False else "MISSING",
            },
            {
                "label": "10Y日变化",
                "value": rate_change,
                "unit": "%",
                "status": "CAUTION" if rate_pressure else "PASS" if rate_change is not None else "MISSING",
            },
            {
                "label": "VIX",
                "value": vix.get("price"),
                "status": "PASS" if vix.get("price") is not None else "MISSING",
            },
        ]
        next_conditions = []
        if breadth_value is None or breadth_value < selective_cut:
            next_conditions.append(f"观察池站上MA50比例恢复到 {selective_cut}% 以上")
        if qqq_above is not True:
            next_conditions.append("QQQ重新站上MA50并由日线/4小时共同确认")
        if rate_pressure:
            next_conditions.append("长端利率压力缓解，不再对成长估值形成逆风")
        if not next_conditions:
            next_conditions.append("维持行业与个股相对强度，并等待具体剧本触发")

        return {
            "state": state,
            "label": label,
            "regime": regime,
            "regime_label": overview.get("regime_label") or regime,
            "market_score": overview.get("score"),
            "position_label": overview.get("position_label"),
            "allocation_cap_pct": str(cap),
            "can_open_new_risk": state in {"RISK_ON", "SELECTIVE"} and quality["can_research"],
            "execution_ready": quality["execution_ready"] and state in {"RISK_ON", "SELECTIVE"},
            "action": overview.get("action") or "等待可验证市场数据",
            "evidence": evidence,
            "next_conditions": next_conditions,
            "breadth": breadth,
            "assets": {
                key: assets.get(key)
                for key in ("SPY", "QQQ", "RSP", "IWM", "DIA", "^VIX", "^TNX", "DX-Y.NYB")
                if assets.get(key) is not None
            },
        }

    @staticmethod
    def _flatten_events(calendar: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for week in calendar.get("weeks") or []:
            for raw in week.get("events") or []:
                event = dict(raw)
                at = _parse_time(event.get("at_cn") or event.get("at"))
                if at:
                    days = (at.date() - now.astimezone(at.tzinfo).date()).days
                else:
                    days = None
                event["days_to_event"] = days
                event["week_label"] = week.get("label")
                event["week_risk_label"] = week.get("risk_label")
                event["verified"] = "确认" in str(event.get("verification") or "")
                result.append(event)
        result.sort(key=lambda item: item.get("at_cn") or item.get("at") or "")
        return result

    def _event_phase(self, days: int | None) -> dict[str, Any]:
        life = self.rules["event_lifecycle"]
        if days is None:
            return {"code": "NO_VERIFIED_EVENT", "label": "没有已核验事件", "step": 0}
        if days > life["expectation_build_max_days"]:
            return {"code": "DISCOVERY", "label": "发现催化剂", "step": 1}
        if life["expectation_build_min_days"] <= days <= life["expectation_build_max_days"]:
            return {"code": "EXPECTATION_BUILD", "label": "预期形成", "step": 2}
        if 1 <= days <= life["pre_event_risk_days"]:
            return {"code": "PRE_EVENT_RISK", "label": "事件前风险期", "step": 3}
        if days == 0:
            return {"code": "FACT_RELEASED", "label": "事实公布", "step": 4}
        if -life["post_discovery_days"] <= days < 0:
            return {"code": "POST_EVENT_DISCOVERY", "label": "价格发现", "step": 5}
        if -life["post_trend_days"] <= days < -life["post_discovery_days"]:
            return {"code": "POST_EVENT_TREND", "label": "事件后趋势", "step": 6}
        return {"code": "INACTIVE", "label": "事件窗口外", "step": 0}

    @staticmethod
    def _matching_event(symbol: str, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = []
        for event in events:
            scope = {str(value).upper() for value in event.get("scope") or []}
            days = event.get("days_to_event")
            if symbol in scope and isinstance(days, int) and -20 <= days <= 45:
                candidates.append(event)
        if not candidates:
            return None
        return min(candidates, key=lambda event: (abs(event["days_to_event"]), -int(event.get("importance") or 0)))

    def _evaluate_symbol(
        self,
        raw: dict[str, Any],
        meta: dict[str, Any],
        events: list[dict[str, Any]],
        market_gate: dict[str, Any],
        quality: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        symbol = str(raw.get("symbol") or "").upper()
        event = self._matching_event(symbol, events)
        if event is None and raw.get("catalyst_date"):
            try:
                event_date = datetime.fromisoformat(str(raw["catalyst_date"]) + "T00:00:00+00:00")
                days = (event_date.date() - now.date()).days
            except ValueError:
                days = None
            event = {
                "title": "未核验公司催化剂",
                "at": raw.get("catalyst_date"),
                "days_to_event": days,
                "verification": "未核验",
                "verified": False,
                "source": None,
                "source_url": None,
                "scope": [symbol],
            }
        phase = self._event_phase(event.get("days_to_event") if event else None)
        playbook_code = self._select_playbook(raw, event, phase)
        playbook_label = self.rules["playbooks"][playbook_code]["label"]
        criteria = self._playbook_criteria(playbook_code, raw, event, phase)
        missing_count = sum(item["status"] == "MISSING" for item in criteria)
        blocked_count = sum(item["status"] == "BLOCK" for item in criteria)
        passed_count = sum(item["status"] == "PASS" for item in criteria)
        total = len(criteria)
        completion = round(passed_count / total * 100) if total else 0
        entry = self._entry_state(
            playbook_code,
            phase,
            missing_count,
            blocked_count,
            market_gate,
            quality,
        )
        driver_tree = self._driver_tree(str(raw.get("sector") or ""))
        plan = self._plan(playbook_code, raw, phase)
        focus = self._symbol_focus(
            playbook_code, phase, criteria, entry, plan, market_gate, quality
        )

        return {
            "symbol": symbol,
            "name": raw.get("name") or meta.get("name") or symbol,
            "sector": raw.get("sector") or meta.get("sector") or "未分组",
            "sector_benchmark": raw.get("sector_benchmark"),
            "price": raw.get("price"),
            "quote_time": raw.get("quote_time"),
            "day_change_pct": raw.get("day_change_pct"),
            "distance_ma50_pct": raw.get("distance_ma50_pct"),
            "drawdown20_pct": raw.get("drawdown20_pct"),
            "ma50": raw.get("ma50"),
            "rsi14": raw.get("rsi14"),
            "volume_ratio": raw.get("volume_ratio"),
            "playbook": {
                "code": playbook_code,
                "label": playbook_label,
                "why": self._playbook_reason(playbook_code, raw, event),
            },
            "event": event,
            "event_phase": phase,
            "entry": entry,
            "criteria": criteria,
            "evidence_completion_pct": completion,
            "evidence_summary": {
                "passed": passed_count,
                "blocked": blocked_count,
                "missing": missing_count,
                "total": total,
                "label": "规则证据完成度，不是胜率",
            },
            "expectation_gap": self._expectation_gap(event),
            "plan": plan,
            "primary_constraint": focus["primary_constraint"],
            "next_best_action": focus["next_best_action"],
            "decision_stack": focus["decision_stack"],
            "driver_tree": driver_tree,
            "source_status": raw.get("status"),
            "legacy_score_reference_only": raw.get("score"),
            "rank_within_playbook": None,
        }

    @staticmethod
    def _symbol_focus(
        playbook: str,
        phase: dict[str, Any],
        criteria: list[dict[str, Any]],
        entry: dict[str, Any],
        plan: dict[str, Any],
        market_gate: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        unresolved = [item for item in criteria if item["status"] in {"MISSING", "BLOCK"}]
        unresolved.sort(key=lambda item: 0 if item["status"] == "MISSING" else 1)
        primary = unresolved[0] if unresolved else None
        state = entry["state"]
        if state == "DATA_BLOCKED":
            next_action = "等待数据恢复并重新生成不可变快照。"
        elif state == "MARKET_BLOCKED":
            next_action = "不新增风险；等待大盘闸门恢复。"
        elif state == "PRE_EVENT_RISK":
            next_action = "停止追买，核对利润垫并降低事件暴露。"
        elif state == "NO_TRADE":
            next_action = "等待进入一套定义清楚的高质量剧本。"
        elif primary:
            next_action = primary["next_condition"]
        elif state == "BROKER_CONFIRMATION":
            next_action = "用券商实时价格、成交量、点差和事件状态复核触发。"
        else:
            next_action = plan["entry_trigger"]

        evidence_status = (
            "PASS" if criteria and not unresolved
            else "MISSING" if any(item["status"] == "MISSING" for item in criteria)
            else "BLOCK" if unresolved
            else "CAUTION"
        )
        execution_status = "PASS" if entry["can_act"] else "BLOCK"
        return {
            "primary_constraint": primary,
            "next_best_action": next_action,
            "decision_stack": [
                {
                    "label": "数据",
                    "status": "PASS" if quality["can_research"] else "BLOCK",
                    "value": quality["status"],
                    "detail": "研究快照可读" if quality["can_research"] else "数据质量阻断",
                },
                {
                    "label": "大盘",
                    "status": "PASS" if market_gate["state"] == "RISK_ON" else "CAUTION" if market_gate["state"] == "SELECTIVE" else "BLOCK",
                    "value": market_gate["label"],
                    "detail": f"模型风险上限 {market_gate['allocation_cap_pct']}%",
                },
                {
                    "label": "剧本",
                    "status": "PASS" if playbook != "NO_TRADE" else "BLOCK",
                    "value": playbook,
                    "detail": phase["label"],
                },
                {
                    "label": "证据",
                    "status": evidence_status,
                    "value": f"{sum(item['status'] == 'PASS' for item in criteria)}/{len(criteria)} 通过",
                    "detail": primary["label"] if primary else "必要条件已完整" if criteria else "没有有效剧本",
                },
                {
                    "label": "执行",
                    "status": execution_status,
                    "value": entry["label"],
                    "detail": "允许按预案执行" if entry["can_act"] else "公开快照不能直接执行",
                },
            ],
        }
    def _select_playbook(
        self,
        raw: dict[str, Any],
        event: dict[str, Any] | None,
        phase: dict[str, Any],
    ) -> str:
        # Priority is protective: post-event discovery > washout > pre-event > trend pullback.
        verified = bool(event and event.get("verified"))
        if verified and phase["code"] in {"FACT_RELEASED", "POST_EVENT_DISCOVERY"}:
            return "POST_EVENT_CONFIRMATION"
        washout = self.rules["playbooks"]["WASHOUT_RECOVERY"]
        day_change = _num(raw.get("day_change_pct"))
        drawdown = _num(raw.get("drawdown20_pct"))
        if (
            day_change is not None
            and _d(day_change) <= _d(washout["max_day_change_pct"])
        ) or (
            drawdown is not None
            and _d(drawdown) <= _d(washout["max_drawdown20_pct"])
        ):
            return "WASHOUT_RECOVERY"
        if verified and phase["code"] in {"EXPECTATION_BUILD", "PRE_EVENT_RISK"}:
            return "EXPECTATION_BUILD"
        leader = self.rules["playbooks"]["LEADERSHIP_PULLBACK"]
        checks = raw.get("checks") or {}
        if (
            checks.get("above_ma50") is True
            and checks.get("quality") is True
            and drawdown is not None
            and _d(leader["drawdown_min_pct"]) <= _d(drawdown) <= _d(leader["drawdown_max_pct"])
        ):
            return "LEADERSHIP_PULLBACK"
        return "NO_TRADE"

    def _playbook_criteria(
        self,
        code: str,
        raw: dict[str, Any],
        event: dict[str, Any] | None,
        phase: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks = raw.get("checks") or {}
        industry = checks.get("industry")
        quality = checks.get("quality")
        above = checks.get("above_ma50")
        stable = checks.get("stabilized")
        not_chasing = checks.get("not_chasing")
        drawdown = _num(raw.get("drawdown20_pct"))
        rsi = _num(raw.get("rsi14"))
        volume = _num(raw.get("volume_ratio"))
        distance = _num(raw.get("distance_ma50_pct"))
        common_quality = _criterion(
            "quality",
            "公司质地可追溯",
            quality,
            lambda value: value is True,
            evidence=f"旧快照质地闸门：{quality}",
            next_condition="补齐SEC、公司IR或人工预审证据",
        )

        if code == "LEADERSHIP_PULLBACK":
            cfg = self.rules["playbooks"][code]
            return [
                common_quality,
                _criterion("industry", "行业趋势确认", industry, lambda value: value is True, evidence=f"行业闸门：{industry}", next_condition="等待行业ETF重新站上上升MA50"),
                _criterion("above_ma50", "个股位于MA50上方", above, lambda value: value is True, evidence=f"距MA50：{distance}%", next_condition="等待价格收复MA50"),
                _criterion("pullback", "回踩位于剧本区间", drawdown, lambda value: _d(cfg["drawdown_min_pct"]) <= _d(value) <= _d(cfg["drawdown_max_pct"]), evidence=f"20日高点回撤：{drawdown}%", next_condition=f"等待回撤进入 {cfg['drawdown_min_pct']}% 至 {cfg['drawdown_max_pct']}% 区间"),
                _criterion("rsi", "动量未过热", rsi, lambda value: _d(value) <= _d(cfg["max_rsi14"]), evidence=f"RSI14：{rsi}", next_condition="等待RSI降温"),
                _criterion("volume", "触发日成交量确认", volume, lambda value: _d(value) >= _d(cfg["confirm_volume_ratio"]), evidence=f"量比：{volume}", next_condition=f"等待量比达到 {cfg['confirm_volume_ratio']} 以上并收复关键位置"),
            ]
        if code == "EXPECTATION_BUILD":
            cfg = self.rules["playbooks"][code]
            days = event.get("days_to_event") if event else None
            verified = event.get("verified") if event else None
            return [
                common_quality,
                _criterion("event", "催化剂由官方来源确认", verified, lambda value: value is True, evidence=(event or {}).get("verification") or "无事件证据", next_condition="由公司IR或官方日历核验事件日期"),
                _criterion("window", "处于买预期窗口", days, lambda value: cfg["min_event_days"] <= int(value) <= cfg["max_event_days"], evidence=f"距事件：{days}天；阶段：{phase['label']}", next_condition=f"只在事件前 {cfg['min_event_days']}–{cfg['max_event_days']} 天进入买预期评估"),
                _criterion("industry", "行业趋势确认", industry, lambda value: value is True, evidence=f"行业闸门：{industry}", next_condition="等待行业ETF确认"),
                _criterion("above_ma50", "个股位于MA50上方", above, lambda value: value is True, evidence=f"距MA50：{distance}%", next_condition="等待价格收复MA50"),
                _criterion("extension", "没有过度延伸", distance, lambda value: _d(value) <= _d(cfg["max_distance_ma50_pct"]), evidence=f"距MA50：{distance}%", next_condition="等待价格回到可控的趋势距离"),
                _criterion("not_chasing", "没有追涨", not_chasing, lambda value: value is True, evidence=f"旧快照追涨闸门：{not_chasing}", next_condition="等待跳空与日内涨幅冷却"),
                _criterion("revision", "盈利预期持续上修", None, lambda value: value is True, evidence="公开快照未提供一致预期修订", next_condition="接入合规一致预期、修订广度与离散度数据"),
                _criterion("options", "期权没有过度定价", None, lambda value: value is True, evidence="公开快照未提供隐含波动与隐含涨跌幅", next_condition="接入OPRA/券商期权隐含波动、期限结构与偏度"),
            ]
        if code == "POST_EVENT_CONFIRMATION":
            verified = event.get("verified") if event else None
            return [
                common_quality,
                _criterion("event", "事实发布日期已核验", verified, lambda value: value is True, evidence=(event or {}).get("verification") or "无事件证据", next_condition="核验公司IR发布日期"),
                _criterion("actual", "收入、利润率与核心KPI超过预期", None, lambda value: value is True, evidence="尚未接入结构化实际值与一致预期比较", next_condition="读取公司IR、10-Q/8-K与合规一致预期"),
                _criterion("guidance", "管理层上调指引", None, lambda value: value is True, evidence="尚未取得已核验指引变化", next_condition="核对下一季度及全年指引中点"),
                _criterion("implied_move", "价格表现超过隐含波动", None, lambda value: value is True, evidence="缺少事件前期权隐含涨跌幅", next_condition="比较实际跳空与事件前ATM跨式隐含涨跌幅"),
                _criterion("avwap", "守住开盘区间与事件VWAP", None, lambda value: value is True, evidence="静态日线不能确认盘中事件VWAP", next_condition="等待开盘15–60分钟并用券商实时K线确认"),
                _criterion("relative_volume", "相对成交量确认", volume, lambda value: _d(value) >= _d(self.rules["playbooks"][code]["min_relative_volume"]), evidence=f"当前量比：{volume}", next_condition="等待相对成交量达到事件剧本阈值"),
            ]
        if code == "WASHOUT_RECOVERY":
            cfg = self.rules["playbooks"][code]
            event_explained = None
            return [
                common_quality,
                _criterion("washout", "下跌达到超跌阈值", (raw.get("day_change_pct"), raw.get("drawdown20_pct")), lambda value: _d(value[0], "999") <= _d(cfg["max_day_change_pct"]) or _d(value[1], "999") <= _d(cfg["max_drawdown20_pct"]), evidence=f"日变动 {raw.get('day_change_pct')}%；20日回撤 {raw.get('drawdown20_pct')}%", next_condition="等待形成足够的风险释放幅度"),
                _criterion("stabilized", "等待2–3个完整交易日企稳", stable, lambda value: value is True, evidence=f"旧快照企稳闸门：{stable}", next_condition=f"至少等待 {cfg['stabilization_sessions']} 个完整交易日不再创新低"),
                _criterion("industry", "行业停止下跌", industry, lambda value: value is True, evidence=f"行业闸门：{industry}", next_condition="等待行业ETF停止创新低并收复短期趋势"),
                _criterion("cause", "下跌原因与基本面逻辑已核验", event_explained, lambda value: value is True, evidence="公开快照没有可验证的事件解释与基本面复核", next_condition="核验公司IR、SEC与可靠新闻原文，确认原逻辑是否仍成立"),
                _criterion("reclaim", "收复事件VWAP或20EMA", None, lambda value: value is True, evidence="静态快照缺少事件锚定VWAP确认", next_condition="使用券商实时K线确认更高低点与关键位置收复"),
            ]
        return []

    @staticmethod
    def _entry_state(
        playbook: str,
        phase: dict[str, Any],
        missing_count: int,
        blocked_count: int,
        market_gate: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        if not quality["can_research"]:
            state, label, priority = "DATA_BLOCKED", "数据阻断", 0
        elif market_gate["state"] in {"BLOCKED", "RISK_OFF"}:
            state, label, priority = "MARKET_BLOCKED", "大盘阻断", 1
        elif playbook == "NO_TRADE":
            state, label, priority = "NO_TRADE", "无有效剧本", 2
        elif phase["code"] == "PRE_EVENT_RISK":
            state, label, priority = "PRE_EVENT_RISK", "事件前只减不加", 3
        elif missing_count:
            state, label, priority = "EVIDENCE_INSUFFICIENT", "证据不足", 4
        elif blocked_count:
            state, label, priority = "WAIT_TRIGGER", "等待触发", 5
        elif not quality["execution_ready"]:
            state, label, priority = "BROKER_CONFIRMATION", "研究就绪·待券商确认", 6
        else:
            state, label, priority = "ENTRY_READY", "条件触发", 7
        return {
            "state": state,
            "label": label,
            "state_priority": priority,
            "setup_ready": state in {"BROKER_CONFIRMATION", "ENTRY_READY"},
            "can_act": state == "ENTRY_READY" and market_gate["execution_ready"],
            "automatic_ordering": False,
        }

    @staticmethod
    def _playbook_reason(code: str, raw: dict[str, Any], event: dict[str, Any] | None) -> str:
        if code == "POST_EVENT_CONFIRMATION":
            return "已进入事实公布后的价格发现窗口，必须比较实际结果、指引、隐含涨跌幅和盘中承接。"
        if code == "WASHOUT_RECOVERY":
            return f"日变动 {raw.get('day_change_pct')}%，20日回撤 {raw.get('drawdown20_pct')}%，风险释放优先级高于事件预期。"
        if code == "EXPECTATION_BUILD":
            return f"已核验事件“{(event or {}).get('title')}”临近，进入预期与定价差评估。"
        if code == "LEADERSHIP_PULLBACK":
            return "个股仍在MA50上方且回撤进入趋势回踩区间，等待量价触发。"
        return "当前结构不属于任何已定义高质量剧本，默认不交易。"

    @staticmethod
    def _expectation_gap(event: dict[str, Any] | None) -> dict[str, Any]:
        components = [
            {"key": "actual_surprise", "label": "实际业绩惊喜", "value": None, "status": "MISSING"},
            {"key": "guidance_revision", "label": "指引变化", "value": None, "status": "MISSING"},
            {"key": "kpi_quality", "label": "核心KPI质量", "value": None, "status": "MISSING"},
            {"key": "pre_event_runup", "label": "事件前已定价涨幅", "value": None, "status": "MISSING"},
            {"key": "implied_move", "label": "期权隐含涨跌幅", "value": None, "status": "MISSING"},
            {"key": "crowding", "label": "拥挤度惩罚", "value": None, "status": "MISSING"},
        ]
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "label": "预期差证据不足",
            "formula": "基本面惊喜 + 指引与KPI - 事件前涨幅 - 隐含波动 - 拥挤度",
            "event_verified": bool(event and event.get("verified")),
            "components": components,
            "missing": [item["label"] for item in components],
        }

    @staticmethod
    def _plan(code: str, raw: dict[str, Any], phase: dict[str, Any]) -> dict[str, Any]:
        if code == "LEADERSHIP_PULLBACK":
            return {
                "entry_trigger": "缩量回踩后，放量收复20EMA、前一日高点或结构锚定VWAP。",
                "invalidation": "跌破最近结构低点、趋势锚定VWAP，或行业相对强度转弱。",
                "take_profit": ["达到2R先保护部分利润", "沿10EMA、事件VWAP或前一日低点移动止盈", "3–5个交易日没有延续则时间止损"],
            }
        if code == "EXPECTATION_BUILD":
            return {
                "entry_trigger": "事件前7–30天内，预期持续上修且价格完成箱体突破或回踩收复。",
                "invalidation": "预期下修、行业转弱、趋势破位，或进入事件前5天但没有足够利润垫。",
                "take_profit": ["涨幅达到事件隐含涨跌幅或2R时减仓", "事件前默认不保留满仓风险", "事实未超已定价预期时执行卖事实"],
            }
        if code == "POST_EVENT_CONFIRMATION":
            return {
                "entry_trigger": "高质量Beat并上调指引后，等待15–60分钟守住开盘区间与事件VWAP。",
                "invalidation": "跌破开盘低点或事件VWAP；指引质量不足；相对行业转弱。",
                "take_profit": ["跳空超过隐含涨跌幅后保护利润", "Beat+Raise且价格守住时保留趋势仓", "2–3个交易日无延续则退出"],
            }
        if code == "WASHOUT_RECOVERY":
            return {
                "entry_trigger": "至少等待2–3个完整交易日，形成更高低点并收复事件VWAP或20EMA。",
                "invalidation": "跌破恐慌低点，或核验后发现基本面逻辑失效。",
                "take_profit": ["反弹至首个供给区先保护利润", "5个交易日没有延续则时间止损", "不因价格更低而机械摊平"],
            }
        return {
            "entry_trigger": "没有已定义剧本，不建立入场计划。",
            "invalidation": "不适用。",
            "take_profit": [],
        }

    def _driver_tree(self, sector: str) -> dict[str, Any]:
        selected = self.driver_trees["default"]
        for key, tree in self.driver_trees.items():
            if key != "default" and key in sector:
                selected = tree
                break
        return selected

    @staticmethod
    def _qqq_summary(
        qqq: dict[str, Any],
        market_gate: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        recommendation = qqq.get("recommendation") or {}
        return {
            "symbol": qqq.get("symbol") or "QQQ",
            "price": qqq.get("price"),
            "bias": qqq.get("bias") or "UNKNOWN",
            "confidence": qqq.get("confidence"),
            "consensus_score": qqq.get("consensus_score"),
            "decision": qqq.get("decision") or "WAIT",
            "decision_label": qqq.get("decision_label") or "等待数据",
            "state": recommendation.get("state") or "NO_EDGE",
            "setup_ready": bool(recommendation.get("technical_setup_ready")),
            "execution_ready": bool(recommendation.get("execution_ready")) and quality["execution_ready"] and market_gate["execution_ready"],
            "support": recommendation.get("support"),
            "resistance": recommendation.get("resistance"),
            "next_condition": recommendation.get("next_condition"),
            "vetoes": recommendation.get("vetoes") or [],
            "reasoning": qqq.get("reasoning") or {},
            "timeframes": qqq.get("timeframes") or {},
            "plans": qqq.get("plans") or {},
            "warning": qqq.get("warning"),
        }

    @staticmethod
    def _sector_summary(sector: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": sector.get("state") or "UNKNOWN",
            "label": sector.get("state_label") or "数据不足",
            "confidence": sector.get("confidence"),
            "action": sector.get("action"),
            "breadth_pct": sector.get("breadth_pct"),
            "above_ma50_pct": sector.get("above_ma50_pct"),
            "leaders": sector.get("leaders") or [],
            "members": sector.get("members") or [],
        }

    @staticmethod
    def _sell_fact_rules() -> list[dict[str, Any]]:
        return [
            {"condition": "事件前涨幅已达到隐含涨跌幅或2R，预期不再上修", "action": "减仓1/3–1/2，停止追买", "severity": "CAUTION"},
            {"condition": "EPS超预期，但收入、毛利率、现金流或核心KPI质量差", "action": "按低质量Beat处理，退出或显著减仓", "severity": "EXIT"},
            {"condition": "本季度Beat，但下一季度或全年指引低于预期", "action": "卖事实，不用EPS标题替代指引判断", "severity": "EXIT"},
            {"condition": "跳空后跌破开盘区间与事件VWAP，重成交量冲高回落", "action": "退出；价格否定基本面标题", "severity": "EXIT"},
            {"condition": "Beat + Raise，跳空守住且预期继续上修", "action": "分批兑现，保留趋势仓并移动止盈", "severity": "HOLD"},
            {"condition": "事实公布后2–3个交易日没有跟随", "action": "时间止损，释放资金", "severity": "EXIT"},
        ]

