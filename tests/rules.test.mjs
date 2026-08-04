import test from "node:test";
import assert from "node:assert/strict";
import { buildDecision, buildMarketData, RULE_VERSION, THRESHOLDS } from "../scripts/core.mjs";
import { buildEventCalendar } from "../scripts/events.mjs";

function market(overrides = {}) {
  return {
    symbol: "QQQ",
    price: 700,
    changePct: 0,
    quoteLabel: "test",
    quoteTime: "2026-07-29",
    provider: "test",
    delayed: true,
    bars: [],
    rsi14: 50,
    macd: 1,
    macdSignal: 0,
    return20Pct: 0,
    distanceMa20Pct: 0,
    distanceMa50Pct: 0,
    distanceMa200Pct: 5,
    distanceHigh52wPct: -8,
    trend: "RANGE",
    trendLabel: "日K震荡整理",
    positionCode: "MID",
    positionLabel: "长期趋势中的中段",
    support: 680,
    resistance: 710,
    dataQuality: { confidence: "HIGH", historyRows: 400, missing: [] },
    ...overrides
  };
}

function calendar(now, hoursAway = null) {
  const events =
    hoursAway === null
      ? []
      : [
          {
            id: "critical",
            at: new Date(now.getTime() + hoursAway * 3_600_000).toISOString(),
            category: "宏观",
            title: "重大事件",
            importance: 4,
            source: "official",
            sourceUrl: "https://example.com",
            verification: "confirmed",
            note: "test",
            scope: ["全市场"]
          }
        ];
  return {
    generatedAt: now.toISOString(),
    verifiedAt: now.toISOString(),
    verificationStatus: "已核验",
    methodology: "test",
    timezoneNote: "test",
    eventCount: events.length,
    weeks: [
      {
        index: 1,
        label: "本周",
        start: "2026-07-29",
        end: "2026-08-04",
        riskScore: events.length ? 4 : 1,
        riskLabel: events.length ? "很高" : "低",
        eventCount: events.length,
        criticalCount: events.length,
        action: "test",
        events
      }
    ]
  };
}

test("规则版本与阈值集中配置", () => {
  assert.equal(RULE_VERSION, "anli-pages-1.0.0");
  assert.equal(THRESHOLDS.eventImminentHours, 72);
});

test("关键数据缺失时阻断决策", () => {
  const now = new Date("2026-07-29T00:00:00Z");
  assert.throws(
    () =>
      buildDecision(
        market({ dataQuality: { confidence: "LOW", historyRows: 150, missing: ["MA200"] } }),
        calendar(now),
        now
      ),
    /关键行情数据不完整/
  );
});

test("高位与重大事件冲突时利润保护优先", () => {
  const now = new Date("2026-07-29T00:00:00Z");
  const result = buildDecision(
    market({
      trend: "UP",
      positionCode: "HIGH_RISK",
      rsi14: 72,
      return20Pct: 9,
      distanceHigh52wPct: -1
    }),
    calendar(now, 24),
    now
  );
  assert.equal(result.gamble.code, "NO_CHASE");
  assert.equal(result.catalyst.actionCode, "REDUCE_PRE_EVENT");
  assert.equal(result.catalyst.priority, "high");
});

test("日K弱且事件临近时等待落地", () => {
  const now = new Date("2026-07-29T00:00:00Z");
  const result = buildDecision(
    market({
      trend: "DOWN",
      rsi14: 40,
      return20Pct: -4,
      distanceMa20Pct: -4
    }),
    calendar(now, 20),
    now
  );
  assert.equal(result.gamble.code, "WAIT_EVENT");
  assert.equal(result.catalyst.actionCode, "WAIT_FOR_RELEASE");
});

test("明显超卖但事件不近时只进入反转观察", () => {
  const now = new Date("2026-07-29T00:00:00Z");
  const result = buildDecision(
    market({
      trend: "DOWN",
      rsi14: 29,
      return20Pct: -10,
      distanceMa20Pct: -9
    }),
    calendar(now, 96),
    now
  );
  assert.equal(result.gamble.code, "REVERSAL_WATCH");
  assert.equal(result.catalyst.actionCode, "WATCH_OVERSOLD");
});

test("上涨且不过热时才允许小仓试探", () => {
  const now = new Date("2026-07-29T00:00:00Z");
  const result = buildDecision(
    market({
      trend: "UP",
      rsi14: 55,
      return20Pct: 3,
      distanceMa20Pct: 2,
      distanceHigh52wPct: -8
    }),
    calendar(now),
    now
  );
  assert.equal(result.gamble.code, "PROBE_ALLOWED");
});

test("原始日K少于200根时拒绝构建市场状态", () => {
  const bars = Array.from({ length: 199 }, (_, index) => ({
    date: `2025-01-${String((index % 28) + 1).padStart(2, "0")}`,
    open: 100,
    high: 102,
    low: 99,
    close: 101,
    volume: 1000
  }));
  assert.throws(() => buildMarketData(bars, { price: 101 }), /不足200根/);
});
test("事件日历使用完整的周一到周日自然周", () => {
  const sunday = buildEventCalendar(new Date("2026-08-02T12:00:00+08:00"));
  assert.equal(sunday.weeks[0].label, "下周");
  assert.equal(sunday.weeks[0].start, "2026-08-03");
  assert.equal(sunday.weeks[0].end, "2026-08-09");

  const monday = buildEventCalendar(new Date("2026-08-03T12:00:00+08:00"));
  assert.equal(monday.weeks[0].label, "本周");
  assert.equal(monday.weeks[0].start, "2026-08-03");
  assert.equal(monday.weeks[0].end, "2026-08-09");

  const tuesday = buildEventCalendar(new Date("2026-08-04T12:00:00+08:00"));
  assert.equal(tuesday.weeks[0].label, "本周");
  assert.equal(tuesday.weeks[0].start, "2026-08-03");
  assert.equal(tuesday.weeks[0].end, "2026-08-09");
});