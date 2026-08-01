from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


HARD_KEYS = ("industry", "quality", "above_ma50", "stabilized", "drawdown", "not_chasing")
CHECK_LABELS = {
    "industry": "行业趋势",
    "quality": "公司质地",
    "above_ma50": "规则32：站上50日线",
    "stabilized": "连续2–3日企稳",
    "drawdown": "错杀幅度",
    "not_chasing": "不追涨",
    "volume": "成交量确认",
    "catalyst": "42天内明确催化剂",
}


def _ai_is_fresh(ai: dict[str, Any] | None, hours: int = 6) -> bool:
    if not ai or not ai.get("analyzed_at"):
        return False
    try:
        analyzed = datetime.fromisoformat(str(ai["analyzed_at"]))
        return (datetime.now(timezone.utc) - analyzed).total_seconds() <= hours * 3600
    except (TypeError, ValueError):
        return False


def assess_opportunity(signal: dict[str, Any], ai: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = signal.get("checks") or {}
    failed_hard = [key for key in HARD_KEYS if not checks.get(key)]
    passed_hard = len(HARD_KEYS) - len(failed_hard)
    ai_fresh = _ai_is_fresh(ai)
    ai_gate = ai.get("buy_gate") if ai_fresh and ai else None
    ai_verdict = ai.get("verdict") if ai_fresh and ai else None
    deterioration = ai.get("fundamental_deterioration") if ai_fresh and ai else None
    confidence = int(ai.get("confidence") or 0) if ai_fresh and ai else 0
    catalyst_days = signal.get("catalyst_days")

    catalyst_band = "无明确催化剂"
    if isinstance(catalyst_days, int):
        if 0 <= catalyst_days < 14:
            catalyst_band = "两周内催化剂"
        elif 14 <= catalyst_days <= 42:
            catalyst_band = "2–6周甜蜜区"
        elif catalyst_days > 42:
            catalyst_band = "催化剂超过6周"
        else:
            catalyst_band = "催化剂已过"

    veto = ai_fresh and (ai_gate == "否决" or deterioration is True or ai_verdict == "恶化")
    ai_pass = ai_fresh and ai_gate == "通过" and deterioration is not True and confidence >= 50
    quant_ready = signal.get("status") == "READY" and not failed_hard

    if signal.get("status") == "NO_DATA":
        stage, label = "NO_DATA", "数据不足"
    elif veto:
        stage, label = "VETO", "基本面否决"
    elif quant_ready and not ai_fresh:
        stage, label = "AI_REVIEW", "量价通过·等待AI"
    elif quant_ready and ai_pass and checks.get("catalyst"):
        stage, label = "STRONG", "强机会"
    elif quant_ready and ai_pass:
        stage, label = "READY_SMALL", "规则机会·小仓"
    elif quant_ready:
        stage, label = "HOLD", "暂缓"
    elif len(failed_hard) == 1 and checks.get("quality"):
        stage, label = "NEAR", "临门一脚"
    elif checks.get("quality") and checks.get("drawdown"):
        stage, label = "SETUP", "错杀观察"
    else:
        stage, label = "WATCH", "等待"

    score = int(signal.get("score") or 0)
    if ai_fresh:
        score += 10 if ai_gate == "通过" else -35 if veto else -5
        score += round((confidence - 50) / 10) if ai_gate == "通过" else 0
    if checks.get("catalyst"):
        score += 5
    final_score = max(0, min(100, score))

    missing = [CHECK_LABELS[key] for key in failed_hard]
    next_action = "继续观察，不采取行动"
    if stage == "VETO":
        next_action = "基本面风险未解除前不碰"
    elif stage == "AI_REVIEW":
        next_action = "等待AI读取新闻与SEC财务数据"
    elif stage == "NEAR" and failed_hard:
        key = failed_hard[0]
        if key == "above_ma50" and signal.get("ma50"):
            next_action = f"等待价格重新站上 ${signal['ma50']:.2f} 的50日线"
        elif key == "stabilized":
            next_action = "等待连续2–3日不再创新低"
        elif key == "industry":
            next_action = "等待所属行业ETF重新站上50日线"
        else:
            next_action = f"等待通过：{CHECK_LABELS[key]}"
    elif stage == "SETUP":
        next_action = "保持观察，等待50日线与企稳确认"
    elif stage == "STRONG":
        next_action = "四层通过，可按纪律分批执行；单仓不超过总资金10%"
    elif stage == "READY_SMALL":
        next_action = "前三层通过但无明确催化剂，只适合小仓、快进快出"
    elif stage == "HOLD":
        next_action = "量价通过但AI未放行，暂缓"

    return {
        "stage": stage,
        "stage_label": label,
        "final_score": final_score,
        "can_act": stage in {"STRONG", "READY_SMALL"},
        "quant_ready": quant_ready,
        "hard_passed": passed_hard,
        "hard_total": len(HARD_KEYS),
        "missing_hard": missing,
        "next_action": next_action,
        "catalyst_band": catalyst_band,
        "ai_fresh": ai_fresh,
        "ai_gate": ai_gate,
        "ai_verdict": ai_verdict,
        "ai_confidence": confidence,
        "ai_risk_score": ai.get("risk_score") if ai_fresh and ai else None,
        "ai_analyzed_at": ai.get("analyzed_at") if ai_fresh and ai else None,
    }


def enrich_signal(signal: dict[str, Any], ai: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(signal)
    result["opportunity"] = assess_opportunity(signal, ai)
    if ai:
        result["ai_analysis"] = {
            key: ai.get(key)
            for key in (
                "verdict", "risk_score", "confidence", "fundamental_deterioration",
                "moat", "summary", "buy_gate", "analyzed_at", "model",
            )
        }
    else:
        result["ai_analysis"] = None
    return result
