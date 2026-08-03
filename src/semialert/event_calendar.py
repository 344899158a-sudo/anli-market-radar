from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


VERIFIED_AT = "2026-08-03T17:50:26+08:00"
ET = ZoneInfo("America/New_York")

FED = ("Federal Reserve", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "官方日历确认")
BLS = ("U.S. Bureau of Labor Statistics", "https://www.bls.gov/schedule/2026/home.htm", "官方日历确认")
BEA = ("U.S. Bureau of Economic Analysis", "https://www.bea.gov/news/schedule/full", "官方日历确认")


def _event(
    event_id: str, at: str, category: str, title: str, importance: int,
    source: tuple[str, str, str], note: str, scope: list[str],
) -> dict[str, Any]:
    return {
        "id": event_id, "at": at, "category": category, "title": title,
        "importance": importance, "source": source[0], "source_url": source[1],
        "verification": source[2], "note": note, "scope": scope,
    }


EVENTS = (
    _event("glw-q2", "2026-07-28T08:30:00-04:00", "财报", "Corning（GLW）Q2 财报", 3,
           ("Corning Investor Relations", "https://investor.corning.com/news-and-events/events-and-presentations/default.aspx", "公司官网确认"),
           "盘前；关注光通信与AI基础设施需求。", ["GLW", "光通信"]),
    _event("fomc-jul", "2026-07-29T14:00:00-04:00", "宏观", "FOMC 利率决议与新闻发布会", 4, FED,
           "两日会议于7月28–29日举行；决议日波动风险最高。", ["全市场"]),
    _event("meta-q2", "2026-07-29T16:30:00-04:00", "财报", "Meta（META）Q2 财报", 4,
           ("Meta Investor Relations", "https://investor.atmeta.com/investor-events/default.aspx", "公司官网确认"),
           "盘后；关注AI资本开支、广告与利润率。", ["META", "QQQ", "AI广告"]),
    _event("arm-fy27-q1", "2026-07-29T17:00:00-04:00", "财报", "Arm（ARM）FY2027 Q1 财报", 3,
           ("Arm Investor Relations", "https://investors.arm.com/news-events/investor-events-presentations/", "公司官网列为暂定"),
           "公司官网标注为 tentative，临近前需再次复核。", ["ARM", "半导体"]),
    _event("msft-fy26-q4", "2026-07-29T17:30:00-04:00", "财报", "Microsoft（MSFT）FY2026 Q4 财报", 4,
           ("Microsoft Investor Relations", "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4", "公司公告确认"),
           "盘后；关注Azure、AI资本开支与指引。", ["MSFT", "QQQ", "AI云"]),
    _event("gdp-pce", "2026-07-30T08:30:00-04:00", "宏观", "美国 Q2 GDP 初值 + 6月PCE", 4, BEA,
           "增长与通胀同日发布，利率预期可能快速重定价。", ["全市场"]),
    _event("aapl-q3", "2026-07-30T17:00:00-04:00", "财报", "Apple（AAPL）FY2026 Q3 财报", 4,
           ("Apple Investor Relations", "https://www.apple.com/investor/earnings-call/", "公司官网确认"),
           "盘后；关注iPhone、服务与中国市场。", ["AAPL", "QQQ"]),
    _event("amzn-q2", "2026-07-30T17:00:00-04:00", "财报", "Amazon（AMZN）Q2 财报", 4,
           ("Amazon Investor Relations", "https://ir.aboutamazon.com/events/", "公司官网确认"),
           "盘后；关注AWS、AI资本开支与零售利润率。", ["AMZN", "QQQ", "AI云"]),
    _event("eci-q2", "2026-07-31T08:30:00-04:00", "宏观", "美国 Q2 就业成本指数（ECI）", 3, BLS,
           "工资通胀的重要观察点。", ["全市场"]),
    _event("jolts-jun", "2026-08-04T10:00:00-04:00", "宏观", "美国 JOLTS 职位空缺", 3, BLS,
           "劳动需求与降息预期的前置指标。", ["全市场"]),
    _event("amd-q2", "2026-08-04T17:00:00-04:00", "财报", "AMD Q2 财报", 4,
           ("AMD Investor Relations", "https://ir.amd.com/news-events/press-releases/detail/1289/amd-to-report-fiscal-second-quarter-2026-financial-results", "公司官网确认"),
           "盘后；关注数据中心GPU、MI系列与毛利率。", ["AMD", "NVDA", "半导体", "QQQ"]),
    _event("productivity-q2", "2026-08-06T08:30:00-04:00", "宏观", "美国 Q2 非农生产率初值", 2, BLS,
           "影响单位劳动力成本与通胀判断。", ["全市场"]),
    _event("nfp-jul", "2026-08-07T08:30:00-04:00", "宏观", "美国 7月非农就业报告", 4, BLS,
           "就业、失业率与工资共同影响利率路径。", ["全市场"]),
    _event("cpi-jul", "2026-08-12T08:30:00-04:00", "宏观", "美国 7月 CPI", 4, BLS,
           "通胀核心事件，盘前波动风险高。", ["全市场"]),
    _event("ppi-jul", "2026-08-13T08:30:00-04:00", "宏观", "美国 7月 PPI", 3, BLS,
           "与CPI连续发布，注意二次定价。", ["全市场"]),
    _event("import-prices", "2026-08-18T08:30:00-04:00", "宏观", "美国 7月进出口价格", 2, BLS,
           "补充观察输入型通胀。", ["全市场"]),
    _event("fomc-minutes", "2026-08-19T14:00:00-04:00", "宏观", "7月 FOMC 会议纪要", 3,
           ("Federal Reserve", "https://www.federalreserve.gov/newsevents/2026-august.htm", "官方日历确认"),
           "关注委员会分歧与未来政策条件。", ["全市场"]),
    _event("opex-aug", "2026-08-21T16:00:00-04:00", "衍生品", "美股月度期权到期（OPEX）", 3,
           ("标准月度到期规则", "https://www.cboe.com/tradable_products/equity_indices_leaps_options/specifications/", "规则推导，非实时公告"),
           "第三个星期五；关注临近收盘的对冲与再平衡波动。", ["全市场"]),
)


