(() => {
  "use strict";

  const app = document.getElementById("app");
  const sourcePill = document.getElementById("sourcePill");
  const refreshButton = document.getElementById("refreshButton");
  const drawer = document.getElementById("detailDrawer");
  const drawerTitle = document.getElementById("drawerTitle");
  const drawerEyebrow = document.getElementById("drawerEyebrow");
  const drawerBody = document.getElementById("drawerBody");
  const toast = document.getElementById("toast");

  const state = {
    data: null,
    currentView: "today",
    stateFilter: "ALL",
    playbookFilter: "ALL",
    sectorFilter: "ALL",
    search: "",
  };

  const stateLabels = {
    ALL: "全部状态",
    RESEARCH_READY: "研究就绪",
    WAIT_TRIGGER: "等待触发",
    EVIDENCE_GAP: "证据不足",
    BLOCKED: "规则阻断",
    NO_SETUP: "暂无剧本",
    DATA_GAP: "数据不足",
  };

  function e(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fmt(value, digits = 1, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : fallback;
  }

  function integer(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    const number = Number(value);
    return Number.isFinite(number) ? Math.round(number).toLocaleString("zh-CN") : fallback;
  }

  function money(value) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number) ? `$${number.toFixed(number >= 100 ? 2 : 2)}` : "—";
  }

  function signed(value, digits = 2) {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return `${number > 0 ? "+" : ""}${number.toFixed(digits)}%`;
  }

  function changeClass(value) {
    if (value === null || value === undefined || value === "") return "";
    const number = Number(value);
    return number > 0 ? "positive" : number < 0 ? "negative" : "";
  }

  function shortTime(value) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function statusBadge(code, label) {
    const safe = String(code || "UNKNOWN").replace(/[^A-Z0-9_-]/g, "");
    return `<span class="status-badge status-${safe}">${e(label || code || "未知")}</span>`;
  }

  async function jsonFetch(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.error) throw new Error(payload.error || `请求失败 ${response.status}`);
    return payload;
  }

  function qualityBanner(data) {
    const quality = data.data_quality || {};
    const ok = quality.status === "OK" && quality.execution_ready;
    const source = data.meta?.source || {};
    const issues = Array.isArray(quality.issues) ? quality.issues.filter(Boolean) : [];
    const firstIssue = issues.length
      ? (typeof issues[0] === "string"
        ? issues[0]
        : issues[0].message || issues[0].detail || issues[0].label || issues[0].code || "存在数据质量限制")
      : "";
    const detail = [
      source.provider || quality.provider || "未知来源",
      source.latency || quality.latency || "时效未知",
      data.meta?.as_of ? `截至 ${shortTime(data.meta.as_of)}` : "",
      quality.official_realtime ? "已确认实时" : "执行前需券商实时确认",
    ].filter(Boolean).join(" · ");
    return `<section class="quality-banner ${ok ? "ok" : ""}">
      <span class="quality-icon">${ok ? "✓" : "i"}</span>
      <div><strong>${e(ok ? "数据与执行闸门已通过" : "研究数据可读，执行闸门尚未通过")}</strong><p>${e(detail)}${firstIssue ? ` · ${e(firstIssue)}` : ""}</p></div>
      <button data-view="market">查看质量与市场闸门 →</button>
    </section>`;
  }

  function commandMetrics(command, counts) {
    const risk = command.risk_budget || {};
    return `<div class="metric-grid">
      <div class="metric"><span>研究就绪</span><strong>${integer(counts.RESEARCH_READY || 0)}</strong></div>
      <div class="metric"><span>等待触发</span><strong>${integer(counts.WAIT_TRIGGER || 0)}</strong></div>
      <div class="metric"><span>证据不足</span><strong>${integer(counts.EVIDENCE_GAP || 0)}</strong></div>
      <div class="metric"><span>单笔研究风险</span><strong>${fmt(risk.risk_per_trade_pct, 2)}%</strong></div>
      <div class="metric wide"><span>组合边界</span><strong>开放风险 ${fmt(risk.max_open_risk_pct, 2)}% · 单仓 ${fmt(risk.max_position_value_pct, 2)}% · 最多 ${integer(risk.max_positions)} 只</strong></div>
    </div>`;
  }

  function decisionStack(command) {
    const rows = Array.isArray(command.stack) ? command.stack : [];
    return `<div class="decision-stack">${rows.map((item, index) => `<article class="stack-card">
      <header><span>0${index + 1}</span>${statusBadge(item.status, item.status)}</header>
      <strong>${e(item.label)} · ${e(item.value)}</strong>
      <p>${e(item.evidence || "暂无证据说明")}<br>${e(item.next_condition || "")}</p>
    </article>`).join("")}</div>`;
  }

  function actionableSymbols(data) {
    return (data.symbols || []).filter(row => !["NO_SETUP", "DATA_GAP"].includes(row.research_state?.code));
  }

  function candidateRows(rows, limit = rows.length) {
    return rows.slice(0, limit).map(row => `<button class="candidate-row" data-symbol="${e(row.symbol)}">
      <span><strong>${e(row.symbol)}</strong><small>${e(row.name)} · ${e(row.sector)}</small></span>
      <span><strong>${e(row.playbook?.label || "暂无剧本")}</strong><small>1.0：${e(row.opportunity?.stage_label || row.legacy_signal?.status || "待确认")}</small></span>
      <span class="price"><strong>${money(row.price)}</strong><small>证据 ${integer(row.evidence_completion_pct, "—")}%</small></span>
      <span class="change ${changeClass(row.day_change_pct)}">${signed(row.day_change_pct)}</span>
      <span class="next">${e(row.next_action)}</span>
      <span class="arrow">›</span>
    </button>`).join("");
  }

  function topConstraints(command) {
    const constraints = Array.isArray(command.top_constraints) ? command.top_constraints : [];
    if (!constraints.length) return `<div class="empty-state">当前没有聚合约束数据</div>`;
    return `<div class="constraint-list">${constraints.map(item => `<div class="constraint-item">
      <strong>${e(item.label)} · ${integer(item.count, 0)} 只</strong>
      <p>缺失 ${integer(item.missing, 0)} · 阻断 ${integer(item.blocked, 0)}</p>
    </div>`).join("")}</div>`;
  }

  function renderToday(data) {
    const command = data.command || {};
    const counts = data.queue_summary?.counts || {};
    const candidates = actionableSymbols(data);
    return `<section class="view ${state.currentView === "today" ? "active" : ""}" data-view-panel="today">
      ${qualityBanner(data)}
      <div class="page-head"><div><span class="eyebrow">TODAY'S UNIFIED COMMAND</span><h1>今日决策</h1></div><p>3.0 将 1.0 的完整证据与 2.0 的唯一剧本合并；状态只用于研究排序，不会自动下单。</p></div>
      <section class="command-card">
        <div class="command-top"><div><span class="eyebrow">MARKET COMMAND</span><h2>${e(command.verdict || "等待统一决策")}</h2><p class="command-copy">${e(command.posture || "等待市场、行业、剧本与证据链完整。")}</p></div><div class="risk-orb"><div><strong>${fmt(command.risk_cap_pct, 0)}%</strong><span>模型风险上限</span></div></div></div>
        ${commandMetrics(command, counts)}
        ${decisionStack(command)}
      </section>
      <div class="section-grid">
        <section class="panel"><div class="panel-header"><div><span class="eyebrow">DECISION QUEUE</span><h2>最接近下一步</h2><p>同时显示 1.0 机会阶段、2.0 剧本和唯一下一条件</p></div><button class="text-button" data-view="opportunities">查看 52 股 →</button></div><div class="candidate-list">${candidateRows(candidates, 8) || `<div class="empty-state">当前没有进入有效剧本的候选</div>`}</div></section>
        <section class="panel"><div class="panel-header"><div><span class="eyebrow">DOMINANT CONSTRAINTS</span><h2>当前主要阻碍</h2><p>${e(command.dominant_constraint?.label || "系统正在聚合证据缺口")}</p></div></div>${topConstraints(command)}</section>
      </div>
      <div class="methodology"><strong>统一路径</strong>${(data.methodology?.decision_order || []).map(step => `<span>${e(step)}</span>`).join(" → ")}<em>仅研究与纪律辅助，最终执行需券商实时确认。</em></div>
    </section>`;
  }

  function overviewTile(label, value, hint = "") {
    return `<div class="evidence-tile"><span>${e(label)}</span><strong>${e(value)}</strong>${hint ? `<small>${e(hint)}</small>` : ""}</div>`;
  }

  function renderMarket(data) {
    const gate = data.market?.gate || {};
    const overview = data.market?.overview || {};
    const qqq = data.market?.qqq || {};
    const sector = data.market?.sector || {};
    const breadth = gate.breadth || overview.breadth || {};
    const leaders = Array.isArray(sector.leaders) ? sector.leaders : [];
    return `<section class="view ${state.currentView === "market" ? "active" : ""}" data-view-panel="market">
      ${qualityBanner(data)}
      <div class="page-head"><div><span class="eyebrow">MARKET PANORAMA</span><h1>市场全景</h1></div><p>保留 1.0 的市场、板块与 QQQ 证据，并用 2.0 风险闸门给出统一动作边界。</p></div>
      <div class="market-grid">
        <section class="panel market-hero"><div class="panel-header"><div><span class="eyebrow">MARKET GATE</span><h2>${e(gate.label || overview.regime_label || "市场待确认")}</h2><p>${e(gate.regime_label || overview.position_label || "")}</p></div>${statusBadge(gate.state || "CAUTION", gate.state || "CAUTION")}</div>
          <div class="score-line"><div class="score-ring"><span><strong>${integer(gate.market_score ?? overview.score)}</strong><small>环境分 / 100</small></span></div><div class="market-verdict"><h2>${e(gate.position_label || overview.position_label || "位置待确认")}</h2><p>${e(gate.action || overview.action || "等待大盘与风险闸门完成。")}</p></div></div>
          <div class="evidence-grid">
            ${overviewTile("风险上限", `${fmt(gate.allocation_cap_pct, 0)}%`, "3.0采用2.0保守口径")}
            ${overviewTile("MA50宽度", `${fmt(breadth.above_ma50_pct ?? breadth.ma50_pct, 1)}%`)}
            ${overviewTile("新风险", gate.can_open_new_risk ? "允许研究" : "暂不扩大", gate.execution_ready ? "执行闸门通过" : "仍需实时确认")}
            ${overviewTile("行情来源", data.meta?.source?.provider || "未知")}
          </div>
        </section>
        <section class="panel"><div class="panel-header"><div><span class="eyebrow">QQQ STRUCTURE</span><h2>QQQ 多周期结构</h2><p>${e(qqq.recommendation?.label || qqq.label || "等待结构数据")}</p></div><a class="text-link" href="./qqq_trendiq.html">完整 TrendIQ →</a></div>
          <div class="market-verdict"><h2>${money(qqq.price)}</h2><p>${e(qqq.recommendation?.summary || qqq.summary || qqq.next_condition || "等待日线、4小时与短周期方向一致。")}</p></div>
          <div class="qqq-levels"><div><span>结构支撑</span><strong>${money(qqq.support)}</strong></div><div><span>结构压力</span><strong>${money(qqq.resistance)}</strong></div><div><span>趋势结论</span><strong>${e(qqq.bias_label || qqq.recommendation?.label || "待确认")}</strong></div></div>
        </section>
      </div>
      <div class="section-grid">
        <section class="panel"><div class="panel-header"><div><span class="eyebrow">SECTOR PULSE</span><h2>${e(sector.label || "行业结构")}</h2><p>${e(sector.action || "等待板块一致性")}</p></div>${statusBadge(sector.state || "CAUTION", sector.confidence || sector.state || "待确认")}</div>
          <div class="evidence-grid">${overviewTile("上涨广度", `${fmt(sector.breadth_pct, 1)}%`)}${overviewTile("站上MA50", `${fmt(sector.above_ma50_pct, 1)}%`)}${overviewTile("覆盖样本", `${integer(sector.members)} 只`)}${overviewTile("当前判断", sector.label || "待确认")}</div>
          <div class="leader-chips">${leaders.map(item => `<span>${e(item.symbol)} ${signed(item.change_pct)}</span>`).join("") || `<span>暂无领涨结构</span>`}</div>
        </section>
        <section class="panel"><div class="panel-header"><div><span class="eyebrow">LEGACY DEPTH</span><h2>完整 1.0 证据仍保留</h2><p>需要日K、行业ETF门槛、历史相似情景和全部AI提醒时，可进入经典全景。</p></div></div>
          <div class="constraint-list"><div class="constraint-item"><strong>3.0 当前页</strong><p>统一命令、风险边界、QQQ、行业和候选队列。</p></div><div class="constraint-item"><strong>1.0 经典全景</strong><p>保留整合前的全部模块、交互和原始信息密度。</p></div></div>
          <div class="detail-actions"><a href="./v1.html">打开 1.0 完整全景</a><a class="secondary" href="./playbooks.html">打开 2.0 剧本台</a></div>
        </section>
      </div>
    </section>`;
  }

  function playbookCards(data) {
    const playbooks = Array.isArray(data.playbook_radar?.playbooks) ? data.playbook_radar.playbooks : [];
    return `<div class="playbook-grid">${playbooks.map(item => `<button class="playbook-card" data-playbook-filter="${e(item.code)}">
      <header><span class="eyebrow">${e(item.code)}</span>${statusBadge(item.state === "FORMING" ? "WAIT_TRIGGER" : item.state === "EVIDENCE_GAP" ? "EVIDENCE_GAP" : "NO_SETUP", item.state_label)}</header>
      <h3>${e(item.label)} · ${integer(item.candidate_count, 0)} 只</h3><p>${e(item.thesis)}</p>
      <footer>主约束：${e(item.primary_bottleneck?.label || "暂无候选")}</footer>
    </button>`).join("")}</div>`;
  }

  function filters(data) {
    const playbooks = [...new Set((data.symbols || []).map(row => row.playbook?.code).filter(Boolean))];
    const sectors = [...new Set((data.symbols || []).map(row => row.sector).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    return `<div class="filter-bar">
      <input id="symbolSearch" type="search" placeholder="搜索代码、公司或下一条件" value="${e(state.search)}" aria-label="搜索股票">
      <select id="stateFilter" aria-label="研究状态"><option value="ALL">全部状态</option>${Object.entries(stateLabels).filter(([code]) => code !== "ALL").map(([code,label]) => `<option value="${code}" ${state.stateFilter === code ? "selected" : ""}>${e(label)}</option>`).join("")}</select>
      <select id="playbookFilter" aria-label="交易剧本"><option value="ALL">全部剧本</option>${playbooks.map(code => { const row=(data.symbols||[]).find(item=>item.playbook?.code===code); return `<option value="${e(code)}" ${state.playbookFilter === code ? "selected" : ""}>${e(row?.playbook?.label || code)}</option>`; }).join("")}</select>
      <select id="sectorFilter" aria-label="行业"><option value="ALL">全部行业</option>${sectors.map(sector => `<option value="${e(sector)}" ${state.sectorFilter === sector ? "selected" : ""}>${e(sector)}</option>`).join("")}</select>
    </div>`;
  }

  function filteredSymbols(data) {
    const needle = state.search.trim().toLowerCase();
    return (data.symbols || []).filter(row => {
      if (state.stateFilter !== "ALL" && row.research_state?.code !== state.stateFilter) return false;
      if (state.playbookFilter !== "ALL" && row.playbook?.code !== state.playbookFilter) return false;
      if (state.sectorFilter !== "ALL" && row.sector !== state.sectorFilter) return false;
      if (!needle) return true;
      return [row.symbol, row.name, row.sector, row.next_action, row.playbook?.label].some(value => String(value || "").toLowerCase().includes(needle));
    });
  }

  function universeTable(data) {
    const rows = filteredSymbols(data);
    return `<div class="universe-table"><div class="universe-head"><span>股票</span><span>统一状态</span><span>交易剧本</span><span>价格/今日</span><span>证据</span><span>主要阻碍与下一步</span><span></span></div>
      ${rows.map(row => `<button class="universe-row" data-symbol="${e(row.symbol)}"><span><strong>${e(row.symbol)}</strong><small>${e(row.name)} · ${e(row.sector)}</small></span><span>${statusBadge(row.research_state?.code, row.research_state?.label)}</span><span><strong>${e(row.playbook?.label || "暂无有效剧本")}</strong><small>1.0 ${e(row.opportunity?.stage_label || row.legacy_signal?.status || "待确认")}</small></span><span class="number"><strong>${money(row.price)}</strong><small class="${changeClass(row.day_change_pct)}">${signed(row.day_change_pct)}</small></span><span class="number"><strong>${integer(row.evidence_completion_pct)}%</strong><small>${integer(row.evidence_summary?.passed, 0)}/${integer(row.evidence_summary?.total, 0)} 通过</small></span><span><strong>${e(row.primary_constraint?.label || "暂无主要阻碍")}</strong><small>${e(row.next_action)}</small></span><span class="arrow">›</span></button>`).join("") || `<div class="empty-state">没有符合当前筛选的股票</div>`}
    </div>`;
  }

  function renderOpportunities(data) {
    return `<section class="view ${state.currentView === "opportunities" ? "active" : ""}" data-view-panel="opportunities">
      ${qualityBanner(data)}
      <div class="page-head"><div><span class="eyebrow">OPPORTUNITIES + PLAYBOOKS</span><h1>机会与剧本</h1></div><p>每只股票只保留一个当前剧本；1.0 分数作为证据参考，3.0 状态以2.0剧本入口为准。</p></div>
      ${playbookCards(data)}
      <section class="panel" style="margin-top:14px"><div class="panel-header"><div><span class="eyebrow">UNIFIED UNIVERSE</span><h2>52 股统一研究队列</h2><p id="resultCount">按状态、剧本、行业与下一条件筛选</p></div></div>${filters(data)}<div id="universeMount">${universeTable(data)}</div></section>
    </section>`;
  }

  function weekCards(data) {
    const weeks = Array.isArray(data.events?.weeks) ? data.events.weeks : [];
    if (!weeks.length) return `<div class="empty-state">自然周事件正在核验</div>`;
    return `<div class="week-grid">${weeks.map(week => `<article class="week-card"><header><span class="eyebrow">${e(week.label)}</span><span class="risk-${e(week.risk_score)}">${e(week.risk_label)}</span></header><h3>${e(week.start)} — ${e(week.end)}</h3><p>${e(week.action)}</p><div class="event-list">${(week.events || []).map(event => `<div class="event-item"><strong>${e(event.title)}</strong><span>${shortTime(event.at_cn || event.at)} · ${e(event.verification || "待核验")}</span></div>`).join("") || `<div class="event-item"><strong>本周暂无已核验事件</strong></div>`}</div></article>`).join("")}</div>`;
  }

  function alertList(data, limit = 16) {
    const alerts = Array.isArray(data.evidence?.recent_alerts) ? data.evidence.recent_alerts.slice(0, limit) : [];
    if (!alerts.length) return `<div class="empty-state">暂无提醒与证据更新</div>`;
    return `<div class="alert-list">${alerts.map(item => `<div class="alert-item"><strong>${e(item.symbol || "SYSTEM")} · ${e(item.kind || "提醒")}</strong><p>${e(item.message)}</p><time>${shortTime(item.created_at)}</time></div>`).join("")}</div>`;
  }

  function renderEvents(data) {
    return `<section class="view ${state.currentView === "events" ? "active" : ""}" data-view-panel="events">
      ${qualityBanner(data)}
      <div class="page-head"><div><span class="eyebrow">EVENTS + EVIDENCE</span><h1>事件与证据</h1></div><p>${e(data.events?.timezone_note || "事件按自然周展示，交易日口径以美东时区为准。")}</p></div>
      ${weekCards(data)}
      <div class="section-grid"><section class="panel"><div class="panel-header"><div><span class="eyebrow">VERIFICATION</span><h2>事件核验状态</h2><p>${e(data.events?.verification_status || "待核验")} · ${e(data.events?.verified_at || "时间未知")}</p></div></div><div class="constraint-list"><div class="constraint-item"><strong>自然周口径</strong><p>周一至周日；周日查看时从次日周一开始，不使用滚动未来7天。</p></div><div class="constraint-item"><strong>执行边界</strong><p>官方事件日期与研究快照不等于实时价格确认，交易前仍需券商数据。</p></div></div></section><section class="panel"><div class="panel-header"><div><span class="eyebrow">RECENT EVIDENCE</span><h2>AI、新闻与SEC提醒</h2><p>AI只做第二层复核，不直接改变规则与交易状态</p></div></div>${alertList(data, 12)}</section></div>
    </section>`;
  }

  function renderAll() {
    if (!state.data) return;
    app.innerHTML = renderToday(state.data) + renderMarket(state.data) + renderOpportunities(state.data) + renderEvents(state.data);
    syncNavigation();
  }

  function syncNavigation() {
    document.querySelectorAll("[data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === state.currentView));
    document.querySelectorAll("[data-view-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.viewPanel === state.currentView));
  }

  function setView(view) {
    if (!["today", "market", "opportunities", "events"].includes(view)) return;
    state.currentView = view;
    syncNavigation();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateUniverse() {
    const mount = document.getElementById("universeMount");
    if (mount && state.data) mount.innerHTML = universeTable(state.data);
  }

  function openSymbol(symbol) {
    const row = (state.data?.symbols || []).find(item => item.symbol === symbol);
    if (!row) return;
    drawerEyebrow.textContent = `${row.playbook?.label || "暂无剧本"} · ${row.research_state?.label || "待确认"}`;
    drawerTitle.textContent = `${row.symbol} 统一决策`;
    drawerBody.innerHTML = `<section class="drawer-hero"><div class="drawer-symbol"><div><span class="eyebrow">${e(row.sector)}</span><h2>${e(row.symbol)}</h2><p>${e(row.name)}</p></div><div class="drawer-price"><strong>${money(row.price)}</strong><span class="${changeClass(row.day_change_pct)}">${signed(row.day_change_pct)}</span></div></div><div class="drawer-badges">${statusBadge(row.research_state?.code, row.research_state?.label)}${statusBadge(row.entry?.state, row.entry?.label)}<span class="status-badge status-PASS">证据 ${integer(row.evidence_completion_pct)}%</span>${row.holding ? `<span class="status-badge status-CAUTION">我的持仓</span>` : ""}</div></section>
      <section class="detail-section"><h3>唯一下一条件</h3><p>${e(row.next_action)}</p></section>
      <section class="detail-section"><h3>1.0 机会证据</h3><p>${e(row.opportunity?.stage_label || row.legacy_signal?.status || "待确认")} · 参考分 ${integer(row.opportunity?.final_score ?? row.legacy_signal?.score)}。${e(row.legacy_signal?.reason || "")}</p></section>
      <section class="detail-section"><h3>2.0 当前剧本</h3><p><strong>${e(row.playbook?.label || "暂无有效剧本")}</strong><br>${e(row.playbook?.why || "当前不属于任何高质量剧本。")}</p></section>
      <section class="detail-section"><h3>主要阻碍</h3><p>${e(row.primary_constraint?.label || "暂无")}: ${e(row.primary_constraint?.evidence || "暂无证据说明")}<br>下一条件：${e(row.primary_constraint?.next_condition || row.next_action)}</p></section>
      <section class="detail-section"><h3>剧本证据链</h3><div class="criteria-list">${(row.criteria || []).map(item => `<div class="criterion">${statusBadge(item.status, item.status)}<strong>${e(item.label)}</strong><p>${e(item.evidence)}<span>下一条件：${e(item.next_condition)}</span></p></div>`).join("") || `<p>当前没有可用证据链。</p>`}</div></section>
      <section class="detail-section"><h3>计划与失效</h3><p>触发：${e(row.plan?.entry_trigger || "待确认")}<br>失效：${e(row.plan?.invalidation || "待确认")}<br>保护：${e((row.plan?.take_profit || []).join("；") || "待确认")}</p></section>
      <section class="detail-section"><h3>AI / 基本面复核</h3><p>${e(row.ai_analysis?.summary || "当前没有新鲜且可验证的AI基本面结论；AI不会直接改变3.0研究状态。")}</p></section>
      <div class="detail-actions"><a href="./qqq_trendiq.html?symbol=${encodeURIComponent(row.symbol)}">打开完整 TrendIQ</a><a class="secondary" href="./v1.html">查看 1.0 全景</a></div>`;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
  }

  function updateSource(data) {
    const quality = data.data_quality || {};
    const source = data.meta?.source || {};
    sourcePill.classList.toggle("ok", quality.status === "OK" && quality.execution_ready);
    sourcePill.classList.toggle("bad", quality.status === "FAILED");
    sourcePill.querySelector("span").textContent = `${source.provider || quality.provider || "未知来源"} · ${shortTime(data.meta?.as_of)}`;
  }

  async function load() {
    try {
      const data = await jsonFetch(`/api/v3/dashboard?t=${Date.now()}`);
      if (data.schema_version !== "3.0.0") throw new Error("收到的不是 ANLI 3.0 数据");
      state.data = data;
      updateSource(data);
      renderAll();
    } catch (error) {
      sourcePill.classList.add("bad");
      sourcePill.querySelector("span").textContent = "3.0 数据不可用";
      app.innerHTML = `<section class="error-card"><span class="eyebrow">ANLI 3.0</span><h1>统一决策层暂不可用</h1><p>${e(error.message)}</p><p>旧版仍然保留，可暂时进入 1.0 或 2.0。</p><div class="detail-actions"><a href="./v1.html">打开 1.0</a><a class="secondary" href="./playbooks.html">打开 2.0</a></div></section>`;
    }
  }

  async function refreshData() {
    refreshButton.disabled = true;
    refreshButton.textContent = "…";
    try {
      await jsonFetch("/api/refresh", { method: "POST" });
      showToast("刷新已提交，正在重新计算统一决策");
      window.setTimeout(load, 1800);
    } catch (error) {
      showToast(error.message);
    } finally {
      window.setTimeout(() => { refreshButton.disabled = false; refreshButton.textContent = "↻"; }, 1900);
    }
  }

  document.addEventListener("click", event => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) setView(viewButton.dataset.view);
    const symbolButton = event.target.closest("[data-symbol]");
    if (symbolButton) openSymbol(symbolButton.dataset.symbol);
    const playbookButton = event.target.closest("[data-playbook-filter]");
    if (playbookButton) {
      state.playbookFilter = playbookButton.dataset.playbookFilter;
      state.currentView = "opportunities";
      renderAll();
    }
    if (event.target.closest("[data-close-drawer]")) closeDrawer();
  });

  document.addEventListener("input", event => {
    if (event.target.id === "symbolSearch") {
      state.search = event.target.value;
      updateUniverse();
    }
  });

  document.addEventListener("change", event => {
    if (event.target.id === "stateFilter") state.stateFilter = event.target.value;
    if (event.target.id === "playbookFilter") state.playbookFilter = event.target.value;
    if (event.target.id === "sectorFilter") state.sectorFilter = event.target.value;
    updateUniverse();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeDrawer();
  });
  refreshButton.addEventListener("click", refreshData);

  load();
})();
