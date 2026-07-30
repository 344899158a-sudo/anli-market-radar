const NASDAQ_BASE = "https://api.nasdaq.com/api/quote/QQQ";
const HEADERS = {
  accept: "application/json, text/plain, */*",
  origin: "https://www.nasdaq.com",
  referer: "https://www.nasdaq.com/",
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
};

export const RULE_VERSION = "anli-pages-1.0.0";
export const THRESHOLDS = Object.freeze({
  eventImminentHours: 72,
  eventVeryCloseHours: 36,
  extendedReturn20Pct: 8,
  extendedRsi: 68,
  extendedDistanceMa20Pct: 6,
  washedReturn20Pct: -8,
  washedRsi: 32,
  washedDistanceMa20Pct: -8,
  pulledReturn20Pct: -3,
  pulledRsi: 42,
  pulledDistanceMa20Pct: -3
});

function numberValue(value) {
  if (value === null || value === undefined) return null;
  const cleaned = String(value)
    .replaceAll("$", "")
    .replaceAll("%", "")
    .replaceAll(",", "")
    .trim();
  if (!cleaned || cleaned === "N/A" || cleaned === "--") return null;
  const result = Number(cleaned);
  return Number.isFinite(result) ? result : null;
}

function parseUsDate(value) {
  const match = value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  return match ? `${match[3]}-${match[1]}-${match[2]}` : null;
}

function average(values, period) {
  if (values.length < period) return null;
  const sample = values.slice(-period);
  return sample.reduce((sum, value) => sum + value, 0) / period;
}