def _risk_label(score: int) -> str:
    return "很高" if score >= 4 else "高" if score == 3 else "中" if score == 2 else "低"


def _next_or_same_monday(value: date) -> date:
    """Return the start of the next complete Monday-Sunday week."""
    return value + timedelta(days=(-value.weekday()) % 7)


def build_event_calendar(today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(ET).date()
    first_week_start = _next_or_same_monday(today)
    now = datetime.now(timezone.utc)
    verified = datetime.fromisoformat(VERIFIED_AT).astimezone(timezone.utc)
    age_hours = max(0, (now - verified).total_seconds() / 3600)
    weeks = []
    for index in range(4):
        start = first_week_start + timedelta(days=index * 7)
        end = start + timedelta(days=6)
        events = []
        for raw in EVENTS:
            event_time = datetime.fromisoformat(raw["at"])
            if start <= event_time.astimezone(ET).date() <= end:
                event = dict(raw)
                event["at_et"] = event_time.isoformat()
                event["at_cn"] = event_time.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
                events.append(event)
        events.sort(key=lambda item: item["at_et"])
        score = max((int(item["importance"]) for item in events), default=1)
        critical_count = sum(int(item["importance"]) >= 4 for item in events)
        action = (
            "重大事件密集：已有盈利优先保护，不在事件前扩大同方向高波动仓位。" if score >= 4
            else "保持仓位克制，事件前减少追涨，确认结果后再提高风险预算。" if score == 3
            else "可按计划交易，但保留事件日失效位与仓位上限。" if score == 2
            else "事件压力较低，仍以大盘趋势和个股条件为准。"
        )
        weeks.append({
            "index": index + 1, "start": start.isoformat(), "end": end.isoformat(),
            "label": ("本周" if start == today else "下周") if index == 0 else f"第{index + 1}周",
            "risk_score": score, "risk_label": _risk_label(score),
            "event_count": len(events), "critical_count": critical_count,
            "action": action, "events": events,
        })
    return {
        "generated_at": now.isoformat(), "verified_at": VERIFIED_AT,
        "verification_age_hours": round(age_hours, 1),
        "verification_status": "已核验" if age_hours <= 48 else "需要重新核验",
        "timezone_note": "页面同时显示美东时间与北京时间；交易决策以美东交易日为准。",
        "weeks": weeks, "event_count": sum(len(week["events"]) for week in weeks),
        "methodology": "每周固定为周一至周日；宏观日期取自美联储、BLS、BEA官方日历；财报优先取公司投资者关系页面；无法核验的日期不显示。",
    }
