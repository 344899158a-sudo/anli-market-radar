export const EVENTS_VERIFIED_AT = "2026-08-04T09:27:47+08:00";

export const VERIFIED_EVENTS = [
  {
    id: "fomc-jul",
    at: "2026-07-29T14:00:00-04:00",
    category: "宏观",
    title: "FOMC 利率决议与新闻发布会",
    importance: 4,
    source: "Federal Reserve",
    sourceUrl: "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    verification: "官方日历确认",
    note: "两日会议于7月28–29日举行；决议日波动风险最高。",
    scope: ["全市场"]
  },
  {
    id: "meta-q2",
    at: "2026-07-29T16:30:00-04:00",
    category: "财报",
    title: "Meta（META）Q2 财报",
    importance: 4,
    source: "Meta Investor Relations",
    sourceUrl: "https://investor.atmeta.com/investor-events/default.aspx",
    verification: "公司官网确认",
    note: "盘后；关注AI资本开支、广告与利润率。",
    scope: ["META", "QQQ", "AI广告"]
  },
  {
    id: "arm-fy27-q1",
    at: "2026-07-29T17:00:00-04:00",
    category: "财报",
    title: "Arm（ARM）FY2027 Q1 财报",
    importance: 3,
    source: "Arm Investor Relations",
    sourceUrl: "https://investors.arm.com/news-events/investor-events-presentations/",
    verification: "公司官网列为暂定",
    note: "公司官网标注为 tentative，临近前需再次复核。",
    scope: ["ARM", "半导体"]
  },
  {
    id: "msft-fy26-q4",
    at: "2026-07-29T17:30:00-04:00",
    category: "财报",
    title: "Microsoft（MSFT）FY2026 Q4 财报",
    importance: 4,
    source: "Microsoft Investor Relations",
    sourceUrl: "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4",
    verification: "公司公告确认",
    note: "盘后；关注Azure、AI资本开支与指引。",
    scope: ["MSFT", "QQQ", "AI云"]
  },
  {
    id: "gdp-pce",
    at: "2026-07-30T08:30:00-04:00",
    category: "宏观",
    title: "美国 Q2 GDP 初值 + 6月PCE",
    importance: 4,
    source: "U.S. Bureau of Economic Analysis",
    sourceUrl: "https://www.bea.gov/news/schedule/full",
    verification: "官方日历确认",
    note: "增长与通胀同日发布，利率预期可能快速重定价。",
    scope: ["全市场"]
  },
  {
    id: "aapl-q3",
    at: "2026-07-30T17:00:00-04:00",
    category: "财报",
    title: "Apple（AAPL）FY2026 Q3 财报",
    importance: 4,
    source: "Apple Investor Relations",
    sourceUrl: "https://www.apple.com/investor/earnings-call/",
    verification: "公司官网确认",
    note: "盘后；关注iPhone、服务与中国市场。",
    scope: ["AAPL", "QQQ"]
  },
  {
    id: "amzn-q2",
    at: "2026-07-30T17:00:00-04:00",
    category: "财报",
    title: "Amazon（AMZN）Q2 财报",
    importance: 4,
    source: "Amazon Investor Relations",
    sourceUrl: "https://ir.aboutamazon.com/events/",
    verification: "公司官网确认",
    note: "盘后；关注AWS、AI资本开支与零售利润率。",
    scope: ["AMZN", "QQQ", "AI云"]
  },
  {
    id: "eci-q2",
    at: "2026-07-31T08:30:00-04:00",
    category: "宏观",
    title: "美国 Q2 就业成本指数（ECI）",
    importance: 3,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "工资通胀的重要观察点。",
    scope: ["全市场"]
  },
  {
    id: "jolts-jun",
    at: "2026-08-04T10:00:00-04:00",
    category: "宏观",
    title: "美国 JOLTS 职位空缺",
    importance: 3,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "劳动需求与降息预期的前置指标。",
    scope: ["全市场"]
  },
  {
    id: "amd-q2",
    at: "2026-08-04T17:00:00-04:00",
    category: "财报",
    title: "AMD Q2 财报",
    importance: 4,
    source: "AMD Investor Relations",
    sourceUrl: "https://ir.amd.com/news-events/press-releases/detail/1289/amd-to-report-fiscal-second-quarter-2026-financial-results",
    verification: "公司官网确认",
    note: "盘后；关注数据中心GPU、MI系列与毛利率。",
    scope: ["AMD", "NVDA", "半导体", "QQQ"]
  },
  {
    id: "productivity-q2",
    at: "2026-08-06T08:30:00-04:00",
    category: "宏观",
    title: "美国 Q2 非农生产率初值",
    importance: 2,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "影响单位劳动力成本与通胀判断。",
    scope: ["全市场"]
  },
  {
    id: "nfp-jul",
    at: "2026-08-07T08:30:00-04:00",
    category: "宏观",
    title: "美国 7月非农就业报告",
    importance: 4,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "就业、失业率与工资共同影响利率路径。",
    scope: ["全市场"]
  },
  {
    id: "cpi-jul",
    at: "2026-08-12T08:30:00-04:00",
    category: "宏观",
    title: "美国 7月 CPI",
    importance: 4,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "通胀核心事件，盘前波动风险高。",
    scope: ["全市场"]
  },
  {
    id: "ppi-jul",
    at: "2026-08-13T08:30:00-04:00",
    category: "宏观",
    title: "美国 7月 PPI",
    importance: 3,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "与CPI连续发布，注意二次定价。",
    scope: ["全市场"]
  },
  {
    id: "import-prices",
    at: "2026-08-18T08:30:00-04:00",
    category: "宏观",
    title: "美国 7月进出口价格",
    importance: 2,
    source: "U.S. Bureau of Labor Statistics",
    sourceUrl: "https://www.bls.gov/schedule/2026/home.htm",
    verification: "官方日历确认",
    note: "补充观察输入型通胀。",
    scope: ["全市场"]
  },
  {
    id: "fomc-minutes",
    at: "2026-08-19T14:00:00-04:00",
    category: "宏观",
    title: "7月 FOMC 会议纪要",
    importance: 3,
    source: "Federal Reserve",
    sourceUrl: "https://www.federalreserve.gov/newsevents/2026-august.htm",
    verification: "官方日历确认",
    note: "关注委员会分歧与未来政策条件。",
    scope: ["全市场"]
  },
  {
    id: "opex-aug",
    at: "2026-08-21T16:00:00-04:00",
    category: "衍生品",
    title: "美股月度期权到期（OPEX）",
    importance: 3,
    source: "Cboe",
    sourceUrl: "https://www.cboe.com/tradable_products/equity_indices_leaps_options/specifications/",
    verification: "标准月度规则推导",
    note: "第三个星期五；关注临近收盘的对冲与再平衡波动。",
    scope: ["全市场"]
  }
];