function pct(value, base) {
  return base ? (value / base - 1) * 100 : 0;
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function wilderRsi(values, period = 14) {
  if (values.length <= period) throw new Error(`RSI需要至少${period + 1}根日K`);
  let gains = 0;
  let losses = 0;
  for (let index = 1; index <= period; index += 1) {
    const change = values[index] - values[index - 1];
    gains += Math.max(change, 0);
    losses += Math.max(-change, 0);
  }
  let averageGain = gains / period;
  let averageLoss = losses / period;
  for (let index = period + 1; index < values.length; index += 1) {
    const change = values[index] - values[index - 1];
    averageGain = (averageGain * (period - 1) + Math.max(change, 0)) / period;
    averageLoss = (averageLoss * (period - 1) + Math.max(-change, 0)) / period;
  }
  if (averageLoss === 0) return 100;
  const strength = averageGain / averageLoss;
  return 100 - 100 / (1 + strength);
}

function emaSeries(values, period) {
  if (!values.length) return [];
  const multiplier = 2 / (period + 1);
  const output = [values[0]];
  for (let index = 1; index < values.length; index += 1) {
    output.push(values[index] * multiplier + output[index - 1] * (1 - multiplier));
  }
  return output;
}

function buildMacd(values) {
  const fast = emaSeries(values, 12);
  const slow = emaSeries(values, 26);
  const line = values.map((_, index) => fast[index] - slow[index]);
  const signal = emaSeries(line, 9);
  return { macd: line.at(-1) ?? 0, signal: signal.at(-1) ?? 0 };
}

async function getNasdaqJson(url) {
  const response = await fetch(url, {
    headers: HEADERS,
    signal: AbortSignal.timeout(20_000)
  });
  if (!response.ok) throw new Error(`Nasdaq行情请求失败：HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload?.data) throw new Error("Nasdaq行情未返回有效数据");
  return payload.data;
}

async function fetchHistory() {
  const from = new Date();
  from.setUTCDate(from.getUTCDate() - 620);
  const data = await getNasdaqJson(
    `${NASDAQ_BASE}/historical?assetclass=etf&fromdate=${from.toISOString().slice(0, 10)}&limit=5000`
  );
  const rows = data?.tradesTable?.rows ?? [];
  const bars = rows.flatMap((row) => {
    const date = parseUsDate(row.date ?? "");
    const open = numberValue(row.open);
    const high = numberValue(row.high);
    const low = numberValue(row.low);
    const close = numberValue(row.close);
    const volume = numberValue(row.volume);
    if (!date || open === null || high === null || low === null || close === null) return [];
    if (!(low <= Math.min(open, close) && Math.max(open, close) <= high)) return [];
    return [{ date, open, high, low, close, volume: Math.trunc(volume ?? 0) }];
  });
  bars.sort((a, b) => a.date.localeCompare(b.date));
  const unique = bars.filter((bar, index) => index === 0 || bar.date !== bars[index - 1].date);
  if (unique.length < 200) throw new Error(`日K数据不足：仅${unique.length}根`);
  return unique;
}

async function fetchQuote() {
  const data = await getNasdaqJson(`${NASDAQ_BASE}/info?assetclass=etf`);
  const primary = data.primaryData ?? data.secondaryData;
  const price = numberValue(primary?.lastSalePrice);
  if (price === null) throw new Error("Nasdaq最新QQQ价格缺失");
  const directPct = numberValue(primary?.percentageChange);
  const netChange = numberValue(primary?.netChange);
  const previous = netChange === null ? null : price - netChange;
  return {
    price,
    changePct: directPct ?? (previous ? pct(price, previous) : null),
    quoteLabel: String(primary?.lastTradeTimestamp ?? "交易所最新可用时点")
  };
}

export function buildMarketData(rawBars, quote) {
  if (!Array.isArray(rawBars) || rawBars.length < 200) {
    throw new Error("关键日K不足200根，分析已阻断");
  }
  if (!Number.isFinite(quote?.price)) throw new Error("最新价格缺失，分析已阻断");

  const closes = [];
  const bars = rawBars.map((bar) => {
    closes.push(bar.close);
    return {
      ...bar,
      ma20: average(closes, 20),
      ma50: average(closes, 50),
      ma200: average(closes, 200)
    };
  });
  const latest = bars.at(-1);
  const ma20 = latest.ma20;
  const ma50 = latest.ma50;
  const ma200 = latest.ma200;
  if (ma20 === null || ma50 === null || ma200 === null) {
    throw new Error("QQQ均线数据不完整，分析已阻断");
  }
  const rsi14 = wilderRsi(closes);
  const macd = buildMacd(closes);
  const ma20FiveDaysAgo = bars.at(-6)?.ma20 ?? ma20;
  const high52w = Math.max(...bars.slice(-252).map((bar) => bar.high));
  const recent = bars.slice(-20);
  const support = Math.min(...recent.map((bar) => bar.low));
  const resistanceCandidates = [
    Math.max(...recent.map((bar) => bar.high)),
    ma20,
    ma50
  ].filter((value) => value > quote.price);
  const resistance = resistanceCandidates.length
    ? Math.min(...resistanceCandidates)
    : Math.max(...recent.map((bar) => bar.high));
  const trend =
    quote.price > ma20 && ma20 > ma50 && ma20 > ma20FiveDaysAgo
      ? "UP"
      : quote.price < ma20 && quote.price < ma50
        ? "DOWN"
        : "RANGE";
  const distanceHigh52wPct = pct(quote.price, high52w);
  const distanceMa50Pct = pct(quote.price, ma50);
  const positionCode =
    distanceHigh52wPct >= -3 && (rsi14 >= 68 || distanceMa50Pct >= 8)
      ? "HIGH_RISK"
      : distanceHigh52wPct >= -5
        ? "HIGH"
        : quote.price >= ma50 && quote.price >= ma200
          ? "MID"
          : quote.price >= ma200
            ? "RECOVERY"
            : "LOW";
  const positionLabels = {
    HIGH_RISK: "高位危险区",
    HIGH: "高位震荡区",
    MID: "长期趋势中的中段",
    RECOVERY: "长期趋势上方的修复区",
    LOW: "长期趋势下方"
  };
  const trendLabels = {
    UP: "日K上涨趋势",
    RANGE: "日K震荡整理",
    DOWN: "日K下跌趋势"
  };
  return {
    symbol: "QQQ",
    price: round(quote.price),
    changePct: quote.changePct === null ? null : round(quote.changePct),
    quoteLabel: quote.quoteLabel,
    quoteTime: latest.date,
    provider: "Nasdaq.com 公开延时报价",
    delayed: true,
    bars: bars.slice(-180).map((bar) => ({
      ...bar,
      ma20: bar.ma20 === null ? null : round(bar.ma20, 3),
      ma50: bar.ma50 === null ? null : round(bar.ma50, 3),
      ma200: bar.ma200 === null ? null : round(bar.ma200, 3)
    })),
    rsi14: round(rsi14, 1),
    macd: round(macd.macd, 3),
    macdSignal: round(macd.signal, 3),
    return20Pct: round(pct(latest.close, closes.at(-21) ?? null)),
    distanceMa20Pct: round(pct(quote.price, ma20)),
    distanceMa50Pct: round(distanceMa50Pct),
    distanceMa200Pct: round(pct(quote.price, ma200)),
    distanceHigh52wPct: round(distanceHigh52wPct),
    trend,
    trendLabel: trendLabels[trend],
    positionCode,
    positionLabel: positionLabels[positionCode],
    support: round(support),
    resistance: round(resistance),
    dataQuality: {
      confidence: bars.length >= 252 ? "HIGH" : "MEDIUM",
      historyRows: bars.length,
      missing: []
    }
  };
}

export async function fetchMarketData() {
  const [rawBars, quote] = await Promise.all([fetchHistory(), fetchQuote()]);
  return buildMarketData(rawBars, quote);
}

function nextCriticalEvent(calendar, now) {
  return calendar.weeks
    .flatMap((week) => week.events)
    .filter((event) => event.importance >= 4)
    .map((event) => ({
      ...event,
      hoursAway: (Date.parse(event.at) - now.getTime()) / 3_600_000
    }))
    .filter((event) => event.hoursAway >= 0)
    .sort((a, b) => a.hoursAway - b.hoursAway)[0] ?? null;
}

export function buildDecision(market, calendar, now = new Date()) {
  if (market.dataQuality.historyRows < 200 || market.dataQuality.missing.length) {
    throw new Error("关键行情数据不完整，决策已阻断");
  }
  const event = nextCriticalEvent(calendar, now);
  const eventHours = event?.hoursAway ?? Number.POSITIVE_INFINITY;
  const eventImminent = eventHours <= THRESHOLDS.eventImminentHours;
  const eventVeryClose = eventHours <= THRESHOLDS.eventVeryCloseHours;
  const extended =
    market.return20Pct >= THRESHOLDS.extendedReturn20Pct ||
    market.rsi14 >= THRESHOLDS.extendedRsi ||
    market.distanceMa20Pct >= THRESHOLDS.extendedDistanceMa20Pct ||
    market.distanceHigh52wPct >= -2 ||
    market.positionCode === "HIGH" ||
    market.positionCode === "HIGH_RISK";
  const washedOut =
    market.return20Pct <= THRESHOLDS.washedReturn20Pct ||
    market.rsi14 <= THRESHOLDS.washedRsi ||
    market.distanceMa20Pct <= THRESHOLDS.washedDistanceMa20Pct;
  const pulledBack =
    market.return20Pct <= THRESHOLDS.pulledReturn20Pct ||
    market.rsi14 <= THRESHOLDS.pulledRsi ||
    market.distanceMa20Pct <= THRESHOLDS.pulledDistanceMa20Pct;

  let expectationLabel = "定价未到极端，不提前押注";
  let expectationDetail =
    `QQQ近20日${market.return20Pct.toFixed(1)}%，RSI ${market.rsi14.toFixed(1)}；` +
    "方向优势不足，事件结果比猜测更重要。";
  if (extended) {
    expectationLabel = "预期已涨多，防“卖事实”";
    expectationDetail =
      `QQQ近20日${market.return20Pct.toFixed(1)}%，RSI ${market.rsi14.toFixed(1)}；` +
      "事件若不超预期，利好兑现也可能回落。";
  } else if (washedOut) {
    expectationLabel = "预期已明显回吐，防过度恐慌";
    expectationDetail =
      `QQQ近20日${market.return20Pct.toFixed(1)}%，RSI ${market.rsi14.toFixed(1)}；` +
      "超卖只代表反弹概率上升，不代表基本面或趋势已经反转。";
  } else if (pulledBack) {
    expectationLabel = "预期有所回吐，等待事件定方向";
    expectationDetail =
      `QQQ近20日${market.return20Pct.toFixed(1)}%，RSI ${market.rsi14.toFixed(1)}；` +
      "当前不是追涨区，但日K确认不足，先等催化落地。";
  }

  let gamble = {
    code: "WAIT_CONFIRM",
    label: "先不博，等待日K确认",
    detail: `方向优势不足；日线站上 $${market.resistance.toFixed(2)} 后才重新评估。`,
    exposure: "新增仓0%–计划仓位1/4",
    firstGate: market.resistance
  };
  if (extended && eventImminent) {
    gamble = {
      code: "NO_CHASE",
      label: "现在不追，先保护利润",
      detail: "高位叠加重大事件，新增仓风险收益不划算；盈利仓可先减1/3。",
      exposure: "新增仓0%；盈利高波动仓减1/3",
      firstGate: market.resistance
    };
  } else if (market.trend === "DOWN" && eventImminent) {
    gamble = {
      code: "WAIT_EVENT",
      label: "暂时不博，等事件落地",
      detail:
        `日K仍弱且${event?.title ?? "重大事件"}临近；` +
        `先等结果，再看能否日线站上 $${market.resistance.toFixed(2)}。`,
      exposure: "新增仓0%；已有仓不在急跌中机械砍仓",
      firstGate: market.resistance
    };
  } else if (washedOut && !eventVeryClose) {
    gamble = {
      code: "REVERSAL_WATCH",
      label: "接近可博区，但必须等止跌",
      detail:
        `跌幅释放较充分；只有日线收回 $${market.resistance.toFixed(2)}、` +
        "RSI拐头且事件未证实基本面恶化，才允许小试。",
      exposure: "试探仓≤计划仓位1/3",
      firstGate: market.resistance
    };
  } else if (market.trend === "UP" && !extended && !eventVeryClose) {
    gamble = {
      code: "PROBE_ALLOWED",
      label: "可以小仓博，但不能追",
      detail: "日K趋势允许，等待回踩确认；先设失效位，再要求至少2:1风险收益比。",
      exposure: "试探仓≤计划仓位1/3",
      firstGate: market.resistance
    };
  }

  let actionCode = "NORMAL_PLAN";
  let actionTitle = "按日K计划交易，保留事件前减仓机制";
  let actionDetail = "不追涨；有利润时在下一高风险窗口前重新评估是否减1/3。";
  let priority = "low";
  if (extended && eventImminent) {
    actionCode = "REDUCE_PRE_EVENT";
    actionTitle = "事件前先止盈/减仓，防利好兑现";
    actionDetail = "盈利仓减1/3，高波动仓优先；不扩大同方向暴露。";
    priority = "high";
  } else if (pulledBack && eventImminent) {
    actionCode = "WAIT_FOR_RELEASE";
    actionTitle = "不在事件前抢反弹，等落地后找错杀";
    actionDetail =
      "若结果没有恶化、价格不再创新低并重新站回观察线，再按“买落地后的确认”小仓进入。";
    priority = eventVeryClose ? "high" : "medium";
  } else if (washedOut) {
    actionCode = "WATCH_OVERSOLD";
    actionTitle = "跌多不等于买点，准备观察恐慌修复";
    actionDetail = "先排除基本面恶化；只在事件落地、止跌和日K转强同时出现后试探。";
    priority = "medium";
  } else if (eventImminent) {
    actionCode = "HOLD_RISK";
    actionTitle = "维持轻仓，重大事件前不加码";
    actionDetail = "已有盈利可抬高保护线；空仓等待结果，不提前押单边。";
    priority = "medium";
  }

  const eventPhase =
    eventHours <= 6 ? "6h" : eventHours <= 24 ? "24h" : eventHours <= 72 ? "72h" : "later";
  const eventText = event
    ? `${event.title} · ${eventHours.toFixed(1)}小时后`
    : "未来72小时暂无四级事件";
  return {
    ruleVersion: RULE_VERSION,
    generatedAt: now.toISOString(),
    question: "这个位置，可以博一下吗？",
    gamble,
    catalyst: {
      actionCode,
      actionTitle,
      actionDetail,
      priority,
      expectationLabel,
      expectationDetail,
      nextEvent: event
    },
    scenarios: [
      {
        label: "已有盈利仓",
        action:
          extended && eventImminent
            ? "高位事件前减1/3，剩余仓抬高保护线。"
            : "不在急跌中机械止盈；不加仓，等事件和日K确认。"
      },
      {
        label: "现在空仓",
        action: "事件前不押方向；落地后基本面无恶化且日K转强，再用计划仓位1/3试探。"
      },
      {
        label: "事件落地后",
        action: "利好但冲高回落＝卖事实风险；利空不再创新低且收复观察线＝潜在错杀。"
      }
    ],
    alert: {
      signature: `${gamble.code}|${actionCode}|${event?.id ?? "none"}|${eventPhase}`,
      title: `QQQ：${gamble.label}`,
      body: `${actionTitle}；${eventText}。`
    },
    guardrails: [
      "超买/超卖只描述位置，不单独触发买卖。",
      "事件结果未知时，不把“买预期、卖事实”当成确定预测。",
      "下单前用券商实时价格复核；系统不自动下单。"
    ]
  };
}
