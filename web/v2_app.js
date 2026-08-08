(function () {
  "use strict";

  const state = {
    data: null,
    currentView: "decision",
    playbookFilter: "ALL",
    search: "",
    drawerSymbol: null,
  };

  const app = document.getElementById("app");
  const sourcePill = document.getElementById("sourcePill");
  const refreshButton = document.getElementById("refreshButton");
  const drawer = document.getElementById("detailDrawer");
  const drawerContent = document.getElementById("drawerContent");
  const drawerBackdrop = document.getElementById("drawerBackdrop");
  const drawerClose = document.getElementById("drawerClose");
  const drawerEyebrow = document.getElementById("drawerEyebrow");
  const toast = document.getElementById("toast");

  const e = value => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const n = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const fmt = (value, digits = 1) => {
    const parsed = n(value);
    return parsed === null ? "—" : parsed.toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  };

  const price = value => {
    const parsed = n(value);
    if (parsed === null) return "—";
    const digits = parsed >= 100 ? 2 : parsed >= 10 ? 2 : 3;
    return parsed.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  };

  const pct = value => {
    const parsed = n(value);
    if (parsed === null) return "—";
    return `${parsed > 0 ? "+" : ""}${fmt(parsed, 2)}%`;
  };

  const directionClass = value => n(value) > 0 ? "positive" : n(value) < 0 ? "negative" : "";
  const statusClass = value => ({ PASS: "pass", BLOCK: "block", MISSING: "missing", CAUTION: "caution" }[value] || "caution");
  const biasClass = value => value === "BULLISH" || value === "UP" ? "up" : value === "BEARISH" || value === "DOWN" ? "down" : "neutral";

  const phaseLabels = [
    ["DISCOVERY", "发现催化"],
    ["EXPECTATION_BUILD", "预期形成"],
    ["PRE_EVENT_RISK", "事前风险"],
    ["FACT_RELEASED", "事实公布"],
    ["POST_EVENT_DISCOVERY", "价格发现"],
    ["POST_EVENT_TREND", "事件趋势"],
  ];

  const playbookCopy = {
    LEADERSHIP_PULLBACK: "趋势仍在，等待缩量回踩后的放量收复。",
    EXPECTATION_BUILD: "催化剂前只交易预期差，不追逐已经定价的故事。",
    POST_EVENT_CONFIRMATION: "先看实际与指引，再看开盘区间和事件VWAP。",
    WASHOUT_RECOVERY: "先核验基本面，再等待2–3日结构企稳。",
    NO_TRADE: "不属于任何高质量剧本，保持现金也是决策。",
  };

  function showToast(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => { toast.hidden = true; }, 2600);
  }

  async function jsonFetch(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try { message = (await response.json()).error || message; } catch (_) { /* noop */ }
      throw new Error(message);
    }
    return response.json();
  }

  async function fetchDashboard() {
    try {
      return await jsonFetch(`/api/v2/dashboard?t=${Date.now()}`);
    } catch (apiError) {
      try {
        const payload = await jsonFetch(`./data/dashboard-v2.json?t=${Date.now()}`);
        payload.meta = payload.meta || {};
        payload.meta.static_public_site = true;
        return payload;
      } catch (_) {
        throw apiError;
      }
    }
  }

  async function fetchSymbol(symbol) {
    try {
      return await jsonFetch(`/api/v2/symbol/${encodeURIComponent(symbol)}?t=${Date.now()}`);
    } catch (apiError) {
      try {
        return await jsonFetch(`./data/symbols/${encodeURIComponent(symbol)}.json?t=${Date.now()}`);
      } catch (_) {
        throw apiError;
      }
    }
  }

  async function loadDashboard(userInitiated = false) {
    refreshButton.classList.add("spinning");
    try {
      state.data = await fetchDashboard();
      render();
      if (userInitiated) showToast("已读取最新可用快照");
    } catch (error) {
      app.innerHTML = `
        <section class="loading-screen">
          <div class="state-orb blocked">!</div>
          <strong>2.0 暂时没有可验证数据</strong>
          <span>${e(error.message)}</span>
          <button class="filter-chip" id="retryButton">重新连接</button>
        </section>`;
      sourcePill.className = "source-pill blocked";
      sourcePill.querySelector("span").textContent = "数据不可用";
      document.getElementById("retryButton")?.addEventListener("click", () => loadDashboard(true));
    } finally {
      refreshButton.classList.remove("spinning");
    }
  }

  function svgLine(values, className = "chart-line") {
    const clean = values.map(n).filter(value => value !== null);
    if (clean.length < 2) return `<div class="empty-state">图表数据不足</div>`;
    const width = 600;
    const height = 170;
    const min = Math.min(...clean);
    const max = Math.max(...clean);
    const span = max - min || 1;
    const points = clean.map((value, index) => {
      const x = index / (clean.length - 1) * width;
      const y = height - 12 - ((value - min) / span * (height - 24));
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
    const area = `0,${height} ${points} ${width},${height}`;
    return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="价格趋势图">
      <defs><linearGradient id="lineFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6ed8ff" stop-opacity=".42"/><stop offset="1" stop-color="#6ed8ff" stop-opacity="0"/></linearGradient></defs>
      <line class="chart-grid" x1="0" y1="42" x2="600" y2="42"/><line class="chart-grid" x1="0" y1="85" x2="600" y2="85"/><line class="chart-grid" x1="0" y1="128" x2="600" y2="128"/>
      <polygon class="chart-area" points="${area}"/><polyline class="${className}" points="${points}"/>
    </svg>`;
  }

  function chartValues(timeframe) {
    const chart = timeframe?.chart;
    if (!Array.isArray(chart)) return [];
    return chart.slice(-110).map(bar => bar?.c ?? bar?.close).filter(value => n(value) !== null);
  }

  function qualityBanner(data) {
    const q = data.data_quality;
    const primary = q.status === "BLOCKED"
      ? "数据闸门已阻断所有研究信号"
      : `${q.provider} · ${q.official_realtime ? "官方实时" : "公开延时/静态快照"}`;
    const secondary = `截至 ${humanTime(q.as_of)} · 快照年龄 ${fmt(q.age_hours, 1)} 小时 · ${q.execution_ready ? "具备执行数据" : "执行前需券商实时确认"}`;
    return `<section class="quality-banner ${q.status === "BLOCKED" ? "blocked" : ""}">
      <div class="quality-icon">${q.status === "BLOCKED" ? "×" : "i"}</div>
      <div><strong>${e(primary)}</strong><p>${e(secondary)}</p></div>
      <button class="text-button" data-detail="quality">查看质量闸门 →</button>
    </section>`;
  }

  function humanTime(value) {
    if (!value) return "未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function marketPanel(data) {
    const gate = data.market_gate;
    const breadth = gate.breadth || {};
    const qqq = gate.assets?.QQQ || {};
    const tnx = gate.assets?.["^TNX"] || {};
    const stateClass = gate.state === "RISK_ON" ? "risk-on" : gate.state === "SELECTIVE" ? "" : gate.state.toLowerCase().replace("_", "-");
    return `<article class="panel market-panel clickable" data-detail="market">
      <div class="market-panel-top">
        <div class="market-state"><div class="state-orb ${stateClass}">◆</div><div><h3>${e(gate.label)}</h3><p>${e(gate.regime_label)} · ${e(gate.position_label || "位置待确认")}</p></div></div>
        <div class="market-score"><strong>${fmt(gate.market_score, 0)}</strong><span>MARKET SCORE</span></div>
      </div>
      <div class="metric-strip">
        <div class="metric-box"><label>MA50宽度</label><strong>${fmt(breadth.above_ma50_pct, 1)}%</strong><small>${fmt(breadth.sample_size, 0)}只样本</small></div>
        <div class="metric-box"><label>QQQ / MA50</label><strong class="${directionClass(qqq.distance_ma50_pct)}">${pct(qqq.distance_ma50_pct)}</strong><small>${qqq.above_ma50 ? "趋势上方" : "趋势下方"}</small></div>
        <div class="metric-box"><label>10Y日变化</label><strong class="${directionClass(-n(tnx.day_change_pct))}">${pct(tnx.day_change_pct)}</strong><small>成长估值压力</small></div>
        <div class="metric-box"><label>风险上限</label><strong>${e(gate.allocation_cap_pct)}%</strong><small>模型风险预算上限</small></div>
      </div>
      <div class="gate-action"><p>${e(gate.action)}</p><span>点击查看完整证据 →</span></div>
    </article>`;
  }

  function qqqPanel(data) {
    const q = data.qqq;
    const oneDay = q.timeframes?.["1D"];
    return `<article class="panel qqq-panel clickable" data-detail="qqq">
      <div class="qqq-top"><div class="ticker-title"><strong>QQQ</strong><span>$${price(q.price)}</span></div><span class="signal-badge ${biasClass(q.bias)}">${e(q.decision_label)}</span></div>
      <div class="qqq-chart">${svgLine(chartValues(oneDay))}</div>
      <div class="qqq-foot"><div class="level-box"><label>结构支撑</label><strong>$${price(q.support)}</strong></div><div class="level-box"><label>结构压力</label><strong>$${price(q.resistance)}</strong></div></div>
      <p class="qqq-decision">${e(q.next_condition || q.reasoning?.summary || "等待多周期共振")}</p>
    </article>`;
  }

  const radarClass = value => ({ READY: "pass", FORMING: "caution", EVIDENCE_GAP: "missing", WATCH: "caution", BLOCKED: "block", EMPTY: "neutral" }[value] || "neutral");

  function radarRows(data) {
    return data.playbook_radar?.playbooks || [];
  }

  function decisionStackHtml(stack, compact = false) {
    return `<div class="decision-stack ${compact ? "compact" : ""}">${(stack || []).map((item, index) => `<div class="stack-node ${statusClass(item.status)}">
      <div class="stack-node-top"><b>0${index + 1}</b><span class="status-badge ${statusClass(item.status)}">${e(item.status)}</span></div>
      <strong>${e(item.label)}</strong><p>${e(item.value)}</p>${compact ? "" : `<small>${e(item.evidence || item.detail || "")}</small><em>${e(item.next_condition || "")}</em>`}
    </div>`).join("")}</div>`;
  }

  function commandCenter(data) {
    const brief = data.command_brief || {};
    const risk = brief.risk_budget || {};
    const constraint = brief.dominant_constraint;
    return `<article class="panel command-center">
      <div class="command-head"><div><span class="eyebrow">TODAY'S COMMAND</span><h2>${e(brief.verdict || data.market_gate.label)}</h2><p>${e(brief.posture || data.market_gate.action)}</p></div><div class="command-cap"><strong>${e(brief.risk_cap_pct ?? data.market_gate.allocation_cap_pct)}%</strong><span>模型风险上限</span></div></div>
      <div class="command-stats"><div><label>研究就绪</label><strong>${fmt(brief.ready_count,0)}</strong></div><div><label>等待触发</label><strong>${fmt(brief.waiting_count,0)}</strong></div><div><label>证据缺口</label><strong>${fmt(brief.evidence_gap_count,0)}</strong></div><div><label>主约束</label><strong>${e(constraint?.label || "逐只核验")}</strong></div></div>
      ${decisionStackHtml(brief.stack)}
      <div class="risk-strip"><span>单笔研究风险 <b>${e(risk.risk_per_trade_pct)}%</b></span><span>组合开放风险 <b>${e(risk.max_open_risk_pct)}%</b></span><span>单仓市值上限 <b>${e(risk.max_position_value_pct)}%</b></span><span>最多持仓 <b>${e(risk.max_positions)}</b></span></div>
    </article>`;
  }

  function radarPipeline(data) {
    const steps = data.playbook_radar?.pipeline || ["市场闸门", "唯一剧本", "必要证据", "价格触发", "券商确认", "持仓管理"];
    return `<div class="radar-pipeline">${steps.map((step, index) => `<div><b>0${index + 1}</b><span>${e(step)}</span></div>`).join("")}</div>`;
  }

  function playbookCards(data, interactive = true) {
    const rows = radarRows(data);
    const codes = ["LEADERSHIP_PULLBACK", "EXPECTATION_BUILD", "POST_EVENT_CONFIRMATION", "WASHOUT_RECOVERY"];
    return `<div class="playbook-grid">${codes.map((code, index) => {
      const radar = rows.find(item => item.code === code) || {};
      const label = radar.label || data.symbols.find(item => item.playbook.code === code)?.playbook.label || ({
        LEADERSHIP_PULLBACK: "强势龙头回踩",
        EXPECTATION_BUILD: "买预期",
        POST_EVENT_CONFIRMATION: "财报后确认",
        WASHOUT_RECOVERY: "超跌修复",
      })[code];
      const count = radar.candidate_count ?? data.playbook_counts?.[code] ?? 0;
      return `<button class="playbook-card ${state.playbookFilter === code ? "active" : ""}" data-playbook="${code}" data-code="${code}" ${interactive ? "" : "tabindex='-1'"}>
        <div class="playbook-card-top"><span class="eyebrow">PLAYBOOK 0${index + 1}</span><strong class="playbook-count">${fmt(count, 0)}</strong></div>
        <div class="playbook-state"><span class="status-badge ${radarClass(radar.state)}">${e(radar.state_label || "等待评估")}</span><small>证据 ${fmt(radar.average_completion_pct,0)}%</small></div>
        <h3>${e(label)}</h3><p>${e(radar.thesis || playbookCopy[code])}</p>
        <div class="playbook-blocker">主约束：${e(radar.primary_bottleneck?.label || (count ? "等待价格触发" : "暂无候选"))}</div>
      </button>`;
    }).join("")}</div>`;
  }

  function playbookRadarGrid(data) {
    const rows = radarRows(data).filter(row => state.playbookFilter === "ALL" || row.code === state.playbookFilter);
    if (!rows.length) return `<div class="empty-state">没有可用的剧本雷达数据</div>`;
    return `<div class="scenario-grid">${rows.map((row, index) => `<article class="scenario-card" data-code="${e(row.code)}">
      <div class="scenario-head"><div><span class="eyebrow">SCENARIO 0${index + 1}</span><h2>${e(row.label)}</h2></div><span class="status-badge ${radarClass(row.state)}">${e(row.state_label)}</span></div>
      <p class="scenario-thesis">${e(row.thesis)}</p>
      <div class="scenario-metrics"><div><label>候选</label><strong>${fmt(row.candidate_count,0)}</strong></div><div><label>研究就绪</label><strong>${fmt(row.ready_count,0)}</strong></div><div><label>等待触发</label><strong>${fmt(row.wait_count,0)}</strong></div><div><label>证据缺口</label><strong>${fmt(row.evidence_gap_count,0)}</strong></div></div>
      <div class="readiness-bar"><i style="width:${Math.max(0, Math.min(100, n(row.average_completion_pct) || 0))}%"></i></div>
      <div class="scenario-focus"><label>当前最重要的阻力</label><strong>${e(row.primary_bottleneck?.label || "暂无候选")}</strong><p>${e(row.primary_bottleneck?.next_condition || row.trigger)}</p></div>
      <div class="scenario-path">${(row.decision_path || []).map(step => `<div><b>0${e(step.step)}</b><span>${e(step.label)}</span><p>${e(step.detail)}</p></div>`).join("")}</div>
      <div class="scenario-actions"><button class="filter-chip" data-playbook="${e(row.code)}">筛选候选</button><button class="text-button" data-playbook-detail="${e(row.code)}">打开完整剧本 →</button></div>
    </article>`).join("")}</div>`;
  }

  function eventCommand(data) {
    const radar = data.event_radar || {};
    const next = radar.next_event;
    return `<article class="panel event-command">
      <div class="event-command-main"><div><span class="eyebrow">EVENT COMMAND</span><h2>${next ? e(next.title) : "等待已核验事件"}</h2><p>${e(radar.policy)}</p></div><div class="event-countdown"><strong>${next ? e(next.days_to_event) : "—"}</strong><span>${next ? "天后" : "无事件"}</span></div></div>
      <div class="command-stats"><div><label>未来事件</label><strong>${fmt(radar.upcoming_count,0)}</strong></div><div><label>7天内</label><strong>${fmt(radar.within_7d_count,0)}</strong></div><div><label>最高重要度</label><strong>${fmt(radar.critical_count,0)}</strong></div><div><label>已核验</label><strong>${fmt(radar.verified_count,0)}</strong></div></div>
    </article>`;
  }

  function eventLifecycle(data) {
    const radar = data.event_radar || {};
    return `<div class="event-life-grid">${(radar.lifecycle || []).map((step, index) => `<article><div><b>0${index + 1}</b><span>${e(step.window)}</span></div><h3>${e(step.label)}</h3><p>${e(step.action)}</p><small>必须证据：${e(step.required)}</small><em>${fmt(radar.phase_counts?.[step.code] || 0,0)} 只处于此阶段</em></article>`).join("")}</div>`;
  }

  function expectationEvidence(data) {
    const components = data.event_radar?.expectation_components || [];
    return `<div class="expectation-grid">${components.map((item, index) => `<article><label>COMPONENT 0${index + 1}</label><strong>${e(item.label)}</strong><p>${e(item.question)}</p></article>`).join("")}</div>`;
  }
  function candidateRows(symbols, limit) {
    const actionableOrder = { BROKER_CONFIRMATION: 7, WAIT_TRIGGER: 6, EVIDENCE_INSUFFICIENT: 5, PRE_EVENT_RISK: 4, NO_TRADE: 2, MARKET_BLOCKED: 1, DATA_BLOCKED: 0 };
    const rows = symbols
      .filter(item => state.playbookFilter === "ALL" || item.playbook.code === state.playbookFilter)
      .sort((a, b) => (actionableOrder[b.entry.state] || 0) - (actionableOrder[a.entry.state] || 0) || b.evidence_completion_pct - a.evidence_completion_pct)
      .slice(0, limit || 999);
    if (!rows.length) return `<div class="empty-state">当前筛选没有股票</div>`;
    return rows.map(item => `<button class="candidate-row" data-symbol="${e(item.symbol)}">
      <div class="symbol-cell"><strong>${e(item.symbol)}</strong><small>${e(item.name)} · ${e(item.sector)}</small></div>
      <div class="playbook-cell"><span>${e(item.playbook.label)}</span><small title="${e(item.next_best_action)}">${e(item.event_phase.label)} · ${e(item.primary_constraint?.label || "等待触发")}</small></div>
      <div class="numeric price-cell">$${price(item.price)}</div>
      <div class="numeric change-cell ${directionClass(item.day_change_pct)}">${pct(item.day_change_pct)}</div>
      <div class="status-cell"><span class="status-badge ${entryClass(item.entry.state)}">${e(item.entry.label)}</span></div>
      <div class="arrow">›</div>
    </button>`).join("");
  }

  function entryClass(entryState) {
    if (entryState === "ENTRY_READY" || entryState === "BROKER_CONFIRMATION") return "pass";
    if (entryState === "DATA_BLOCKED" || entryState === "MARKET_BLOCKED") return "block";
    return "missing";
  }

  function candidateTable(data, limit) {
    return `<div class="candidate-list"><div class="candidate-header"><span>股票</span><span>交易剧本</span><span>价格</span><span>今日</span><span>状态</span><span></span></div>${candidateRows(data.symbols, limit)}</div>`;
  }

  function eventRows(events, limit) {
    const rows = events.filter(item => n(item.days_to_event) >= -1).slice(0, limit || 999);
    if (!rows.length) return `<div class="empty-state">未来四周没有已核验事件</div>`;
    return rows.map((event, index) => {
      const date = new Date(event.at_cn || event.at);
      const dateText = Number.isNaN(date.getTime()) ? event.at_cn || event.at : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
      const importance = Math.max(0, Math.min(4, Number(event.importance) || 0));
      return `<button class="event-row ${importance >= 4 ? "critical" : ""}" data-event-index="${index}">
        <i class="event-dot"></i><div class="event-time"><strong>${e(dateText)}</strong><small>北京时间 · ${e(event.week_label || "")}</small></div>
        <div class="event-title"><strong>${e(event.title)}</strong><small>${e(event.category)} · ${e(event.verification)}</small></div>
        <div class="importance">${[1,2,3,4].map(i => `<i class="${i <= importance ? "on" : ""}"></i>`).join("")}</div>
      </button>`;
    }).join("");
  }

  function sellFactPanel(data, compact = false) {
    const rows = compact ? data.sell_fact_rules.slice(0, 4) : data.sell_fact_rules;
    return `<article class="panel fact-panel"><h3>卖事实矩阵</h3><p>不是看到 Beat 就卖，而是判断事实是否超过市场已经定价的预期。</p>${rows.map(rule => `<div class="fact-rule ${String(rule.severity).toLowerCase()}"><strong>${e(rule.condition)}</strong><span>${e(rule.action)}</span></div>`).join("")}</article>`;
  }

  function renderDecision(data) {
    return `<section class="view ${state.currentView === "decision" ? "active" : ""}" data-view-panel="decision">
      <div class="section-head"><div><span class="eyebrow">MARKET COMMAND</span><h1>大局观</h1></div></div>
      ${commandCenter(data)}
      <div class="section-head"><div><span class="eyebrow">MARKET STRUCTURE</span><h2>指数、宽度与多周期结构</h2></div><p>点击模块查看完整证据、触发与否决条件</p></div>
      <div class="macro-grid">${marketPanel(data)}${qqqPanel(data)}</div>
      <div class="section-head"><div><span class="eyebrow">PLAYBOOK MATRIX</span><h2>今天有哪些有效剧本</h2></div><p>四套规则互不混用，只在各自剧本内排名</p></div>
      ${playbookCards(data)}
      <div class="section-head"><div><span class="eyebrow">DECISION QUEUE</span><h2>最接近触发的研究候选</h2></div><p>点击股票进入完整技术、事件、证据与进出场分析</p></div>
      <div class="candidate-layout candidate-layout-single">${candidateTable(data, 10)}</div>
    </section>`;
  }

  function renderPlaybooks(data) {
    const summary = data.playbook_radar?.summary || {};
    return `<section class="view ${state.currentView === "playbooks" ? "active" : ""}" data-view-panel="playbooks">
      <div class="section-head"><div><span class="eyebrow">SCENARIO OPERATING SYSTEM</span><h1>交易剧本雷达</h1></div><button class="filter-chip ${state.playbookFilter === "ALL" ? "active" : ""}" data-playbook="ALL">查看全部</button></div>
      <div class="radar-summary"><div><label>有候选剧本</label><strong>${fmt(summary.active_playbooks,0)}</strong></div><div><label>研究就绪</label><strong>${fmt(summary.ready_playbooks,0)}</strong></div><div><label>触发形成中</label><strong>${fmt(summary.forming_playbooks,0)}</strong></div><div><label>证据缺口</label><strong>${fmt(summary.evidence_gap_playbooks,0)}</strong></div><div><label>明确不交易</label><strong>${fmt(summary.no_trade_count,0)}</strong></div></div>
      ${radarPipeline(data)}
      <div class="section-head"><div><h2>四套剧本的完整决策路径</h2></div><p>没有主观概率；只展示已满足、被阻断和缺失的必要证据</p></div>
      ${playbookRadarGrid(data)}
      <div class="section-head"><div><h2>${state.playbookFilter === "ALL" ? "全部剧本候选" : e(radarRows(data).find(item => item.code === state.playbookFilter)?.label || "剧本候选")}</h2></div><p>证据完成度是规则一致度，不是胜率</p></div>
      ${candidateTable(data)}
    </section>`;
  }

  function renderEvents(data) {
    return `<section class="view ${state.currentView === "events" ? "active" : ""}" data-view-panel="events">
      <div class="section-head"><div><span class="eyebrow">EXPECTATION LIFECYCLE</span><h1>事件与预期</h1></div><p>北京时间 · 官方来源优先</p></div>
      ${eventCommand(data)}
      <div class="section-head"><div><h2>从发现催化到卖事实</h2></div><p>每个阶段使用不同证据和仓位纪律</p></div>
      ${eventLifecycle(data)}
      <div class="section-head"><div><h2>已核验事件与卖事实矩阵</h2></div><p>事件日期不是利好；事实必须超过已经定价的预期</p></div>
      <div class="event-grid"><article class="panel timeline-panel"><div class="timeline">${eventRows(data.events)}</div></article>${sellFactPanel(data)}</div>
      <div class="section-head"><div><h2>预期差的六项必要证据</h2></div><p>任何一项缺失都不会被AI猜测填充</p></div>
      ${expectationEvidence(data)}
    </section>`;
  }

  function renderUniverse(data) {
    const query = state.search.trim().toUpperCase();
    const symbols = data.symbols.filter(item => !query || item.symbol.includes(query) || String(item.name).toUpperCase().includes(query) || String(item.sector).includes(state.search.trim()));
    const filtered = symbols.filter(item => state.playbookFilter === "ALL" || item.playbook.code === state.playbookFilter);
    return `<section class="view ${state.currentView === "universe" ? "active" : ""}" data-view-panel="universe">
      <div class="section-head"><div><span class="eyebrow">FULL DECISION UNIVERSE</span><h1>全部个股</h1></div><label class="search-box"><input id="stockSearch" type="search" placeholder="代码、公司、行业" value="${e(state.search)}" autocomplete="off"></label></div>
      <div class="filters">
        ${["ALL", "LEADERSHIP_PULLBACK", "EXPECTATION_BUILD", "POST_EVENT_CONFIRMATION", "WASHOUT_RECOVERY", "NO_TRADE"].map(code => `<button class="filter-chip ${state.playbookFilter === code ? "active" : ""}" data-playbook="${code}">${code === "ALL" ? "全部" : e(data.symbols.find(item => item.playbook.code === code)?.playbook.label || playbookCopy[code]?.split("，")[0] || code)}</button>`).join("")}
      </div>
      <div class="section-head"><div><h2>${filtered.length} 只股票</h2></div><p>每张卡片都显示剧本、证据、主约束和唯一下一步</p></div>
      <div class="universe-grid">${filtered.map(stockCard).join("") || `<div class="empty-state">没有符合条件的股票</div>`}</div>
    </section>`;
  }

  function stockCard(item) {
    const summary = item.evidence_summary || {};
    const constraint = item.primary_constraint;
    return `<button class="stock-card detailed" data-symbol="${e(item.symbol)}">
      <div class="stock-card-top"><h3>${e(item.symbol)}<small>${e(item.name)} · ${e(item.sector)}</small></h3><div class="stock-price">$${price(item.price)}<small class="${directionClass(item.day_change_pct)}">${pct(item.day_change_pct)}</small></div></div>
      <div class="stock-card-bottom"><span class="playbook-badge">${e(item.playbook.label)}</span><span class="status-badge ${entryClass(item.entry.state)}">${e(item.entry.label)}</span></div>
      <div class="stock-evidence"><span><i class="pass" style="width:${Math.max(0, Math.min(100, n(item.evidence_completion_pct) || 0))}%"></i></span><small>${fmt(summary.passed,0)}通过 · ${fmt(summary.blocked,0)}阻断 · ${fmt(summary.missing,0)}缺失</small></div>
      <div class="stock-constraint"><label>${constraint ? "主约束" : "下一触发"}</label><strong>${e(constraint?.label || item.event_phase.label)}</strong><p>${e(item.next_best_action)}</p></div>
      <div class="stock-card-metrics"><span>MA50 ${pct(item.distance_ma50_pct)}</span><span>20日回撤 ${pct(item.drawdown20_pct)}</span><span>RSI ${fmt(item.rsi14,1)}</span><span>量比 ${fmt(item.volume_ratio,2)}</span></div>
    </button>`;
  }
  function render() {
    const data = state.data;
    sourcePill.className = `source-pill ${data.data_quality.status === "BLOCKED" ? "blocked" : "ready"}`;
    sourcePill.querySelector("span").textContent = `${data.data_quality.provider} · ${humanTime(data.data_quality.as_of)}`;
    app.innerHTML = qualityBanner(data) + renderDecision(data) + renderPlaybooks(data) + renderEvents(data) + renderUniverse(data);
    syncNavigation();
    bindSearch();
  }

  function bindSearch() {
    const input = document.getElementById("stockSearch");
    if (!input) return;
    input.addEventListener("input", event => {
      state.search = event.target.value;
      const start = event.target.selectionStart;
      render();
      const next = document.getElementById("stockSearch");
      next?.focus();
      next?.setSelectionRange(start, start);
    });
  }

  function syncNavigation() {
    document.querySelectorAll("[data-view]").forEach(button => {
      button.classList.toggle("active", button.dataset.view === state.currentView);
    });
    document.querySelectorAll("[data-view-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.viewPanel === state.currentView);
    });
  }

  function switchView(view) {
    state.currentView = view;
    if (view !== "playbooks" && view !== "universe") state.playbookFilter = "ALL";
    if (state.data) render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openDrawer(eyebrow, html) {
    drawerEyebrow.textContent = eyebrow;
    drawerContent.innerHTML = html;
    drawerBackdrop.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => drawer.classList.add("open"));
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    drawerBackdrop.hidden = true;
    document.body.style.overflow = "";
    state.drawerSymbol = null;
  }

  function openInfo(type) {
    const data = state.data;
    if (type === "market") {
      const gate = data.market_gate;
      openDrawer("MARKET GATE · 2.0", `<div class="drawer-title"><h2>${e(gate.label)}<small>${e(gate.regime_label)} · ${e(gate.position_label)}</small></h2><div class="drawer-price">${fmt(gate.market_score, 0)}<small>市场环境分</small></div></div>
        <div class="drawer-badges"><span class="status-badge ${gate.state === "RISK_ON" ? "pass" : gate.state === "SELECTIVE" ? "missing" : "block"}">${e(gate.state)}</span><span class="playbook-badge">风险上限 ${e(gate.allocation_cap_pct)}%</span><span class="playbook-badge">${e(data.data_quality.latency)}</span></div>
        <section class="detail-section"><h3>全局五层决策栈 <span>数据 → 大盘 → QQQ → 行业 → 个股</span></h3>${decisionStackHtml(data.command_brief?.stack)}</section>
        <section class="detail-section"><h3>市场证据链 <span>指数 → 宽度 → 利率 → 波动率</span></h3><div class="criteria-list">${gate.evidence.map(item => `<div class="criterion"><span class="status-badge ${statusClass(item.status)}">${e(item.status)}</span><strong>${e(item.label)}</strong><p>${e(item.value ?? "缺失")}${item.unit || ""}</p></div>`).join("")}</div></section>
        <section class="detail-section"><h3>下一次升级条件</h3><div class="detail-card"><ul class="take-profit-list">${gate.next_conditions.map(item => `<li>${e(item)}</li>`).join("")}</ul></div></section>
        <section class="detail-section"><h3>当前动作</h3><div class="detail-card"><p>${e(gate.action)}</p></div></section>`);
      return;
    }
    if (type === "qqq") {
      const q = data.qqq;
      const frames = Object.entries(q.timeframes || {});
      openDrawer("QQQ · MULTI TIMEFRAME", `<div class="drawer-title"><h2>QQQ<small>${e(q.decision_label)}</small></h2><div class="drawer-price">$${price(q.price)}<small>${e(q.bias)} · 共振 ${fmt(q.consensus_score, 1)}</small></div></div>
        <div class="drawer-badges"><span class="signal-badge ${biasClass(q.bias)}">${e(q.decision)}</span><span class="status-badge ${q.execution_ready ? "pass" : "missing"}">${q.execution_ready ? "执行数据通过" : "待券商确认"}</span></div>
        <section class="detail-section"><h3>日线结构</h3><div class="technical-chart">${svgLine(chartValues(q.timeframes?.["1D"]))}</div></section>
        <section class="detail-section"><h3>周期共振</h3><div class="timeframe-grid">${frames.map(([name, frame]) => timeframeCard(name, frame)).join("")}</div></section>
        <section class="detail-section"><h3>结构位置</h3><div class="tech-metrics"><div class="tech-metric"><label>SUPPORT</label><strong>$${price(q.support)}</strong></div><div class="tech-metric"><label>RESISTANCE</label><strong>$${price(q.resistance)}</strong></div><div class="tech-metric"><label>CONFIDENCE</label><strong>${fmt(q.confidence, 1)}</strong></div></div></section>
        <section class="detail-section"><h3>QQQ三情景地图 <span>无主观概率，等待价格确认</span></h3><div class="scenario-map"><div class="bull"><label>BULL</label><strong>突破并守住 $${price(q.resistance)}</strong><p>只有日线与4小时方向转为一致，短周期回踩不破，才升级风险。</p></div><div class="base"><label>BASE</label><strong>$${price(q.support)} – $${price(q.resistance)}</strong><p>区间内保持选择性，只做相对强度领先且剧本清晰的个股。</p></div><div class="bear"><label>BEAR</label><strong>有效跌破 $${price(q.support)}</strong><p>降低风险上限，停止追买；等待重新收复或形成2–3日企稳结构。</p></div></div></section>
        <section class="detail-section"><h3>下一触发</h3><div class="detail-card"><p>${e(q.next_condition)}</p></div></section>
        <section class="detail-section"><h3>否决条件</h3><div class="detail-card"><ul class="take-profit-list">${(q.vetoes || []).map(item => `<li>${e(item)}</li>`).join("")}</ul></div></section>`);
      return;
    }
    if (type === "quality") {
      const q = data.data_quality;
      openDrawer("DATA QUALITY GATE", `<div class="drawer-title"><h2>数据质量闸门<small>${e(q.provider)} · ${e(q.feed)}</small></h2><div class="drawer-price">${e(q.status)}<small>${fmt(q.age_hours, 1)} 小时</small></div></div>
        <div class="drawer-badges"><span class="status-badge ${q.can_research ? "pass" : "block"}">${q.can_research ? "研究可用" : "研究阻断"}</span><span class="status-badge ${q.execution_ready ? "pass" : "block"}">${q.execution_ready ? "执行可用" : "执行不可用"}</span><span class="playbook-badge">${e(q.session)}</span></div>
        <section class="detail-section"><h3>质量发现</h3><div class="criteria-list">${q.issues.map(issue => `<div class="criterion"><span class="status-badge ${issue.severity === "CRITICAL" || issue.severity === "HIGH" ? "block" : "missing"}">${e(issue.severity)}</span><strong>${e(issue.code)}</strong><p>${e(issue.message)}</p></div>`).join("") || `<div class="detail-card"><p>没有发现阻断性问题。</p></div>`}</div></section>
        <section class="detail-section"><h3>来源定义</h3><div class="detail-card"><p>数据截至 ${e(q.as_of)}。延迟属性：${e(q.latency)}。公开快照不是券商SIP或OPRA实时数据，因此即使技术条件完整，也只能形成研究候选。</p></div></section>`);
    }
  }

  function openPlaybookDetail(code) {
    const row = radarRows(state.data).find(item => item.code === code);
    if (!row) return;
    openDrawer(`${code} · SCENARIO SYSTEM`, `<div class="drawer-title"><h2>${e(row.label)}<small>${e(row.thesis)}</small></h2><div class="drawer-price">${fmt(row.candidate_count,0)}<small>当前候选</small></div></div>
      <div class="drawer-badges"><span class="status-badge ${radarClass(row.state)}">${e(row.state_label)}</span><span class="playbook-badge">平均证据 ${fmt(row.average_completion_pct,0)}%</span><span class="playbook-badge">研究就绪 ${fmt(row.ready_count,0)}</span></div>
      <section class="action-hero ${radarClass(row.state)}"><label>剧本核心命题</label><h3>${e(row.thesis)}</h3><p>主约束：${e(row.primary_bottleneck?.label || "暂无候选")}。${e(row.primary_bottleneck?.next_condition || row.trigger)}</p></section>
      <section class="detail-section"><h3>五步决策路径 <span>顺序不可颠倒</span></h3><div class="scenario-path drawer-path">${row.decision_path.map(step => `<div><b>0${e(step.step)}</b><span>${e(step.label)}</span><p>${e(step.detail)}</p></div>`).join("")}</div></section>
      <section class="detail-section"><h3>适用环境</h3><div class="detail-card"><p>${e(row.market_fit)}</p></div></section>
      <section class="detail-section"><h3>当前证据瓶颈 <span>按影响股票数量排序</span></h3><div class="criteria-list">${row.bottlenecks.map(item => `<div class="criterion"><span class="status-badge ${item.missing ? "missing" : "block"}">${item.missing ? "MISSING" : "BLOCK"}</span><strong>${e(item.label)} · ${fmt(item.count,0)}只</strong><p>${e(item.next_condition)}<span>${fmt(item.missing,0)}只缺数据 · ${fmt(item.blocked,0)}只条件未过</span></p></div>`).join("") || `<div class="detail-card"><p>当前没有聚合瓶颈。</p></div>`}</div></section>
      <section class="detail-section"><h3>最接近触发的候选</h3><div class="leader-list">${row.leaders.map(item => `<button data-symbol="${e(item.symbol)}"><strong>${e(item.symbol)}<small>${e(item.entry_label)}</small></strong><span>证据 ${fmt(item.completion_pct,0)}%</span><p>${e(item.next_action)}</p></button>`).join("") || `<div class="detail-card"><p>当前没有进入此剧本的股票。</p></div>`}</div></section>
      <section class="detail-section"><h3>风险与退出纪律</h3><div class="plan-grid"><div class="plan-card invalidation"><label>DO NOT TRADE WHEN</label><p>${e(row.avoid)}</p></div><div class="plan-card"><label>EXIT MANAGEMENT</label><p>${e(row.exit)}</p></div></div></section>`);
  }

  function phaseForDays(days) {
    const d = n(days);
    if (d === null) return "NO_VERIFIED_EVENT";
    if (d > 30) return "DISCOVERY";
    if (d >= 7) return "EXPECTATION_BUILD";
    if (d >= 1) return "PRE_EVENT_RISK";
    if (d === 0) return "FACT_RELEASED";
    if (d >= -3) return "POST_EVENT_DISCOVERY";
    if (d >= -20) return "POST_EVENT_TREND";
    return "INACTIVE";
  }

  function openEvent(index) {
    const event = state.data.events.filter(item => n(item.days_to_event) >= -1)[index];
    if (!event) return;
    const scope = (event.scope || []).join(" · ");
    const phase = state.data.event_radar?.lifecycle?.find(item => item.code === phaseForDays(event.days_to_event));
    openDrawer("VERIFIED EVENT", `<div class="drawer-title"><h2>${e(event.title)}<small>${e(event.category)} · ${e(event.verification)}</small></h2><div class="drawer-price">${n(event.days_to_event) >= 0 ? n(event.days_to_event) : "已过"}<small>${n(event.days_to_event) >= 0 ? "天后" : "事件窗口"}</small></div></div>
      <div class="drawer-badges"><span class="status-badge ${event.verified ? "pass" : "missing"}">${event.verified ? "官方确认" : "待核验"}</span><span class="playbook-badge">重要度 ${e(event.importance)}/4</span><span class="playbook-badge">${e(event.week_risk_label || "")}</span><span class="playbook-badge">${e(phase?.label || "事件窗口外")}</span></div>
      <section class="action-hero ${event.verified ? "pass" : "missing"}"><label>当前阶段的动作</label><h3>${e(phase?.action || "等待核验")}</h3><p>必须证据：${e(phase?.required || "官方日期与价格反应")}</p></section>
      <section class="detail-section"><h3>事件生命周期</h3>${lifecycle(phaseForDays(event.days_to_event))}</section>
      <section class="detail-section"><h3>时间与时区</h3><div class="detail-card"><p>北京时间：${e(event.at_cn || event.at)}<br>原始美东时间：${e(event.at_et || "未提供")}</p></div></section>
      <section class="detail-section"><h3>影响范围</h3><div class="detail-card"><p>${e(scope || "全市场")}</p></div></section>
      <section class="detail-section"><h3>交易含义</h3><div class="detail-card"><p>${e(event.note || "等待官方数据与价格反应")}</p></div></section>
      <section class="detail-section"><h3>事实发布后必须回答</h3>${expectationEvidence(state.data)}</section>
      <section class="detail-section"><h3>官方来源</h3><div class="detail-card"><p>${event.source_url ? `<a href="${e(event.source_url)}" target="_blank" rel="noopener noreferrer">${e(event.source || event.source_url)} ↗</a>` : e(event.source || "没有来源链接")}</p></div></section>`);
  }
  function lifecycle(activeCode) {
    return `<div class="lifecycle">${phaseLabels.map(([code, label], index) => `<div class="life-step ${activeCode === code ? "active" : ""}"><b>0${index + 1}</b><span>${e(label)}</span></div>`).join("")}</div>`;
  }

  function decisionDetail(item, technical, technicalError) {
    const gap = item.expectation_gap || { components: [], label: "证据不足", formula: "" };
    const event = item.event;
    const constraint = item.primary_constraint;
    return `<div class="drawer-title"><h2>${e(item.symbol)}<small>${e(item.name)} · ${e(item.sector)}</small></h2><div class="drawer-price">$${price(item.price)}<small class="${directionClass(item.day_change_pct)}">${pct(item.day_change_pct)}</small></div></div>
      <div class="drawer-badges"><span class="playbook-badge">${e(item.playbook.label)}</span><span class="status-badge ${entryClass(item.entry.state)}">${e(item.entry.label)}</span><span class="playbook-badge">证据 ${e(item.evidence_completion_pct)}%</span><span class="playbook-badge">剧本内 #${e(item.rank_within_playbook || "—")}</span></div>
      <section class="action-hero ${entryClass(item.entry.state)}"><label>现在唯一该做什么</label><h3>${e(item.next_best_action)}</h3><p>${constraint ? `当前主约束：${e(constraint.label)} · ${e(constraint.status)}` : "必要证据已完整，仍需等待价格触发与券商确认。"}</p></section>
      <section class="detail-section"><h3>五层决策栈 <span>任何一层阻断都不能越级</span></h3>${decisionStackHtml(item.decision_stack)}</section>
      <section class="detail-section"><h3>为什么进入这个剧本</h3><div class="detail-card"><p>${e(item.playbook.why)}</p></div></section>
      <section class="detail-section"><h3>当前结构快照 <span>同一份公开快照</span></h3><div class="tech-metrics"><div class="tech-metric"><label>距MA50</label><strong>${pct(item.distance_ma50_pct)}</strong></div><div class="tech-metric"><label>20日回撤</label><strong>${pct(item.drawdown20_pct)}</strong></div><div class="tech-metric"><label>RSI14</label><strong>${fmt(item.rsi14,1)}</strong></div><div class="tech-metric"><label>量比</label><strong>${fmt(item.volume_ratio,2)}</strong></div><div class="tech-metric"><label>MA50</label><strong>$${price(item.ma50)}</strong></div><div class="tech-metric"><label>事件阶段</label><strong>${e(item.event_phase.label)}</strong></div></div></section>
      <section class="detail-section"><h3>事件生命周期 <span>${event ? `${e(event.title)} · ${e(event.days_to_event)}天` : "无已核验公司事件"}</span></h3>${lifecycle(item.event_phase.code)}</section>
      <section class="detail-section"><h3>剧本证据链 <span>${e(item.evidence_summary.label)}</span></h3><div class="criteria-list">${item.criteria.map(rule => `<div class="criterion"><span class="status-badge ${statusClass(rule.status)}">${e(rule.status)}</span><strong>${e(rule.label)}</strong><p>${e(rule.evidence)}<span>下一条件：${e(rule.next_condition)}</span></p></div>`).join("") || `<div class="detail-card"><p>当前没有有效剧本，默认不交易；等待价格进入一套定义清楚的高质量结构。</p></div>`}</div></section>
      <section class="detail-section"><h3>预期差引擎 <span>${e(gap.label)}</span></h3><div class="gap-grid">${gap.components.map(component => `<div class="gap-item ${statusClass(component.status)}"><label>${e(component.status)}</label><strong>${e(component.label)}</strong><p>${component.value == null ? "证据尚未接入" : e(component.value)}</p></div>`).join("")}</div><div class="detail-card" style="margin-top:8px"><p>${e(gap.formula)}</p></div></section>
      <section class="detail-section"><h3>入场、失效与退出</h3><div class="plan-grid"><div class="plan-card"><label>ENTRY TRIGGER</label><p>${e(item.plan.entry_trigger)}</p></div><div class="plan-card invalidation"><label>INVALIDATION</label><p>${e(item.plan.invalidation)}</p></div></div><div class="detail-card" style="margin-top:8px"><ul class="take-profit-list">${item.plan.take_profit.map(rule => `<li>${e(rule)}</li>`).join("") || "<li>无交易计划</li>"}</ul></div></section>
      <section class="detail-section"><h3>${e(item.driver_tree.archetype)} · 驱动树</h3><div class="driver-grid">${item.driver_tree.drivers.map(driver => `<div class="driver-item">${e(driver)}</div>`).join("")}</div><h3 style="margin-top:12px">逻辑证伪条件</h3><div class="driver-grid">${item.driver_tree.falsifiers.map(driver => `<div class="driver-item falsifier">${e(driver)}</div>`).join("")}</div></section>
      <section class="detail-section"><h3>TrendIQ 技术结构 <span>与 QQQ 相同的多周期系统</span></h3><div class="detail-card" style="margin-bottom:8px"><a class="text-button" href="./qqq_trendiq.html?symbol=${encodeURIComponent(item.symbol)}">打开 ${e(item.symbol)} 完整交互K线、MACD、RSI与情景计划 →</a></div>${technical ? technicalDetail(technical) : `<div class="detail-card"><p>${e(technicalError || "正在加载技术快照…")}</p></div>`}</section>`;
  }
  function timeframeCard(name, frame) {
    const indicators = frame?.indicators || {};
    const trend = frame?.trend || frame?.direction || "UNKNOWN";
    return `<div class="timeframe-card"><div class="timeframe-card-top"><h4>${e(name)}</h4><span class="signal-badge ${biasClass(trend)}">${e(trend)}</span></div><p>趋势分 ${fmt(frame?.trend_score ?? frame?.score, 0)}<br>RSI ${fmt(indicators.rsi14, 1)} · MA20 ${price(indicators.ma20)}</p></div>`;
  }

  function technicalDetail(technical) {
    const frames = Object.entries(technical.timeframes || {});
    const oneDay = technical.timeframes?.["1D"];
    const patterns = technical.patterns || [];
    const longPlan = technical.plans?.long || {};
    const backtest = technical.backtest || {};
    return `<div class="technical-hero"><div class="technical-summary"><span class="signal-badge ${biasClass(technical.bias)}">${e(technical.bias || "UNKNOWN")}</span><strong>${e(technical.decision_label || technical.decision || "等待")}</strong><p>${e(technical.reasoning?.summary || "多周期结构等待确认")}</p></div><div class="technical-chart">${svgLine(chartValues(oneDay))}</div></div>
      <div class="timeframe-grid" style="margin-top:8px">${frames.map(([name, frame]) => timeframeCard(name, frame)).join("")}</div>
      <div class="tech-metrics" style="margin-top:8px"><div class="tech-metric"><label>模型触发位</label><strong>$${price(longPlan.trigger)}</strong></div><div class="tech-metric"><label>模型止损位</label><strong>$${price(longPlan.stop)}</strong></div><div class="tech-metric"><label>模型目标1</label><strong>$${price(longPlan.target1)}</strong></div><div class="tech-metric"><label>5日结构胜率</label><strong>${fmt(backtest.day_5?.win_rate,1)}%</strong></div><div class="tech-metric"><label>20日中位回报</label><strong>${pct(backtest.day_20?.median_return_pct)}</strong></div><div class="tech-metric"><label>历史样本</label><strong>${fmt(backtest.sample_count,0)}</strong></div></div>
      ${patterns.length ? `<div class="pattern-list" style="margin-top:8px">${patterns.slice(0,5).map(pattern => `<div class="pattern-row"><strong>${e(pattern.name)} · ${e(pattern.timeframe)}</strong><p>${e(pattern.explanation)}</p><span class="status-badge ${biasClass(pattern.direction) === "up" ? "pass" : biasClass(pattern.direction) === "down" ? "block" : "missing"}">${e(pattern.status)}</span></div>`).join("")}</div>` : ""}
      <div class="detail-card" style="margin-top:8px"><p>以上价位来自静态模型快照，只能用于观察结构；真实执行必须重新核验实时价格、点差、成交量和事件状态。</p></div>`;
  }

  async function openSymbol(symbol) {
    const item = state.data.symbols.find(row => row.symbol === symbol);
    if (!item) return;
    state.drawerSymbol = symbol;
    openDrawer(`${symbol} · PLAYBOOK DETAIL`, decisionDetail(item, null, null));
    try {
      const payload = await fetchSymbol(symbol);
      if (state.drawerSymbol !== symbol) return;
      drawerContent.innerHTML = decisionDetail(payload.decision || item, payload.technical, payload.technical_error);
    } catch (error) {
      if (state.drawerSymbol !== symbol) return;
      drawerContent.innerHTML = decisionDetail(item, null, error.message);
    }
  }

  document.addEventListener("click", event => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) { switchView(viewButton.dataset.view); return; }
    const playbookDetailButton = event.target.closest("[data-playbook-detail]");
    if (playbookDetailButton) { openPlaybookDetail(playbookDetailButton.dataset.playbookDetail); return; }
    const symbolButton = event.target.closest("[data-symbol]");
    if (symbolButton) { openSymbol(symbolButton.dataset.symbol); return; }
    const playbookButton = event.target.closest("[data-playbook]");
    if (playbookButton) {
      state.playbookFilter = playbookButton.dataset.playbook;
      state.currentView = state.currentView === "universe" ? "universe" : "playbooks";
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const detailButton = event.target.closest("[data-detail]");
    if (detailButton) { openInfo(detailButton.dataset.detail); return; }
    const eventButton = event.target.closest("[data-event-index]");
    if (eventButton) openEvent(Number(eventButton.dataset.eventIndex));
  });

  refreshButton.addEventListener("click", () => loadDashboard(true));
  drawerClose.addEventListener("click", closeDrawer);
  drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeDrawer(); });

  loadDashboard();
})();
