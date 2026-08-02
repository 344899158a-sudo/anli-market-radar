let signals = [];
let aiAnalyses = {};
let aiJobs = {};
let aiJobsInitialized = false;
let activeAiSymbol = null;
let filter = 'ALL';
let sectorFilter = 'ALL';
let seenAlerts = new Set();
let firstAlertLoad = true;
let technicalSymbol = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const stageClass = stage => String(stage || 'WATCH').toLowerCase();
const safeExternalUrl = value => {
  try {
    const url = new URL(String(value || ''));
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch (_) {
    return null;
  }
};

function fmtTime(value) {
  return value ? new Date(value).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '—';
}

function fmtNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const absolute = Math.abs(number);
  if (absolute >= 1e12) return `${(number / 1e12).toFixed(2)}T`;
  if (absolute >= 1e9) return `${(number / 1e9).toFixed(2)}B`;
  if (absolute >= 1e6) return `${(number / 1e6).toFixed(2)}M`;
  return number.toLocaleString('en-US', {maximumFractionDigits: 2});
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('show');
  setTimeout(() => $('toast').classList.remove('show'), 4500);
}

function beep() {
  try {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain); gain.connect(context.destination);
    oscillator.frequency.value = 740;
    gain.gain.setValueAtTime(.08, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .35);
    oscillator.start(); oscillator.stop(context.currentTime + .35);
  } catch (_) {}
}

async function get(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const payload = JSON.parse(text);
      message = payload.error || payload.message || text;
    } catch (_) {}
    const error = new Error(message || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function localNotify(alert) {
  toast(alert.message);
  beep();
  if (Notification.permission === 'granted') {
    new Notification('Anli 原则机会提醒', {body: alert.message, tag: String(alert.id)});
  }
}

function renderMetrics() {
  $('readyCount').textContent = signals.filter(item => item.opportunity?.can_act).length;
  $('nearCount').textContent = signals.filter(item => item.opportunity?.stage === 'NEAR').length;
  $('aiReviewCount').textContent = signals.filter(item => item.opportunity?.stage === 'AI_REVIEW').length;
}

function renderOpportunityCards() {
  const candidates = signals
    .filter(item => !['WATCH', 'NO_DATA', 'VETO'].includes(item.opportunity?.stage))
    .sort((a, b) => b.opportunity.final_score - a.opportunity.final_score)
    .slice(0, 5);
  if (!candidates.length) {
    $('opportunityCards').innerHTML = '<p class="empty">当前没有接近买点的股票，继续等待规则触发。</p>';
    return;
  }
  $('opportunityCards').innerHTML = candidates.map(item => {
    const opportunity = item.opportunity;
    const change = Number(item.day_change_pct || 0);
    return `<article class="opportunity-card" data-symbol="${item.symbol}">
      <strong>${esc(item.symbol)}</strong><span class="stage ${stageClass(opportunity.stage)}">${esc(opportunity.stage_label)}</span>
      <div class="price">$${Number(item.price || 0).toFixed(2)} <small class="${change >= 0 ? 'positive' : 'negative'}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</small></div>
      <p>综合 ${opportunity.final_score}分 · 硬条件 ${opportunity.hard_passed}/${opportunity.hard_total} · ${esc(opportunity.catalyst_band)}</p>
      <p>${esc(opportunity.next_action)}</p>
    </article>`;
  }).join('');
  document.querySelectorAll('.opportunity-card').forEach(card => {
    card.onclick = () => {
      $('search').value = card.dataset.symbol;
      renderSignals();
      document.querySelector('.table-wrap').scrollIntoView({behavior: 'smooth', block: 'start'});
    };
  });
}

function renderSectors(status) {
  const counts = {};
  for (const item of signals) counts[item.sector] = (counts[item.sector] || 0) + 1;
  const entries = Object.entries(status || {});
  $('sectors').innerHTML = entries.map(([name, value]) => {
    const trend = value.above_ma50 === true
      ? '<b class="up">趋势通过</b>'
      : value.above_ma50 === false
        ? '<b class="down">趋势未过</b>'
        : '<b class="watch">快照待核</b>';
    return `<div class="sector-card" data-sector="${esc(name)}">
      <strong>${esc(name)}</strong><span>${esc(value.benchmark)} · ${trend} · ${counts[name] || 0}只</span>
    </div>`;
  }).join('');
  const select = $('sectorSelect');
  if (select.options.length === 1) {
    for (const [name] of entries) select.add(new Option(`${name} (${counts[name] || 0})`, name));
  }
  document.querySelectorAll('.sector-card').forEach(card => {
    card.onclick = () => { sectorFilter = card.dataset.sector; select.value = sectorFilter; renderSignals(); };
  });
}

function layerChecks(item) {
  const checks = item.checks || {};
  const meanReversion = checks.above_ma50 && checks.stabilized && checks.drawdown;
  const layers = [
    ['行', checks.industry, '行业前景'],
    ['质', checks.quality, '公司质地'],
    ['归', meanReversion, '均值回归确认'],
    ['催', checks.catalyst, '催化剂距离']
  ];
  return layers.map(([label, pass, title]) => `<span class="layer ${pass ? 'pass' : 'pending'}" title="${title}">${label}</span>`).join('');
}

function aiCell(item) {
  const job = aiJobs[item.symbol];
  if (job && ["QUEUED", "RUNNING"].includes(job.status)) {
    return `<button class="ai-cell-button" disabled>AI复核中…</button><span class="company">${esc(job.message)}</span>`;
  }
  if (job && job.status === "FAILED") {
    return `<button class="ai-cell-button ai-run" data-symbol="${item.symbol}">重试AI复核</button><span class="company negative">${esc(job.error || "复核失败")}</span>`;
  }
  const analysis = item.ai_analysis;
  const opportunity = item.opportunity || {};
  if (!analysis) {
    return `<button class="ai-cell-button ai-run" data-symbol="${item.symbol}">立即事件复核</button><span class="company">异动+新闻+SEC披露</span>`;
  }
  const verdictClass = analysis.verdict === '正常' ? 'positive' : analysis.verdict === '恶化' ? 'negative' : 'watch';
  return `<div class="ai-review"><strong class="${verdictClass}">${esc(analysis.event_class || analysis.verdict)}</strong> · 风险${analysis.risk_score ?? '—'} · 置信${analysis.confidence ?? '—'}
    <div class="ai-summary-line">${esc(analysis.summary || '')}</div>
    <button class="ai-cell-button ai-view" data-symbol="${item.symbol}">查看AI依据</button>
    ${!opportunity.ai_fresh ? `<button class="ai-cell-button ai-run" data-symbol="${item.symbol}">更新</button>` : ''}
  </div>`;
}

function matchesFilter(item) {
  const stage = item.opportunity?.stage;
  if (filter === 'ALL') return true;
  if (filter === 'ACTION') return item.opportunity?.can_act;
  if (filter === 'HOLDING') return item.holding;
  return stage === filter;
}

function renderSignals() {
  renderMetrics();
  renderOpportunityCards();
  const query = $('search').value.trim().toUpperCase();
  const rows = signals.filter(item => matchesFilter(item)
    && (sectorFilter === 'ALL' || item.sector === sectorFilter)
    && (!query || item.symbol.includes(query) || item.name.toUpperCase().includes(query)));
  if (!rows.length) {
    $('signalRows').innerHTML = '<tr><td colspan="9" class="empty">当前筛选下没有股票</td></tr>';
    return;
  }
  $('signalRows').innerHTML = rows.map(item => {
    const opportunity = item.opportunity || {};
    const change = Number(item.day_change_pct || 0);
    const missing = (opportunity.missing_hard || []).join('、') || '硬条件已齐';
    return `<tr>
      <td><div class="stock-title"><button class="ticker tech-open" data-symbol="${item.symbol}">${esc(item.symbol)}</button><button class="technical-open tech-open" data-symbol="${item.symbol}">📈 技术分析</button></div><span class="company">${esc(item.name)} · ${esc(item.sector)}</span></td>
      <td><div class="stage-block"><span class="stage ${stageClass(opportunity.stage)}">${esc(opportunity.stage_label)}</span><span class="final-score">综合${opportunity.final_score}分 · ${opportunity.hard_passed}/${opportunity.hard_total}</span></div></td>
      <td>$${Number(item.price || 0).toFixed(2)}<span class="company ${change >= 0 ? 'positive' : 'negative'}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span></td>
      <td>${item.ma50 ? '$' + Number(item.ma50).toFixed(2) : '—'}<span class="company ${Number(item.distance_ma50_pct || 0) >= 0 ? 'positive' : 'negative'}">${item.distance_ma50_pct ?? '—'}%</span></td>
      <td class="${Number(item.drawdown20_pct || 0) <= -8 ? 'positive' : ''}">${item.drawdown20_pct ?? '—'}%<span class="company">20日高点回撤</span></td>
      <td><div class="four-layers">${layerChecks(item)}</div><span class="company">${esc(missing)}</span></td>
      <td>${aiCell(item)}</td>
      <td><div class="next-action">${esc(opportunity.next_action)}</div><span class="company">${esc(opportunity.catalyst_band)}</span></td>
      <td><button class="holding ${item.holding ? 'on' : ''}" data-symbol="${item.symbol}" data-held="${!!item.holding}">${item.holding ? '持仓中' : '设为持仓'}</button></td>
    </tr>`;
  }).join('');
  const mobileLabels = [
    "\u80a1\u7968", "\u673a\u4f1a\u9636\u6bb5", "\u4ef7\u683c / \u4eca\u65e5",
    "50\u65e5\u7ebf", "\u9519\u6740\u5e45\u5ea6", "\u56db\u5c42\u68c0\u67e5",
    "AI / SEC", "\u4e0b\u4e00\u6b65", "\u6301\u4ed3"
  ];
  document.querySelectorAll("#signalRows tr").forEach(row => {
    row.querySelectorAll("td:not([colspan])").forEach((cell, index) => { cell.dataset.label = mobileLabels[index] || ""; });
  });
  document.querySelectorAll('.holding').forEach(button => {
    button.onclick = async () => {
      await get('/api/holding', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({symbol: button.dataset.symbol, held: button.dataset.held !== 'true'})});
      toast(window.ANLI_PUBLIC_MODE ? '本设备持仓标记已更新' : '持仓标记已更新');
      await loadSignals();
    };
  });
  document.querySelectorAll('.ai-run').forEach(button => button.onclick = () => runAI(button.dataset.symbol));
  document.querySelectorAll('.ai-view').forEach(button => button.onclick = () => showAI(button.dataset.symbol));
  document.querySelectorAll('.tech-open').forEach(button => button.onclick = () => loadTechnical(button.dataset.symbol, true));
}