function shanghaiDate(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(value);
}

function addDays(date, days) {
  return new Date(date.getTime() + days * 86_400_000);
}

function riskLabel(score) {
  return score >= 4 ? "很高" : score === 3 ? "高" : score === 2 ? "中" : "低";
}

export function buildEventCalendar(now = new Date()) {
  const todayKey = shanghaiDate(now);
  const today = new Date(`${todayKey}T12:00:00+08:00`);
  const weekday = today.getUTCDay();
  const mondayOffset = weekday === 0 ? 1 : 1 - weekday;
  const firstWeekStart = addDays(today, mondayOffset);
  const weeks = Array.from({ length: 4 }, (_, index) => {
    const start = addDays(firstWeekStart, index * 7);
    const end = addDays(start, 6);
    const startKey = shanghaiDate(start);
    const endKey = shanghaiDate(end);
    const events = VERIFIED_EVENTS.filter((event) => {
      const key = shanghaiDate(new Date(event.at));
      return key >= startKey && key <= endKey;
    }).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    const riskScore = Math.max(1, ...events.map((event) => event.importance));
    const action =
      riskScore >= 4
        ? "重大事件密集：已有盈利优先保护，不在事件前扩大同方向高波动仓位。"
        : riskScore === 3
          ? "保持仓位克制，事件前减少追涨，确认结果后再提高风险预算。"
          : "可按计划交易，但保留事件日失效位与仓位上限。";
    return {
      index: index + 1,
      label: index === 0 ? (weekday === 0 ? "下周" : "本周") : `第${index + 1}周`,
      start: startKey,
      end: endKey,
      riskScore,
      riskLabel: riskLabel(riskScore),
      eventCount: events.length,
      criticalCount: events.filter((event) => event.importance >= 4).length,
      action,
      events
    };
  });
  const verifiedAgeHours = (now.getTime() - Date.parse(EVENTS_VERIFIED_AT)) / 3_600_000;
  return {
    generatedAt: now.toISOString(),
    verifiedAt: EVENTS_VERIFIED_AT,
    verificationStatus: verifiedAgeHours <= 72 ? "已核验" : "需再次核验",
    methodology:
      "宏观日期取自美联储、BLS、BEA官方日历；财报取公司投资者关系页面；未核验日期不显示。",
    timezoneNote: "事件按北京时间展示，原始时间以美东交易日为准。",
    eventCount: weeks.reduce((total, week) => total + week.eventCount, 0),
    weeks
  };
}
