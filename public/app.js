const app = document.querySelector("#app");
const refreshButton = document.querySelector("#refresh-button");
const alertButton = document.querySelector("#alert-button");
const reminder = document.querySelector("#reminder");
const reminderTitle = document.querySelector("#reminder-title");
const reminderBody = document.querySelector("#reminder-body");
const reminderClose = document.querySelector("#reminder-close");
const pageTitle = document.querySelector(".app-bar h1");

let chartObserver;

const state = {
  payload: null,
  range: 66,
  weekIndex: 0,
  alertsEnabled: localStorage.getItem("anli-pages-alerts") === "1"
};

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

function signed(value) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value));
}

function eventTime(value) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(new Date(value));
  const get = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return {
    day: `${Number(get("day"))}日`,
    monthTime: `${Number(get("month"))}月 · ${get("hour")}:${get("minute")}`
  };
}

function weekRange(week) {
  return `${week.start.slice(5).replace("-", ".")}—${week.end.slice(5).replace("-", ".")}`;
}

function freshness(value) {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60_000));
  if (minutes < 2) return "刚刚更新";
  if (minutes < 60) return `${minutes}分钟前更新`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前更新`;
  return `${Math.floor(hours / 24)}天前快照`;
}

function isDetailView() {
  return window.location.hash === "#trendiq";
}

function snapshotHealth(value) {
  const ageMinutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60_000));
  const weekday = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    weekday: "short"
  }).format(new Date());
  const staleAfterMinutes = weekday === "Sat" || weekday === "Sun" ? 26 * 60 : 45;
  return {
    ageMinutes,
    stale: ageMinutes > staleAfterMinutes
  };
}

function showReminder(title, body) {
  reminderTitle.textContent = title;
  reminderBody.textContent = body;
  reminder.hidden = false;
}

function updateAlertButton() {
  alertButton.textContent = state.alertsEnabled ? "页内提醒已开" : "开启页内提醒";
  alertButton.classList.toggle("active", state.alertsEnabled);
  alertButton.setAttribute("aria-pressed", String(state.alertsEnabled));
}

function maybeAlert() {
  if (!state.payload || !state.alertsEnabled) return;
  const { alert } = state.payload.decision;
  const key = "anli-pages-last-alert";
  if (localStorage.getItem(key) === alert.signature) return;
  localStorage.setItem(key, alert.signature);
  showReminder(alert.title, alert.body);
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(alert.title, { body: alert.body, tag: alert.signature });
    } catch {
      // 微信内置浏览器等环境仍使用页面内提醒。
    }
  }
}

function render() {
  const { market, decision, calendar, generatedAt } = state.payload;
  const detailView = isDetailView();
  const health = snapshotHealth(generatedAt);
  const evidenceWasOpen = Boolean(app.querySelector(".evidence")?.open);
  const selectedWeek = calendar.weeks[Math.min(state.weekIndex, calendar.weeks.length - 1)];
  const gambleTone =
    decision.gamble.code === "PROBE_ALLOWED"
      ? "good"
      : decision.gamble.code === "NO_CHASE"
        ? "danger"
        : "warn";
  const latestBar = market.bars.at(-1);
  const conditionCount = [
    market.trend === "UP",
    market.price > (latestBar?.ma20 ?? Number.POSITIVE_INFINITY),
    market.rsi14 >= 40 && market.rsi14 <= 65,
    market.macd > market.macdSignal
  ].filter(Boolean).length;
  const eventHtml = selectedWeek.events.length
    ? selectedWeek.events
        .map((event) => {
          const time = eventTime(event.at);
          return `
            <article>
              <div class="event-date">
                <strong>${escapeHtml(time.day)}</strong>
                <span>${escapeHtml(time.monthTime)}</span>
              </div>
              <div class="event-body">
                <div>
                  <span class="category">${escapeHtml(event.category)}</span>
                  <span class="importance" aria-label="重要性${event.importance}级">${"●".repeat(event.importance)}</span>
                  <small>北京时间</small>
                </div>
                <h4>${escapeHtml(event.title)}</h4>
                <p>${escapeHtml(event.note)}</p>
                <a href="${escapeHtml(event.sourceUrl)}" target="_blank" rel="noreferrer">
                  ${escapeHtml(event.verification)} · 查看官方来源
                </a>
              </div>
            </article>`;
        })
        .join("")
    : '<p class="empty-week">本周暂无已核验重大事件。</p>';
  const catalystBadge =
    decision.catalyst.actionCode === "REDUCE_PRE_EVENT"
      ? "减仓 / 止盈"
      : decision.catalyst.actionCode === "WAIT_FOR_RELEASE"
        ? "等待落地"
        : decision.catalyst.actionCode === "WATCH_OVERSOLD"
          ? "超跌观察"
          : "按计划";

  app.innerHTML = `
    <p class="cloud-note">
      独立公开版 · 电脑关机仍可访问 · Nasdaq公开延时报价 · 仅作决策辅助，不自动下单
    </p>

    <section class="module-card opportunity" aria-labelledby="opportunity-title">
      <div class="section-heading">
        <div>
          <span>01 · QQQ当前机会</span>
          <h2 id="opportunity-title">这个位置，可以博一下吗？</h2>
        </div>
        <small>${escapeHtml(freshness(generatedAt))}<br />${escapeHtml(market.provider)}</small>
      </div>

      <div class="direct-answer ${gambleTone}">
        <div>
          <span>系统直接回答</span>
          <strong>${escapeHtml(decision.gamble.label)}</strong>
          <p>${escapeHtml(decision.gamble.detail)}</p>
        </div>
        <em>${escapeHtml(decision.gamble.exposure)}</em>
      </div>

      <div class="state-line">
        <div class="state-gauge"><strong>${conditionCount}/4</strong><span>日K条件</span></div>
        <div>
          <span class="trend-pill ${market.trend.toLowerCase()}">${escapeHtml(market.trendLabel)}</span>
          <h3>当前位置：${escapeHtml(market.positionLabel)}</h3>
          <p>距52周高点 ${market.distanceHigh52wPct.toFixed(1)}%，距MA50 ${market.distanceMa50Pct.toFixed(1)}%。</p>
        </div>
      </div>

      <div class="metrics-grid">
        <article><span>QQQ</span><strong>${money(market.price)}</strong><small class="${(market.changePct ?? 0) >= 0 ? "up" : "down"}">${signed(market.changePct)}</small></article>
        <article><span>RSI 14</span><strong>${market.rsi14.toFixed(1)}</strong><small>${market.rsi14 <= 32 ? "超卖观察" : market.rsi14 >= 68 ? "过热" : "中性区"}</small></article>
        <article><span>近20日</span><strong>${signed(market.return20Pct)}</strong><small>位置温度</small></article>
        <article><span>第一观察线</span><strong>${money(decision.gamble.firstGate)}</strong><small>站上仅重新评估</small></article>
      </div>

      <div class="chart-head">
        <div><strong>QQQ 日K技术图</strong><span>固定日K · 触摸K线查看OHLC</span></div>
        <div class="range-tabs" role="group" aria-label="日K显示范围">
          <button data-range="23" class="${state.range === 23 ? "selected" : ""}">近1月</button>
          <button data-range="66" class="${state.range === 66 ? "selected" : ""}">近3月</button>
          <button data-range="132" class="${state.range === 132 ? "selected" : ""}">近6月</button>
        </div>
      </div>
      <div class="legend">
        <span class="ma20">MA20</span><span class="ma50">MA50</span><span class="ma200">MA200</span>
        <span class="resistance">压力 ${market.resistance.toFixed(2)}</span>
        <span class="support">支撑 ${market.support.toFixed(2)}</span>
      </div>
      <div class="chart-shell">
        <canvas id="market-chart" class="market-chart" aria-label="QQQ日K、MACD与RSI图"></canvas>
        <div id="chart-tooltip" class="chart-tooltip" hidden></div>
      </div>

      <div class="technical-strip">
        <article><span>周期趋势</span><strong>${market.trend}</strong><small>${escapeHtml(market.trendLabel)}</small></article>
        <article><span>MACD</span><strong>${market.macd.toFixed(3)}</strong><small>信号 ${market.macdSignal.toFixed(3)}</small></article>
        <article><span>支撑</span><strong>${money(market.support)}</strong><small>近20日低点</small></article>
        <article><span>压力</span><strong>${money(market.resistance)}</strong><small>均线/近20日高点</small></article>
      </div>

      <details class="evidence">
        <summary>查看判断依据与数据质量</summary>
        <ul>
          <li>规则版本：${escapeHtml(decision.ruleVersion)}</li>
          <li>历史日K：${market.dataQuality.historyRows}根；图表显示${market.bars.length}根；质量：${market.dataQuality.confidence}</li>
          <li>行情快照：${escapeHtml(formatDateTime(generatedAt))}；最新完整日K：${escapeHtml(market.quoteTime ?? "—")}</li>
          <li>报价时点：${escapeHtml(market.quoteLabel)}</li>
          ${decision.guardrails.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        </ul>
      </details>
    </section>

    <section class="module-card catalyst" aria-labelledby="catalyst-title">
      <div class="section-heading">
        <div>
          <span>02 · 未来一个月催化 × 风险 × 动作</span>
          <h2 id="catalyst-title">催化——提前考虑未来风险</h2>
        </div>
        <small>${escapeHtml(calendar.verificationStatus)}<br />${escapeHtml(formatDateTime(calendar.verifiedAt))}</small>
      </div>

      <div class="catalyst-decision ${decision.catalyst.priority}">
        <div class="decision-kicker">
          <span>${escapeHtml(catalystBadge)}</span>
          <small>${decision.catalyst.nextEvent ? `${escapeHtml(decision.catalyst.nextEvent.title)} · ${decision.catalyst.nextEvent.hoursAway.toFixed(1)}小时后` : "未来72小时暂无四级事件"}</small>
        </div>
        <h3>${escapeHtml(decision.catalyst.actionTitle)}</h3>
        <p>${escapeHtml(decision.catalyst.actionDetail)}</p>
        <div class="expectation">
          <span>预期交易温度</span>
          <strong>${escapeHtml(decision.catalyst.expectationLabel)}</strong>
          <small>${escapeHtml(decision.catalyst.expectationDetail)}</small>
        </div>
        <div class="scenarios">
          ${decision.scenarios.map((scenario) => `<article><b>${escapeHtml(scenario.label)}</b><span>${escapeHtml(scenario.action)}</span></article>`).join("")}
        </div>
      </div>

      <div class="calendar-summary">
        <article><span>未来事件</span><strong>${calendar.eventCount}项</strong></article>
        <article><span>最高风险</span><strong>${Math.max(...calendar.weeks.map((week) => week.riskScore)) >= 4 ? "很高" : "高"}</strong></article>
        <article><span>本周重点</span><strong>${calendar.weeks[0]?.eventCount ?? 0}项</strong></article>
      </div>

      <nav class="week-tabs" aria-label="选择周">
        ${calendar.weeks
          .map(
            (week, index) => `
              <button data-week="${index}" class="${state.weekIndex === index ? "selected" : ""}">
                <span>${escapeHtml(weekRange(week))}</span>
                <strong>${escapeHtml(week.label)} · ${escapeHtml(week.riskLabel)}</strong>
              </button>`
          )
          .join("")}
      </nav>

      <div class="week-head">
        <div><h3>${escapeHtml(selectedWeek.label)} · ${escapeHtml(weekRange(selectedWeek))}</h3><p>${escapeHtml(selectedWeek.action)}</p></div>
        <span>${escapeHtml(selectedWeek.riskLabel)}风险</span>
      </div>
      <div class="event-list">${eventHtml}</div>
      <p class="methodology">${escapeHtml(calendar.methodology)} ${escapeHtml(calendar.timezoneNote)}</p>
    </section>
  `;

  document.body.classList.toggle("detail-view", detailView);
  pageTitle.textContent = detailView ? "QQQ 技术分析" : "今天的大局观";
  app.querySelector(".cloud-note")?.remove();

  const opportunity = app.querySelector(".opportunity");
  const headingMeta = opportunity.querySelector(".section-heading small");
  const sectionMeta = document.createElement("div");
  sectionMeta.className = "section-meta";
  headingMeta.before(sectionMeta);
  sectionMeta.append(headingMeta);
  headingMeta.insertAdjacentHTML(
    "afterbegin",
    `<b class="auto-state ${health.stale ? "stale" : ""}">${health.stale ? "快照偏旧" : "自动更新"}</b>`
  );

  if (detailView) {
    opportunity.classList.add("detail-focus");
    opportunity.insertAdjacentHTML("beforebegin", '<a class="detail-back" href="./">← 返回大局观</a>');
    opportunity.querySelector(".direct-answer").insertAdjacentHTML(
      "afterend",
      `<section class="data-gate ${health.stale ? "stale" : "ready"}" aria-live="polite">
        <div>
          <span>数据闸门</span>
          <strong>${health.stale ? "云端快照偏旧，请先用券商实时行情复核" : "云端快照已接通自动更新"}</strong>
        </div>
        <p>页面每60秒检查一次；本次生成于 ${escapeHtml(formatDateTime(generatedAt))}，最新完整日K为 ${escapeHtml(market.quoteTime ?? "—")}。公开行情为延时数据。</p>
      </section>`
    );
    opportunity.querySelector(".technical-strip").insertAdjacentHTML(
      "afterend",
      `<div class="analysis-grid">
        <article>
          <span>趋势结构</span>
          <strong>${escapeHtml(market.trendLabel)}</strong>
          <p>现价 ${money(market.price)}；MA20 ${latestBar?.ma20 == null ? "—" : money(latestBar.ma20)}，MA50 ${latestBar?.ma50 == null ? "—" : money(latestBar.ma50)}，MA200 ${latestBar?.ma200 == null ? "—" : money(latestBar.ma200)}。</p>
        </article>
        <article>
          <span>动能状态</span>
          <strong>RSI ${market.rsi14.toFixed(1)}</strong>
          <p>MACD ${market.macd.toFixed(3)} / 信号 ${market.macdSignal.toFixed(3)}；超买超卖只描述位置。</p>
        </article>
        <article>
          <span>关键价位</span>
          <strong>${money(market.support)} — ${money(market.resistance)}</strong>
          <p>第一观察线 ${money(decision.gamble.firstGate)}；站上只触发重新评估，不等于自动买入。</p>
        </article>
        <article>
          <span>风险动作</span>
          <strong>${escapeHtml(decision.gamble.exposure)}</strong>
          <p>${escapeHtml(decision.guardrails[0] ?? "按规则核对，不自动下单。")}</p>
        </article>
      </div>`
    );
    const evidence = opportunity.querySelector(".evidence");
    evidence.open = evidenceWasOpen;
    const qualityItem = evidence.querySelector("li:nth-child(2)");
    qualityItem?.insertAdjacentHTML(
      "afterend",
      "<li>结构质量只表示字段与历史样本完整，不代表实时行情。</li>"
    );
    app.querySelector(".catalyst")?.remove();
  } else {
    opportunity.classList.add("module-drilldown");
    opportunity.tabIndex = 0;
    opportunity.setAttribute("role", "link");
    opportunity.setAttribute("aria-label", "打开 QQQ 详细技术分析");
    opportunity
      .querySelectorAll(".chart-head, .legend, .chart-shell, .technical-strip, .evidence")
      .forEach((element) => element.remove());
    opportunity.insertAdjacentHTML(
      "beforeend",
      `<span class="detail-entry">
        <b>完整日K · MACD · RSI · 支撑压力 · 判断依据</b>
        <small>点击整个模块进入，一页看清技术结构</small>
      </span>`
    );
    sectionMeta.insertAdjacentHTML(
      "beforeend",
      '<span class="detail-link">查看详细技术分析 <b aria-hidden="true">→</b></span>'
    );
    const openDetail = () => {
      window.location.hash = "trendiq";
    };
    opportunity.addEventListener("click", (event) => {
      if (event.target.closest("a, button, details, input, canvas")) return;
      openDetail();
    });
    opportunity.addEventListener("keydown", (event) => {
      if (event.target !== opportunity || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      openDetail();
    });
  }

  app.insertAdjacentHTML(
    "beforeend",
    '<p class="footer-note">公开版使用 Nasdaq 延时报价；网页每60秒检查云端快照。技术分析只作决策辅助，不自动下单。</p>'
  );

  app.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.range = Number(button.dataset.range);
      render();
    });
  });
  app.querySelectorAll("[data-week]").forEach((button) => {
    button.addEventListener("click", () => {
      state.weekIndex = Number(button.dataset.week);
      render();
    });
  });
  if (detailView) drawChart(market, state.range);
}

function emaSeries(values, period) {
  if (!values.length) return [];
  const multiplier = 2 / (period + 1);
  const result = [values[0]];
  for (let index = 1; index < values.length; index += 1) {
    result.push(values[index] * multiplier + result[index - 1] * (1 - multiplier));
  }
  return result;
}

function rsiSeries(values, period = 14) {
  const output = Array(values.length).fill(null);
  if (values.length <= period) return output;
  let gains = 0;
  let losses = 0;
  for (let index = 1; index <= period; index += 1) {
    const change = values[index] - values[index - 1];
    gains += Math.max(change, 0);
    losses += Math.max(-change, 0);
  }
  let averageGain = gains / period;
  let averageLoss = losses / period;
  output[period] = averageLoss === 0 ? 100 : 100 - 100 / (1 + averageGain / averageLoss);
  for (let index = period + 1; index < values.length; index += 1) {
    const change = values[index] - values[index - 1];
    averageGain = (averageGain * (period - 1) + Math.max(change, 0)) / period;
    averageLoss = (averageLoss * (period - 1) + Math.max(-change, 0)) / period;
    output[index] =
      averageLoss === 0 ? 100 : 100 - 100 / (1 + averageGain / averageLoss);
  }
  return output;
}

function drawChart(market, range) {
  const canvas = document.querySelector("#market-chart");
  const tooltip = document.querySelector("#chart-tooltip");
  if (!canvas || !tooltip) return;
  const allBars = market.bars;
  const startIndex = Math.max(0, allBars.length - range);
  const bars = allBars.slice(startIndex);
  const closes = allBars.map((bar) => bar.close);
  const ema12 = emaSeries(closes, 12);
  const ema26 = emaSeries(closes, 26);
  const macdAll = closes.map((_, index) => ema12[index] - ema26[index]);
  const signalAll = emaSeries(macdAll, 9);
  const rsiAll = rsiSeries(closes);
  const macd = macdAll.slice(startIndex);
  const signal = signalAll.slice(startIndex);
  const rsi = rsiAll.slice(startIndex);

  const draw = () => {
    const width = Math.max(300, canvas.clientWidth);
    const height = canvas.clientHeight;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const left = 10;
    const right = 48;
    const top = 18;
    const bottom = 24;
    const gap = 18;
    const usable = height - top - bottom - gap * 2;
    const priceHeight = usable * 0.62;
    const macdHeight = usable * 0.21;
    const rsiHeight = usable * 0.17;
    const priceTop = top;
    const macdTop = priceTop + priceHeight + gap;
    const rsiTop = macdTop + macdHeight + gap;
    const plotWidth = width - left - right;
    const x = (index) => left + ((index + 0.5) / bars.length) * plotWidth;

    const priceValues = bars.flatMap((bar) => [
      bar.low,
      bar.high,
      ...(bar.ma20 === null ? [] : [bar.ma20]),
      ...(bar.ma50 === null ? [] : [bar.ma50]),
      ...(bar.ma200 === null ? [] : [bar.ma200])
    ]);
    priceValues.push(market.support, market.resistance);
    const priceMin = Math.min(...priceValues);
    const priceMax = Math.max(...priceValues);
    const pricePadding = Math.max((priceMax - priceMin) * 0.08, 1);
    const low = priceMin - pricePadding;
    const high = priceMax + pricePadding;
    const py = (value) => priceTop + ((high - value) / (high - low)) * priceHeight;

    context.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
    for (let line = 0; line <= 4; line += 1) {
      const value = high - ((high - low) * line) / 4;
      const y = priceTop + (priceHeight * line) / 4;
      context.strokeStyle = "rgba(154,190,176,.12)";
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(width - right, y);
      context.stroke();
      context.fillStyle = "#6f8880";
      context.fillText(value.toFixed(0), width - right + 5, y + 3);
    }

    const level = (value, color, label) => {
      const y = py(value);
      context.save();
      context.setLineDash([5, 5]);
      context.strokeStyle = color;
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(width - right, y);
      context.stroke();
      context.restore();
      context.fillStyle = color;
      context.font = "9px ui-monospace, monospace";
      context.fillText(label, left + 3, y - 4);
    };
    level(market.resistance, "#ff746d", `压力 ${market.resistance.toFixed(2)}`);
    level(market.support, "#4de1a3", `支撑 ${market.support.toFixed(2)}`);

    const candleWidth = Math.max(2, Math.min(8, (plotWidth / bars.length) * 0.62));
    bars.forEach((bar, index) => {
      const px = x(index);
      const color = bar.close >= bar.open ? "#4de1a3" : "#ff746d";
      context.strokeStyle = color;
      context.fillStyle = color;
      context.beginPath();
      context.moveTo(px, py(bar.high));
      context.lineTo(px, py(bar.low));
      context.stroke();
      const bodyTop = py(Math.max(bar.open, bar.close));
      const bodyBottom = py(Math.min(bar.open, bar.close));
      context.fillRect(
        px - candleWidth / 2,
        bodyTop,
        candleWidth,
        Math.max(1.5, bodyBottom - bodyTop)
      );
    });

    const averageLine = (key, color) => {
      context.strokeStyle = color;
      context.lineWidth = 1.5;
      context.beginPath();
      let started = false;
      bars.forEach((bar, index) => {
        const value = bar[key];
        if (value === null) return;
        if (!started) {
          context.moveTo(x(index), py(value));
          started = true;
        } else {
          context.lineTo(x(index), py(value));
        }
      });
      context.stroke();
    };
    averageLine("ma20", "#ffc45f");
    averageLine("ma50", "#70a8ff");
    averageLine("ma200", "#bd8cff");

    context.fillStyle = "#9cb0a8";
    context.font = "10px ui-monospace, monospace";
    context.fillText("MACD (12,26,9)", left, macdTop - 5);
    const macdExtent = Math.max(0.01, ...macd.flatMap((value, index) => [Math.abs(value), Math.abs(signal[index])]));
    const my = (value) => macdTop + macdHeight / 2 - (value / macdExtent) * (macdHeight * 0.42);
    context.strokeStyle = "rgba(154,190,176,.18)";
    context.beginPath();
    context.moveTo(left, my(0));
    context.lineTo(width - right, my(0));
    context.stroke();
    macd.forEach((value, index) => {
      const histogram = value - signal[index];
      context.fillStyle = histogram >= 0 ? "rgba(77,225,163,.58)" : "rgba(255,116,109,.58)";
      const y = my(histogram);
      context.fillRect(x(index) - Math.max(1, candleWidth / 2), Math.min(my(0), y), Math.max(2, candleWidth), Math.abs(my(0) - y));
    });
    const line = (values, color, mapper) => {
      context.strokeStyle = color;
      context.lineWidth = 1.4;
      context.beginPath();
      values.forEach((value, index) => {
        if (value === null) return;
        if (index === 0) context.moveTo(x(index), mapper(value));
        else context.lineTo(x(index), mapper(value));
      });
      context.stroke();
    };
    line(macd, "#70a8ff", my);
    line(signal, "#ffc45f", my);

    context.fillStyle = "#9cb0a8";
    context.fillText("RSI (14)", left, rsiTop - 5);
    const ry = (value) => rsiTop + ((100 - value) / 100) * rsiHeight;
    [
      [70, "#ff746d"],
      [30, "#4de1a3"]
    ].forEach(([value, color]) => {
      context.save();
      context.setLineDash([4, 4]);
      context.strokeStyle = color;
      context.beginPath();
      context.moveTo(left, ry(value));
      context.lineTo(width - right, ry(value));
      context.stroke();
      context.restore();
      context.fillStyle = color;
      context.fillText(String(value), width - right + 6, ry(value) + 3);
    });
    line(rsi, "#ffc45f", ry);

    context.fillStyle = "#71877f";
    context.textAlign = "center";
    context.font = "9px ui-monospace, monospace";
    [0, Math.floor((bars.length - 1) / 2), bars.length - 1].forEach((index) => {
      context.fillText(bars[index].date.slice(5), x(index), height - 7);
    });
    context.textAlign = "left";
  };

  const locate = (clientX) => {
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - bounds.left - 10) / (bounds.width - 58)));
    const index = Math.min(bars.length - 1, Math.max(0, Math.floor(ratio * bars.length)));
    const bar = bars[index];
    tooltip.innerHTML = `<b>${escapeHtml(bar.date)}</b><span>开 ${bar.open.toFixed(2)} · 高 ${bar.high.toFixed(2)} · 低 ${bar.low.toFixed(2)} · 收 ${bar.close.toFixed(2)}</span>`;
    tooltip.hidden = false;
  };
  canvas.addEventListener("pointermove", (event) => locate(event.clientX));
  canvas.addEventListener("pointerdown", (event) => locate(event.clientX));
  canvas.addEventListener("pointerleave", () => {
    tooltip.hidden = true;
  });
  draw();
  chartObserver?.disconnect();
  chartObserver = new ResizeObserver(draw);
  chartObserver.observe(canvas);
}

async function load({ silent = false } = {}) {
  if (!silent) {
    refreshButton.disabled = true;
    refreshButton.textContent = "复核中";
  }
  try {
    const response = await fetch(`./data/dashboard.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`数据文件返回 HTTP ${response.status}`);
    const payload = await response.json();
    if (!payload?.market?.bars?.length || !payload?.decision || !payload?.calendar?.weeks) {
      throw new Error("数据快照结构不完整");
    }
    state.payload = payload;
    render();
    maybeAlert();
  } catch (error) {
    if (!state.payload) {
      app.innerHTML = `
        <div class="error-card">
          <b>公开行情快照暂时没有返回</b>
          <span>${escapeHtml(error instanceof Error ? error.message : "未知错误")}</span>
          <button id="retry-button" type="button">重新加载</button>
        </div>`;
      document.querySelector("#retry-button")?.addEventListener("click", load);
    }
  } finally {
    if (!silent) {
      refreshButton.disabled = false;
      refreshButton.textContent = "刷新";
    }
  }
}

alertButton.addEventListener("click", async () => {
  state.alertsEnabled = !state.alertsEnabled;
  localStorage.setItem("anli-pages-alerts", state.alertsEnabled ? "1" : "0");
  updateAlertButton();
  if (
    state.alertsEnabled &&
    "Notification" in window &&
    window.isSecureContext &&
    Notification.permission === "default"
  ) {
    try {
      await Notification.requestPermission();
    } catch {
      // 页内提醒仍可用。
    }
  }
  if (state.alertsEnabled && state.payload) {
    showReminder(state.payload.decision.alert.title, state.payload.decision.alert.body);
  }
});
refreshButton.addEventListener("click", () => load());
reminderClose.addEventListener("click", () => {
  reminder.hidden = true;
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") load({ silent: true });
});
updateAlertButton();
window.addEventListener("hashchange", () => {
  if (state.payload) render();
});
load();
setInterval(() => load({ silent: true }), 60_000);