function technicalChart(points) {
  if (!points?.length) return '<p class="empty">暂无图表数据</p>';
  const width = 960, height = 280, pad = 28;
  const values = points.flatMap(point => [point.close, point.ma20, point.ma50]).filter(value => Number.isFinite(Number(value))).map(Number);
  const minimum = Math.min(...values), maximum = Math.max(...values);
  const range = Math.max(maximum - minimum, maximum * 0.02, 1);
  const x = index => pad + index * (width - pad * 2) / Math.max(1, points.length - 1);
  const y = value => height - pad - (Number(value) - minimum) * (height - pad * 2) / range;
  const line = (key, color) => {
    const coords = points.map((point, index) => point[key] == null ? null : `${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`).filter(Boolean).join(' ');
    return `<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  };
  const grids = [0, .25, .5, .75, 1].map(ratio => {
    const gy = pad + ratio * (height - pad * 2);
    const label = (maximum - ratio * range).toFixed(2);
    return `<line x1="${pad}" y1="${gy}" x2="${width - pad}" y2="${gy}" stroke="#1d3a32"/><text x="${pad + 3}" y="${gy - 4}" fill="#6f9185" font-size="10">$${label}</text>`;
  }).join('');
  return `<div class="technical-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="价格、20日均线和50日均线走势图">${grids}${line('close', '#e9f4ef')}${line('ma20', '#64f0b2')}${line('ma50', '#ffbd66')}</svg><div class="chart-legend"><span>白：收盘/现价</span><span>绿：MA20</span><span>橙：MA50</span><span>${esc(points[0].t)} — ${esc(points.at(-1).t)}</span></div></div>`;
}

function renderTechnical(data) {
  const finalClass = ['LONG_READY'].includes(data.final_signal) ? 'positive' : ['SHORT_READY', 'SELL_REVIEW'].includes(data.final_signal) ? 'negative' : 'watch';
  const technicalClass = data.direction === 'LONG' ? 'positive' : data.direction === 'SHORT' ? 'negative' : 'watch';
  const indicators = data.indicators || {};
  const longLabels = {above_ma20: '价格>MA20', above_ma50: '价格>MA50', ma_bullish: 'MA20>MA50', macd_bullish: 'MACD金叉', histogram_positive: '柱线为正', momentum_healthy: 'RSI健康', volume_confirmed: '量能确认'};
  const shortLabels = {below_ma20: '价格<MA20', below_ma50: '价格<MA50', ma_bearish: 'MA20<MA50', macd_bearish: 'MACD死叉', histogram_negative: '柱线为负', momentum_weak: 'RSI偏弱', volume_confirmed: '量能确认'};
  const checkRow = (checks, labels, kind) => Object.entries(labels).map(([key, label]) => `<span class="tech-check ${checks?.[key] ? (kind === 'long' ? 'pass' : 'short-pass') : 'fail'}">${checks?.[key] ? '✓' : '×'} ${label}</span>`).join('');
  const planCard = (plan, kind) => `<article class="trade-plan ${plan.active ? 'active ' + kind : ''}">
    <div><strong>${kind === 'long' ? '做多方案' : '做空方案'}</strong><span>${esc(plan.label)}${plan.active ? ' · 当前方向' : ' · 备用预案'}</span></div>
    <div class="plan-levels"><span>触发价<b>$${Number(plan.trigger).toFixed(2)}</b></span><span>止损<b>$${Number(plan.stop).toFixed(2)}</b></span><span>目标一<b>$${Number(plan.target1).toFixed(2)}</b><small>盈亏比 ${Number(plan.risk_reward1).toFixed(2)}</small></span><span>目标二<b>$${Number(plan.target2).toFixed(2)}</b><small>盈亏比 ${Number(plan.risk_reward2).toFixed(2)}</small></span></div>
    <p>失效条件：${esc(plan.invalidation)}</p>
  </article>`;
  const executionText = data.data.execution_ready ? '官方盘中实时数据：具备执行核对条件' : `当前仅供计划：${data.data.official_realtime ? '非盘中或报价超过5分钟' : '不是官方实时行情'}`;
  $('technicalSource').textContent = `${data.data.provider} · ${data.data.timeframe} · ${data.data.market_session} · ${data.data.quote_age_minutes == null ? '报价年龄未知' : '报价' + data.data.quote_age_minutes + '分钟前'}`;
  $('technicalContent').innerHTML = `<div class="technical-head">
    <div><span class="option-symbol">${esc(data.symbol)}</span><b>$${Number(data.price).toFixed(2)}</b></div>
    <div class="technical-verdict"><span class="${technicalClass}">${esc(data.technical_label)}</span><strong class="${finalClass}">${esc(data.final_label)}</strong><small>${esc(data.reason)}</small></div>
  </div>
  <div class="execution-gate ${data.data.execution_ready ? 'ready' : 'blocked'}">${data.data.execution_ready ? '✓' : '⚠'} ${esc(executionText)}</div>
  <div class="direction-scores"><div class="long-score"><span>做多评分</span><b>${data.long_score}/${data.score_total}</b><i style="width:${data.long_score / data.score_total * 100}%"></i></div><div class="short-score"><span>做空评分</span><b>${data.short_score}/${data.score_total}</b><i style="width:${data.short_score / data.score_total * 100}%"></i></div></div>
  <div class="check-section"><b>做多条件</b><div class="tech-checks">${checkRow(data.long_checks, longLabels, 'long')}</div><b>做空条件</b><div class="tech-checks">${checkRow(data.short_checks, shortLabels, 'short')}</div></div>
  <div class="trade-plans">${planCard(data.plans.long, 'long')}${planCard(data.plans.short, 'short')}</div>
  ${technicalChart(data.chart)}
  <div class="indicator-grid">
    <article><span>趋势</span><b>MA20 $${Number(indicators.ma20).toFixed(2)}</b><small>MA50 $${Number(indicators.ma50).toFixed(2)}</small></article>
    <article><span>动量</span><b>RSI14 ${Number(indicators.rsi14).toFixed(1)}</b><small>${Number(indicators.rsi14) >= 70 ? '偏热' : Number(indicators.rsi14) < 40 ? '偏弱' : '中性区间'}</small></article>
    <article><span>MACD柱线</span><b>${Number(indicators.macd_histogram).toFixed(3)}</b><small>MACD ${Number(indicators.macd).toFixed(3)} / 信号 ${Number(indicators.macd_signal).toFixed(3)}</small></article>
    <article><span>波动</span><b>ATR ${Number(indicators.atr14).toFixed(2)}</b><small>占股价 ${Number(indicators.atr_pct).toFixed(2)}%</small></article>
    <article><span>关键位置</span><b>支撑 $${Number(indicators.support20).toFixed(2)}</b><small>阻力 $${Number(indicators.resistance20).toFixed(2)}</small></article>
    <article><span>布林带 / 量能</span><b>$${Number(indicators.bollinger_lower).toFixed(2)}–$${Number(indicators.bollinger_upper).toFixed(2)}</b><small>量比 ${Number(indicators.volume_ratio).toFixed(2)}</small></article>
  </div><p class="option-warning">${esc(data.warning)}</p>`;
}
async function loadTechnical(symbol, shouldScroll = false) {
  technicalSymbol = symbol;
  if (shouldScroll) {
    $('technicalContent').innerHTML = `<p class="empty">正在计算 ${esc(symbol)} 技术指标…</p>`;
    $('technicalDetail').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  try {
    renderTechnical(await get(`/api/technical?symbol=${encodeURIComponent(symbol)}`));
  } catch (error) {
    $('technicalContent').innerHTML = `<p class="empty negative">技术分析读取失败：${esc(error.message)}</p>`;
  }
}
function fundamentalGrid(analysis) {
  const labels = {revenue: '营收', net_income: '净利润', operating_income: '经营利润', operating_cash_flow: '经营现金流', assets: '总资产', liabilities: '总负债'};
  const metrics = analysis.fundamentals?.metrics || {};
  const cells = Object.entries(labels).map(([key, label]) => {
    const latest = (metrics[key] || [])[0];
    if (!latest) return `<div class="fundamental-item"><b>${label}</b>暂无SEC数据</div>`;
    return `<div class="fundamental-item"><b>${label}</b>${fmtNumber(latest.value)} ${esc(latest.unit)}<br>${esc(latest.form)} · ${esc(latest.fiscal_period || '')} · 截至${esc(latest.end || '')}</div>`;
  });
  return cells.join('');
}

async function showAI(symbol) {
  let analysis = aiAnalyses[symbol];
  if (!analysis) {
    try {
      analysis = await get(`/api/ai/analysis?symbol=${encodeURIComponent(symbol)}`);
    } catch (singleError) {
      if (window.ANLI_PUBLIC_MODE || ![404, 405].includes(singleError.status)) {
        toast(`AI / SEC 详情暂不可用：${singleError.message}`);
        return;
      }
      try {
        const legacyAnalyses = await get('/api/ai/analyses');
        analysis = legacyAnalyses.find(item => item.symbol === symbol);
        if (!analysis) throw singleError;
      } catch (error) {
        toast(`AI / SEC 详情暂不可用：${error.message}`);
        return;
      }
    }
    aiAnalyses[symbol] = analysis;
  }
  const list = (values, empty) => (values || []).map(value => `<li>${esc(value)}</li>`).join('') || `<li>${esc(empty)}</li>`;
  const reasons = list(analysis.reasons, '暂无详细判断依据');
  const flags = list(analysis.red_flags, '未识别到明确红旗，但仍需核实原始材料');
  const positives = list(analysis.positive_factors, '暂无明确积极因素');
  const gaps = list(analysis.evidence_gaps, 'AI未列出额外证据缺口');
  const nextChecks = list(analysis.next_checks, '等待下一轮新闻与SEC披露');
  const context = analysis.market_context || {};
  const move = (label, price, change) => `<article><span>${label}</span><b>${price == null ? '—' : '$' + Number(price).toFixed(2)}</b><small class="${Number(change || 0) >= 0 ? 'positive' : 'negative'}">${change == null ? '—' : (Number(change) >= 0 ? '+' : '') + Number(change).toFixed(2) + '%'}</small></article>`;
  const sessionLabels = {PREMARKET: '盘前', REGULAR: '盘中', AFTERHOURS: '盘后', WEEKEND: '周末', OVERNIGHT: '隔夜', UNKNOWN: '时段未知'};
  const newsRows = (analysis.news_items || []).filter(item => item.age_hours != null && Number(item.age_hours) <= 72);
  const renderNews = item => {
    const url = safeExternalUrl(item.url);
    const title = esc(item.title);
    const sourceLink = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<span>${title}</span>`;
    return `<article class="event-news ${item.risk_keyword_hit ? 'risk-headline' : ''}"><div><span class="session-tag">${esc(sessionLabels[item.session] || item.session || '时段未知')}</span>${item.breaking_6h ? '<span class="breaking-tag">6小时内</span>' : ''}${item.risk_keyword_hit ? '<span class="risk-tag">高风险词线索</span>' : ''}<b>${esc(item.publisher)}</b><small>${Number(item.age_hours) < 1 ? Math.max(1, Math.round(Number(item.age_hours) * 60)) + '分钟前' : Number(item.age_hours).toFixed(1) + '小时前'} · ${esc(item.published_at || '时间未知')} · 来源${esc(item.source_quality || '待核实')}</small></div>${sourceLink}</article>`;
  };
  const breakingNews = newsRows.filter(item => Number(item.age_hours) <= 6).slice(0, 12).map(renderNews).join('') || '<p class="empty">过去6小时没有取得可验证的突发新闻；这不等于确认没有黑天鹅。</p>';
  const backgroundNews = newsRows.filter(item => Number(item.age_hours) > 6).slice(0, 8).map(renderNews).join('') || '<p class="empty">没有其他72小时背景新闻。</p>';
  const filings = (analysis.sec_filings || []).slice(0, 10).map(item => {
    const url = safeExternalUrl(item.url);
    const body = `<b>${esc(item.form)}</b><span>${esc(item.filed_at || '日期未知')} · ${esc(item.items || item.description || '公司披露')}</span>`;
    return url
      ? `<a class="filing-item" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${body}</a>`
      : `<div class="filing-item">${body}</div>`;
  }).join('') || '<p class="empty">本次没有取得SEC近期申报目录。</p>';
  const quality = analysis.evidence_quality || {};
  const eventClass = analysis.event_class || '旧版复核';
  const eventClassStyle = ['黑天鹅', '基本面恶化'].includes(eventClass) ? 'negative' : eventClass === '潜在错杀' || eventClass === '利好催化' ? 'positive' : 'watch';
  const sources = (analysis.sources || []).map(source => ({...source, safeUrl: safeExternalUrl(source.url)})).filter(source => source.safeUrl).map(source => `<a href="${esc(source.safeUrl)}" target="_blank" rel="noopener noreferrer">${esc(source.publisher)}：${esc(source.title)}</a>`).join('') || '本次未获得可用来源';
  $('aiDetail').innerHTML = `<div class="panel-title"><h2>${esc(symbol)} AI事件驱动复核</h2><span>${fmtTime(analysis.analyzed_at)} · ${esc(analysis.model)}</span></div>
    <div class="event-verdict"><div><span class="event-class ${eventClassStyle}">${esc(eventClass)}</span><b>紧急度：${esc(analysis.event_urgency || '未评级')}</b><strong>${esc(analysis.entry_conclusion || '等待确认')}</strong></div><p>${esc(analysis.summary || '')}</p><small>买入门槛：${esc(analysis.buy_gate)} · 风险 ${analysis.risk_score ?? '—'} / 100 · 置信度 ${analysis.confidence ?? '—'} / 100 · 护城河 ${esc(analysis.moat)}</small></div>
    <div class="market-moves">${move('盘前', context.premarket_price, context.premarket_change_pct)}${move('盘中', context.regular_price || context.price, context.regular_change_pct ?? context.day_change_pct)}${move('盘后', context.afterhours_price, context.afterhours_change_pct)}</div>
    <div class="event-driver"><h3>最可能的关键事件</h3><p>${esc(analysis.key_event || '尚未形成事件结论')}</p><h3>事件与股价波动是否对应</h3><p>${esc(analysis.price_move_driver || '尚未完成时间对应分析')}</p></div>
    <div class="evidence-quality"><b>证据覆盖：${esc(quality.grade || '旧版分析')}</b><span>6小时突发 ${quality.breaking_6h ?? '—'} · 24小时新闻 ${quality.news_24h ?? '—'} · 高风险词线索 ${quality.risk_keyword_count ?? '—'} · 72小时内SEC ${quality.recent_sec_72h ?? '—'}</span><small>${esc(quality.limitation || '旧版分析未记录证据覆盖质量')}</small></div>
    <h3>突发新闻（仅显示6小时内）</h3><div class="event-news-list">${breakingNews}</div><h3>近72小时背景新闻</h3><div class="event-news-list">${backgroundNews}</div>
    <h3>SEC近期官方申报</h3><div class="filing-list">${filings}</div>
    <h3>SEC最近披露财务数据</h3><div class="fundamental-grid">${fundamentalGrid(analysis)}</div>
    <div class="ai-reason-grid"><section><h3>判断依据</h3><ul>${reasons}</ul></section><section><h3>风险红旗</h3><ul>${flags}</ul></section><section><h3>积极因素</h3><ul>${positives}</ul></section><section><h3>证据缺口</h3><ul>${gaps}</ul></section><section><h3>接下来必须核查</h3><ul>${nextChecks}</ul></section></div>
    <h3>全部来源链接</h3><div class="ai-sources">${sources}</div>`;
  $('aiDetail').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function runAI(symbol) {
  try {
    activeAiSymbol = symbol;
    delete aiAnalyses[symbol];
    const response = await get('/api/ai/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({symbol})});
    if (response.job) aiJobs[symbol] = response.job;
    renderSignals();
    toast(`${symbol} AI深度复核已进入队列，页面会自动显示进度`);
  } catch (error) {
    toast(`${symbol} AI复核未启动：${error.message}`);
  }
}

const marketAssetLabels = {
  SPY: '标普500', QQQ: '纳斯达克100', '^IXIC': '纳斯达克综合', RSP: '标普等权', IWM: '小盘股', DIA: '道指',
  '^VIX': 'VIX', '^TNX': '10年期收益率', 'DX-Y.NYB': '美元指数'
};

function nasdaqCandlestick(points) {
  if (!Array.isArray(points) || points.length < 20) return '<p class="empty">纳斯达克日线数据不足，暂不能绘制可靠K线。</p>';
  const width = 1200, height = 500, left = 64, right = 18, top = 18, priceBottom = 370, volumeTop = 395, bottom = 470;
  const priceValues = points.flatMap(p => [p.low, p.high, p.ma20, p.ma50, p.ma200]).filter(v => Number.isFinite(Number(v))).map(Number);
  let minimum = Math.min(...priceValues), maximum = Math.max(...priceValues);
  const padding = Math.max(1, (maximum - minimum) * 0.05); minimum -= padding; maximum += padding;
  const range = maximum - minimum || 1;
  const y = value => top + (maximum - Number(value)) / range * (priceBottom - top);
  const step = (width - left - right) / points.length;
  const candleWidth = Math.max(1.4, Math.min(6, step * 0.66));
  const maxVolume = Math.max(...points.map(p => Number(p.volume || 0)), 1);
  const grids = Array.from({length: 6}, (_, i) => {
    const ratio = i / 5, gy = top + ratio * (priceBottom - top), value = maximum - ratio * range;
    return `<line x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}" class="k-grid"/><text x="${left - 8}" y="${gy + 4}" text-anchor="end" class="k-axis">${value.toLocaleString('en-US',{maximumFractionDigits:0})}</text>`;
  }).join('');
  const candles = points.map((p, i) => {
    const x = left + i * step + step / 2, openY = y(p.open), closeY = y(p.close), highY = y(p.high), lowY = y(p.low);
    const rising = Number(p.close) >= Number(p.open), cls = rising ? 'k-up' : 'k-down';
    const bodyY = Math.min(openY, closeY), bodyHeight = Math.max(1, Math.abs(closeY - openY));
    const volumeHeight = Number(p.volume || 0) / maxVolume * (bottom - volumeTop);
    return `<g class="k-candle"><title>${esc(p.date)}  开 ${Number(p.open).toFixed(2)}  高 ${Number(p.high).toFixed(2)}  低 ${Number(p.low).toFixed(2)}  收 ${Number(p.close).toFixed(2)}  量 ${fmtNumber(p.volume)}</title><line x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}" class="${cls}"/><rect x="${x - candleWidth / 2}" y="${bodyY}" width="${candleWidth}" height="${bodyHeight}" class="${cls}"/><rect x="${x - candleWidth / 2}" y="${bottom - volumeHeight}" width="${candleWidth}" height="${volumeHeight}" class="${cls} k-volume"/></g>`;
  }).join('');
  const line = (key, cls) => {
    let path = '', started = false;
    points.forEach((p, i) => {
      if (p[key] == null) { started = false; return; }
      const x = left + i * step + step / 2, py = y(p[key]);
      path += `${started ? 'L' : 'M'}${x.toFixed(2)},${py.toFixed(2)} `; started = true;
    });
    return `<path d="${path}" class="${cls}" fill="none"/>`;
  };
  const tickIndices = [...new Set([0, Math.floor(points.length / 4), Math.floor(points.length / 2), Math.floor(points.length * 3 / 4), points.length - 1])];
  const dateTicks = tickIndices.map(i => { const x = left + i * step + step / 2; return `<line x1="${x}" y1="${bottom}" x2="${x}" y2="${bottom + 5}" class="k-grid"/><text x="${x}" y="${bottom + 19}" text-anchor="middle" class="k-axis">${esc(points[i].date.slice(5))}</text>`; }).join('');
  const latest = points.at(-1), latestY = y(latest.close);
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="QQQ最近${points.length}个交易日日K线图">${grids}<line x1="${left}" y1="${volumeTop}" x2="${width-right}" y2="${volumeTop}" class="k-separator"/>${candles}${line('ma20','k-ma20')}${line('ma50','k-ma50')}${line('ma200','k-ma200')}<line x1="${left}" y1="${latestY}" x2="${width-right}" y2="${latestY}" class="k-latest"/><text x="${width-right-2}" y="${latestY-5}" text-anchor="end" class="k-latest-label">${Number(latest.close).toLocaleString('en-US',{maximumFractionDigits:2})}</text>${dateTicks}<text x="${left-8}" y="${volumeTop+12}" text-anchor="end" class="k-axis">成交量</text></svg>`;
}
function renderMarketOverview(data) {
  const score = Number(data.score || 0);
  const tone = data.regime === 'DOWNTREND' ? 'negative' : data.regime === 'STRONG_LOW_VOL' ? 'positive' : 'watch';
  $('marketScore').textContent = score;
  $('marketScore').className = tone;
  $('marketRegime').textContent = data.regime_label || '数据不足';
  $('marketRegime').className = `market-regime-tag ${tone}`;
  $('marketPosition').textContent = `当前位置：${data.position_label || '待确认'}`;
  $('marketAction').textContent = data.action || '等待市场数据完整后再行动。';
  $('marketExposure').textContent = `风险预算建议：${data.exposure_guidance || '等待确认'}`;
  $('marketAsOf').textContent = `${data.provider || '公开行情'} · 数据${data.as_of ? new Date(data.as_of).toLocaleString('zh-CN') : '时间未知'} · 计算${fmtTime(data.calculated_at)}`;
  const wanted = ['SPY', 'QQQ', '^IXIC', 'RSP', 'IWM', '^VIX', '^TNX', 'DX-Y.NYB'];
  $('marketAssets').innerHTML = wanted.map(symbol => {
    const item = data.assets?.[symbol] || {};
    const change = item.day_change_pct;
    const changeClass = Number(change || 0) >= 0 ? 'positive' : 'negative';
    const maText = symbol.startsWith('^') || symbol === 'DX-Y.NYB' ? '' : `<small>20/50/200日线：${item.above_ma20 ? '上' : '下'} / ${item.above_ma50 ? '上' : '下'} / ${item.above_ma200 ? '上' : '下'}</small>`;
    return `<article><span>${esc(marketAssetLabels[symbol] || symbol)}</span><b>${item.price == null ? '—' : Number(item.price).toFixed(symbol === '^TNX' ? 3 : 2)}</b><em class="${changeClass}">${change == null ? '—' : (Number(change) >= 0 ? '+' : '') + Number(change).toFixed(2) + '%'}</em>${maText}</article>`;
  }).join('');
  const nasdaq = data.nasdaq_analysis || {};
  const ixic = data.assets?.['^IXIC'] || {};
  $('marketNasdaq').innerHTML = `<div><span>NASDAQ COMPOSITE</span><h3>纳斯达克综合指数：${esc(nasdaq.trend || '待确认')}</h3><p>${esc(nasdaq.summary || '数据正在初始化')}</p></div><div class="nasdaq-levels"><span>距20日线<b>${ixic.distance_ma20_pct == null ? '—' : Number(ixic.distance_ma20_pct).toFixed(2) + '%'}</b></span><span>距50日线<b>${ixic.distance_ma50_pct == null ? '—' : Number(ixic.distance_ma50_pct).toFixed(2) + '%'}</b></span><span>距200日线<b>${ixic.distance_ma200_pct == null ? '—' : Number(ixic.distance_ma200_pct).toFixed(2) + '%'}</b></span><span>距52周高点<b>${ixic.distance_high_52w_pct == null ? '—' : Number(ixic.distance_high_52w_pct).toFixed(2) + '%'}</b></span></div>`;
  $('nasdaqKline').innerHTML = nasdaqCandlestick(data.nasdaq_chart || []);
  const chartRows = data.nasdaq_chart || [];
  $('nasdaqChartSubtitle').textContent = chartRows.length ? `${chartRows[0].date} 至 ${chartRows.at(-1).date} · ${chartRows.length}根日K · OHLC、成交量与MA20/50/200` : '日K数据不足';
  $('marketChecks').innerHTML = (data.checks || []).map(item => {
    const stateClass = ['通过', '允许'].includes(item.status) ? 'positive' : ['不通过', '防守'].includes(item.status) ? 'negative' : 'watch';
    return `<article><span class="market-step">${item.step}</span><div><h4>${esc(item.name)}<b class="${stateClass}">${esc(item.status)}</b></h4><p>${esc(item.detail)}</p></div></article>`;
  }).join('') || '<p class="empty">市场环境数据暂未形成。</p>';
  const breadth = data.breadth || {};
  $('marketLimitations').textContent = `观察池宽度：20日线${breadth.above_ma20_pct ?? '—'}% · 50日线${breadth.above_ma50_pct ?? '—'}% · 200日线${breadth.above_ma200_pct ?? '—'}%（${breadth.sample_size ?? 0}/${breadth.universe_size ?? 0}）｜${data.limitations || ''}`;
}

function renderQQQRadar(data) {
  const recommendation = data.recommendation || {};
  const source = data.data || {};
  const frames = data.timeframes || {};
  const sideClass = recommendation.side === 'SHORT' ? 'negative' : recommendation.technical_setup_ready ? 'positive' : 'watch';
  $('qqqRadarScore').textContent = Number.isFinite(Number(recommendation.score)) ? Number(recommendation.score).toFixed(0) : '—';
  $('qqqRadarStance').textContent = recommendation.stance || '观望';
  $('qqqRadarStance').className = `qqq-radar-tag ${sideClass}`;
  $('qqqRadarHeadline').textContent = recommendation.headline || '尚未形成完整条件';
  $('qqqRadarNext').textContent = recommendation.next_condition || '等待多周期方向一致。';
  $('qqqRadarGrade').textContent = `${recommendation.grade || '继续等待'} · QQQ $${Number(data.price || 0).toFixed(2)}`;
  $('qqqRadarAsOf').textContent = `${source.provider || '公开行情'} · ${String(source.quote_time || '').replace('T', ' ').slice(0, 16) || '时间未知'}`;
  $('qqqRadarGate').className = `qqq-radar-gate ${source.execution_ready ? 'ready' : 'blocked'}`;
  $('qqqRadarGate').textContent = source.execution_ready ? '行情时效闸门已通过；仍需人工核对仓位与止损。' : '当前为公开近实时或非盘中数据；执行前请用券商实时价格复核。';
  const frameOrder = ['15m', '1h', '4h', '1D', '1W'];
  $('qqqRadarFrames').innerHTML = frameOrder.map(label => {
    const frame = frames[label] || {};
    const trend = frame.sufficient ? frame.trend : '数据不足';
    const trendClass = trend === 'UP' ? 'positive' : trend === 'DOWN' ? 'negative' : 'watch';
    const rsi = frame.indicators?.rsi14;
    return `<article><span>${label}</span><b class="${trendClass}">${esc(trend)}</b><small>${rsi == null ? '等待指标' : 'RSI ' + Number(rsi).toFixed(1)}${frame.sufficient ? ' · ' + (Number(frame.trend_score) > 0 ? '+' : '') + Number(frame.trend_score).toFixed(0) : ''}</small></article>`;
  }).join('');
  $('qqqRadarLevels').innerHTML = `<article><span>计划入场</span><b>$${Number(recommendation.entry || 0).toFixed(2)}</b></article><article class="stop"><span>失效 / 止损</span><b>$${Number(recommendation.stop || 0).toFixed(2)}</b></article><article class="target"><span>情景目标</span><b>$${Number(recommendation.target || 0).toFixed(2)}</b></article><article><span>下一动作</span><b>${recommendation.execution_ready ? '人工执行核对' : recommendation.technical_setup_ready ? '等待实时数据' : '继续观察'}</b></article>`;
}

async function loadMarketOverview() {
  try {
    renderQQQRadar(await get('/api/qqq-analysis'));
  } catch (error) {
    $('qqqRadarGate').className = 'qqq-radar-gate blocked';
    $('qqqRadarGate').textContent = `QQQ 决策雷达暂不可用：${esc(error.message)}`;
  }
}
async function loadStatus() {
  const status = await get('/api/status');
  const ageMinutes = status.quote_age_seconds == null ? null : Math.round(status.quote_age_seconds / 60);
  $('connection').textContent = status.last_error ? '异常' : status.quote_is_fresh ? '盘中近实时' : status.market_session_label || '已连接';
  $('connection').className = status.last_error ? 'negative' : status.quote_is_fresh ? 'positive' : 'watch';
  const freshnessText = status.market_session === 'REGULAR' ? (ageMinutes == null ? '报价时间未知' : `报价${ageMinutes}分钟前`) : '当前显示最近常规交易时段报价';
  $('feed').textContent = status.last_error ? String(status.last_error).slice(0, 55) : `${status.provider || status.feed} · ${status.market_session_label || ''} · ${freshnessText}`;
  $('updated').textContent = fmtTime(status.market_data_time || status.last_refresh);
  $('poll').textContent = `每 ${status.poll_seconds} 秒 · ${status.ticker_count}只`;
  $('setup').classList.toggle('hidden', !status.last_error);
  renderSectors(status.sector_status);
}

function renderSectorPulse(data) {
  const stateStyles = {REVERSAL_ALERT: 'reversal', TREND_CONFIRMATION: 'confirmed', RISK_OFF: 'risk', MIXED: 'mixed'};
  $('pulseState').className = `pulse-state ${stateStyles[data.state] || 'mixed'}`;
  $('pulseState').textContent = data.state_label || '数据不足';
  $('pulseAction').textContent = data.action || '等待板块数据';
  $('pulseConfidence').textContent = `情景判断置信度：${data.confidence || '—'} · 不是收益保证`;
  const benchmark = data.benchmark || {};
  $('pulseMetrics').innerHTML = [
    ['上涨广度', `${data.positive_count || 0}/${data.members || 0}`, `${Number(data.breadth_pct || 0).toFixed(1)}%`],
    ['中位涨幅', `${Number(data.median_change_pct || 0) >= 0 ? '+' : ''}${Number(data.median_change_pct || 0).toFixed(2)}%`, `≥3%共${data.strong_count || 0}只`],
    ['站上50日线', `${data.above_ma50_count || 0}/${data.members || 0}`, `${Number(data.above_ma50_pct || 0).toFixed(1)}%`],
    [data.benchmark_symbol || 'SOXX', `${Number(benchmark.change_pct || 0) >= 0 ? '+' : ''}${Number(benchmark.change_pct || 0).toFixed(2)}%`, `距MA50 ${Number(benchmark.distance_ma50_pct || 0).toFixed(2)}%`],
  ].map(item => `<article><span>${esc(item[0])}</span><b>${esc(item[1])}</b><small>${esc(item[2])}</small></article>`).join('');
  $('pulseLeaders').innerHTML = (data.leaders || []).map(item => `<article class="pulse-leader ${String(item.decision || '').toLowerCase()}">
    <div><b>${esc(item.symbol)}</b><span>${Number(item.change_pct) >= 0 ? '+' : ''}${Number(item.change_pct).toFixed(2)}%</span></div>
    <strong>${esc(item.decision_label)}</strong><p>${esc(item.trigger)}</p><small>20日回撤 ${Number(item.drawdown20_pct).toFixed(2)}% · 距MA50 ${Number(item.distance_ma50_pct).toFixed(2)}%</small>
  </article>`).join('') || '<p class="empty">暂无候选</p>';
  const analogs = data.analogs || {};
  $('pulseAnalogs').innerHTML = `<div class="analog-head"><b>${analogs.sample_count || 0}</b><span>个近一年相似事件</span></div>
    <div class="analog-grid">${[1, 3, 5].map(day => { const row = analogs[`day_${day}`] || {}; return `<article><span>${day}日后</span><b>${!analogs.sufficient || row.win_rate == null ? '样本不足' : `${Number(row.win_rate).toFixed(1)}%上涨`}</b><small>中位回报 ${!analogs.sufficient || row.median_return_pct == null ? '—' : `${Number(row.median_return_pct).toFixed(2)}%`}</small></article>`; }).join('')}</div>
    <p>${esc(analogs.note || '')}</p>`;
  $('pulseLadder').innerHTML = (data.decision_ladder || []).map((step, index) => `<div><b>${index + 1}</b><span>${esc(step)}</span></div>`).join('');
}

async function loadSectorPulse() {
  try { renderSectorPulse(await get('/api/sector-pulse')); }
  catch (error) { $('pulseLeaders').innerHTML = `<p class="empty negative">板块信号暂不可用：${esc(error.message)}</p>`; }
}
async function loadSignals() {
  signals = await get('/api/opportunities');
  renderSignals();
}

async function loadAI() {
  const [status, jobs] = await Promise.all([get('/api/ai/status'), get('/api/ai/jobs')]);
  $('aiConnection').textContent = status.configured ? (status.last_error ? '接口异常' : '已连接') : '未配置';
  $('aiConnection').className = status.configured && !status.last_error ? 'positive' : 'negative';
  $('aiModel').textContent = status.configured ? `${status.model} · ${Math.round(status.scan_seconds / 60)}分钟扫描` : 'AI接口未启用';
  // Full AI evidence is loaded per symbol on demand.
  const nextJobs = Object.fromEntries(jobs.map(job => [job.symbol, job]));
  if (aiJobsInitialized) {
    for (const job of jobs) {
      const previous = aiJobs[job.symbol];
      if (job.status === 'COMPLETE' && previous?.status !== 'COMPLETE') {
        delete aiAnalyses[job.symbol];
        toast(`${job.symbol} AI复核完成：${job.verdict || '已生成结论'}`);
        if (activeAiSymbol === job.symbol) showAI(job.symbol);
      }
      if (job.status === 'FAILED' && previous?.status !== 'FAILED') toast(`${job.symbol} AI复核失败：${job.error || '未知错误'}`);
    }
  }
  aiJobs = nextJobs;
  aiJobsInitialized = true;
}

async function loadAlerts() {
  const alerts = await get('/api/alerts');
  $('alerts').innerHTML = alerts.length ? alerts.slice(0, 20).map(alert => `<div class="alert-item"><strong>${esc(alert.symbol)}</strong> ${esc(alert.message)}<time>${new Date(alert.created_at).toLocaleString('zh-CN')}</time></div>`).join('') : '<p class="empty">暂无提醒</p>';
  for (const alert of alerts) {
    if (!firstAlertLoad && !seenAlerts.has(alert.id)) localNotify(alert);
    seenAlerts.add(alert.id);
  }
  firstAlertLoad = false;
}

document.querySelectorAll('.tab').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach(item => item.classList.remove('active'));
    tab.classList.add('active'); filter = tab.dataset.filter; renderSignals();
  };
});
$('search').oninput = renderSignals;
$('sectorSelect').onchange = event => { sectorFilter = event.target.value; renderSignals(); };
$('notifyBtn').onclick = async () => {
  if (!('Notification' in window)) return toast('当前浏览器不支持系统通知');
  const permission = await Notification.requestPermission();
  toast(permission === 'granted' ? '本地声音和桌面提醒已开启' : '未获得通知权限');
};
$('refreshBtn').onclick = async () => {
  await get('/api/refresh', {method: 'POST'});
  if (window.ANLI_PUBLIC_MODE) {
    await tick();
    toast('已检查最新云端快照');
  } else {
    toast('已请求刷新48只股票，结果会自动更新');
  }
};
document.querySelectorAll('[data-detail-href]').forEach(card => {
  const openDetail = () => window.location.assign(card.dataset.detailHref);
  card.addEventListener('click', event => {
    if (event.target.closest('a,button,input,select,textarea,summary,[contenteditable="true"]')) return;
    if (window.getSelection && String(window.getSelection())) return;
    openDetail();
  });
  card.addEventListener('keydown', event => {
    if (event.target !== card || !['Enter', ' '].includes(event.key)) return;
    event.preventDefault();
    openDetail();
  });
});


let marketOverviewData = null;
let eventCalendarData = null;

function renderJointConclusion() {
  if (!marketOverviewData || !eventCalendarData) return;
  const firstWeek = eventCalendarData.weeks?.[0] || {};
  const position = marketOverviewData.position_code || 'UNKNOWN';
  const root = $('marketJointAction');
  const highPosition = ['HIGH', 'HIGH_RISK'].includes(position);
  const highEventRisk = Number(firstWeek.risk_score || 0) >= 4;
  root.className = `market-joint-action ${highPosition && highEventRisk ? 'danger' : highEventRisk ? 'caution' : 'normal'}`;
  if (highPosition && highEventRisk) {
    root.innerHTML = `<strong>高位事件前区</strong><p>QQQ位于${esc(marketOverviewData.position_label)}，且${esc(firstWeek.label || '首周')}为${esc(firstWeek.risk_label)}风险周。已有盈利仓优先考虑减仓 1/3–1/2；不新增同方向高波动仓位，事件结果确认后再评估。</p>`;
  } else if (highEventRisk) {
    root.innerHTML = `<strong>重大事件周</strong><p>当前位置为${esc(marketOverviewData.position_label)}，${esc(firstWeek.label || '首周')}事件风险${esc(firstWeek.risk_label)}。新开仓缩小，避免在事件前追涨；已有盈利仓提高保护线。</p>`;
  } else if (highPosition) {
    root.innerHTML = `<strong>高位利润保护</strong><p>未来一周事件压力暂不极端，但QQQ已在${esc(marketOverviewData.position_label)}。停止追涨，盈利仓按计划分批兑现。</p>`;
  } else {
    root.innerHTML = `<strong>按趋势执行</strong><p>当前位置为${esc(marketOverviewData.position_label)}，${esc(firstWeek.label || '首周')}事件风险${esc(firstWeek.risk_label || '待确认')}。可按规则寻找回踩机会，但不取消止损与仓位上限。</p>`;
  }
}

function renderMarketOverview(data) {
  marketOverviewData = data;
  const score = Number(data.score || 0);
  const tone = data.regime === 'DOWNTREND' ? 'negative' : data.regime === 'STRONG_LOW_VOL' ? 'positive' : 'watch';
  $('marketScore').textContent = score;
  $('marketScore').className = tone;
  $('marketRegime').textContent = data.regime_label || '数据不足';
  $('marketRegime').className = `market-regime-tag ${tone}`;
  $('marketPosition').textContent = `当前位置：${data.position_label || '待确认'}`;
  $('marketAction').textContent = data.action || '等待市场数据完整后再行动。';
  $('marketExposure').textContent = `风险预算建议：${data.exposure_guidance || '等待确认'}`;
  $('marketAsOf').textContent = `${data.provider || '公开行情'} · 行情${data.as_of ? new Date(data.as_of).toLocaleString('zh-CN') : '时间未知'} · 计算${fmtTime(data.calculated_at)}`;
  const qqq = data.assets?.QQQ || {};
  const metric = (label, value, hint = '') => `<article><span>${label}</span><b>${value}</b><small>${hint}</small></article>`;
  const streak = Number(qqq.daily_streak || 0);
  $('marketPositionMetrics').innerHTML = [
    metric('距52周高点', qqq.distance_high_52w_pct == null ? '—' : `${Number(qqq.distance_high_52w_pct).toFixed(2)}%`, '越接近0越处于高位'),
    metric('高于50日线', qqq.distance_ma50_pct == null ? '—' : `${Number(qqq.distance_ma50_pct).toFixed(2)}%`, qqq.above_ma50 ? '趋势在50日线上方' : '趋势未通过'),
    metric('RSI（14）', qqq.rsi14 == null ? '—' : Number(qqq.rsi14).toFixed(1), Number(qqq.rsi14 || 0) >= 70 ? '过热观察区' : '未进入极端过热'),
    metric('连续涨跌', streak === 0 ? '0天' : `${streak > 0 ? '上涨' : '下跌'}${Math.abs(streak)}天`, '只描述状态，不单独构成买卖信号'),
  ].join('');
  const chart = data.qqq_chart || [];
  $('marketKline').innerHTML = nasdaqCandlestick(chart);
  $('marketChartSubtitle').textContent = chart.length ? `${chart[0].date} 至 ${chart.at(-1).date} · ${chart.length}根日K · 数据不足时不绘图` : 'QQQ完整OHLCV不足，暂不绘图';
  const wanted = ['SPY', 'QQQ', '^IXIC', 'RSP', 'IWM', '^VIX', '^TNX', 'DX-Y.NYB'];
  $('marketAssets').innerHTML = wanted.map(symbol => {
    const item = data.assets?.[symbol] || {};
    const change = item.day_change_pct;
    const changeClass = Number(change || 0) >= 0 ? 'positive' : 'negative';
    return `<article><span>${esc(marketAssetLabels[symbol] || symbol)}</span><b>${item.price == null ? '—' : Number(item.price).toFixed(symbol === '^TNX' ? 3 : 2)}</b><em class="${changeClass}">${change == null ? '—' : (Number(change) >= 0 ? '+' : '') + Number(change).toFixed(2) + '%'}</em><small>距MA50 ${item.distance_ma50_pct == null ? '—' : Number(item.distance_ma50_pct).toFixed(2) + '%'}</small></article>`;
  }).join('');
  $('marketChecks').innerHTML = (data.checks || []).map(item => {
    const stateClass = ['通过', '允许'].includes(item.status) ? 'positive' : ['不通过', '防守'].includes(item.status) ? 'negative' : 'watch';
    return `<article><span class="market-step">${item.step}</span><div><h4>${esc(item.name)}<b class="${stateClass}">${esc(item.status)}</b></h4><p>${esc(item.detail)}</p></div></article>`;
  }).join('');
  const breadth = data.breadth || {};
  $('marketLimitations').textContent = `数据说明：市场宽度使用当前观察池代理（50日线上方${breadth.above_ma50_pct ?? '—'}%，样本${breadth.sample_size ?? 0}/${breadth.universe_size ?? 0}）；${data.limitations || ''}`;
  renderJointConclusion();
}

function renderEventCalendar(data) {
  eventCalendarData = data;
  const weeks = data.weeks || [];
  const topWeek = [...weeks].sort((a, b) => Number(b.risk_score) - Number(a.risk_score))[0] || {};
  const critical = weeks.flatMap(week => week.events || []).find(event => Number(event.importance) >= 4);
  $('eventVerifiedAt').textContent = `${data.verification_status} · ${new Date(data.verified_at).toLocaleString('zh-CN')}`;
  $('eventVerifiedAt').className = data.verification_status === '已核验' ? 'positive' : 'negative';
  $('eventCalendarSummary').innerHTML = `<article><span>未来4周事件</span><b>${data.event_count || 0}项</b><small>无来源日期不显示</small></article><article><span>最高风险周</span><b>${esc(topWeek.label || '—')} · ${esc(topWeek.risk_label || '—')}</b><small>${topWeek.critical_count || 0}项核心事件</small></article><article><span>最近核心事件</span><b>${esc(critical?.title || '暂无')}</b><small>${critical ? new Date(critical.at_cn).toLocaleString('zh-CN') : '—'}</small></article>`;
  $('eventWeeks').innerHTML = weeks.map(week => `<article class="event-week risk-${week.risk_score}">
    <header><div><span>${esc(week.label)}</span><b>${esc(week.start)} — ${esc(week.end)}</b></div><strong>${esc(week.risk_label)}风险</strong></header>
    <p class="week-action">${esc(week.action)}</p>
    <div class="week-events">${(week.events || []).map(event => {
      const et = new Date(event.at_et);
      const cn = new Date(event.at_cn);
      return `<div class="calendar-event importance-${event.importance}"><time>${et.toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'})} 美东 ${et.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',timeZone:'America/New_York'})}<small>北京时间 ${cn.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small></time><div><span>${esc(event.category)} · ${esc(event.verification)}</span><b>${esc(event.title)}</b><p>${esc(event.note)}</p><small>影响：${esc((event.scope || []).join('、'))}</small></div><a href="${esc(event.source_url)}" target="_blank" rel="noopener noreferrer">核对来源</a></div>`;
    }).join('') || '<p class="empty">该周暂无已核验的重大事件。</p>'}</div>
  </article>`).join('');
  $('eventMethodology').textContent = `${data.methodology} ${data.timezone_note} 核验超过48小时会显示“需要重新核验”，此时不应仅凭日历执行交易。`;
  renderJointConclusion();
}

async function loadMarketOverview() {
  try {
    const [overview, qqq, calendar] = await Promise.all([
      get('/api/market-overview'), get('/api/qqq-analysis'), get('/api/event-calendar')
    ]);
    renderMarketOverview(overview);
    renderQQQRadar(qqq);
    renderEventCalendar(calendar);
  } catch (error) {
    $('marketJointAction').className = 'market-joint-action danger';
    $('marketJointAction').textContent = `大局观或事件数据不完整：${error.message}。当前不输出行动结论。`;
  }
}
let tickInFlight = false;
async function tick() {
  if (tickInFlight || document.hidden) return;
  tickInFlight = true;
  try {
    const results = await Promise.allSettled([
      loadAI(), loadStatus(), loadAlerts(), loadMarketOverview(), loadSectorPulse()
    ]);
    await loadSignals();
    const failures = results
      .filter(result => result.status === 'rejected')
      .map(result => result.reason?.message || '模块读取失败');
    if (failures.length) toast(`部分模块暂不可用：${failures.join('；')}`);
  } catch (error) {
    toast(`股票数据读取失败：${error.message}`);
  }
  finally { tickInFlight = false; }
}

tick();
setInterval(tick, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
setInterval(() => { if (!document.hidden && technicalSymbol) loadTechnical(technicalSymbol); }, 30000);