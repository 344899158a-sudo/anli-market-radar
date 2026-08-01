let activeTechnicalData = null;
let activeTechnicalTimeframe = '1D';

function techNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : '—';
}

function advancedCandlestick(frame) {
  const points = frame?.chart || [];
  if (points.length < 20) return '<p class="empty">该周期K线不足，不能可靠绘图。</p>';
  const width = 1180, height = 520, left = 64, right = 24, top = 20;
  const priceBottom = 365, volumeTop = 398, bottom = 485;
  const values = points.flatMap(point => [point.l, point.h, point.ma20, point.ma50])
    .filter(value => Number.isFinite(Number(value))).map(Number);
  let minimum = Math.min(...values), maximum = Math.max(...values);
  const pad = Math.max((maximum - minimum) * .06, maximum * .005);
  minimum -= pad; maximum += pad;
  const range = maximum - minimum || 1;
  const step = (width - left - right) / points.length;
  const candleWidth = Math.max(1.4, Math.min(8, step * .62));
  const y = value => top + (maximum - Number(value)) / range * (priceBottom - top);
  const x = index => left + step * index + step / 2;
  const maxVolume = Math.max(...points.map(point => Number(point.v) || 0), 1);
  const grids = Array.from({length: 6}, (_, index) => {
    const ratio = index / 5, gy = top + ratio * (priceBottom - top);
    const label = maximum - ratio * range;
    return `<line class="adv-grid" x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}"/>
      <text class="adv-axis" x="4" y="${gy + 4}">$${label.toFixed(2)}</text>`;
  }).join('');
  const candles = points.map((point, index) => {
    const open = Number(point.o), close = Number(point.c), high = Number(point.h), low = Number(point.l);
    const up = close >= open, colorClass = up ? 'adv-up' : 'adv-down';
    const bodyTop = Math.min(y(open), y(close)), bodyHeight = Math.max(1.3, Math.abs(y(open) - y(close)));
    const volumeHeight = (Number(point.v) || 0) / maxVolume * (bottom - volumeTop);
    const title = `${String(point.t).replace('T', ' ').slice(0, 16)}
开 ${open.toFixed(2)}  高 ${high.toFixed(2)}  低 ${low.toFixed(2)}  收 ${close.toFixed(2)}
成交量 ${fmtNumber(point.v)}`;
    return `<g class="adv-candle"><title>${esc(title)}</title>
      <line class="${colorClass}" x1="${x(index)}" y1="${y(high)}" x2="${x(index)}" y2="${y(low)}"/>
      <rect class="${colorClass}" x="${x(index) - candleWidth / 2}" y="${bodyTop}" width="${candleWidth}" height="${bodyHeight}"/>
      <rect class="${up ? 'adv-vol-up' : 'adv-vol-down'}" x="${x(index) - candleWidth / 2}" y="${bottom - volumeHeight}" width="${candleWidth}" height="${volumeHeight}"/>
    </g>`;
  }).join('');
  const polyline = (key, className) => {
    const coords = points.map((point, index) => point[key] == null ? null : `${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`)
      .filter(Boolean).join(' ');
    return `<polyline class="${className}" points="${coords}" fill="none"/>`;
  };
  const zones = (frame.zones || []).slice(0, 5).map(zone => {
    const zy = y(zone.high), zh = Math.max(2, y(zone.low) - y(zone.high));
    return `<g><rect class="adv-zone ${zone.role === '支撑' ? 'support' : 'resistance'}" x="${left}" y="${zy}" width="${width-left-right}" height="${zh}"/>
      <text class="adv-zone-label" x="${width-right-4}" y="${zy + 11}" text-anchor="end">${esc(zone.role)} $${techNumber(zone.level)} · ${zone.touches}次</text></g>`;
  }).join('');
  const trendlines = frame.trendlines || {};
  const trendStart = Math.max(0, points.length - 30);
  const trend = ['upper', 'lower'].map(key => {
    const line = trendlines[key];
    if (!line) return '';
    return `<line class="adv-trendline ${key}" x1="${x(trendStart)}" y1="${y(line.start)}" x2="${x(points.length - 1)}" y2="${y(line.end)}"/>`;
  }).join('');
  const dateTicks = Array.from(new Set([0, Math.floor(points.length * .25), Math.floor(points.length * .5), Math.floor(points.length * .75), points.length - 1]))
    .map(index => `<text class="adv-axis" x="${x(index)}" y="${height - 8}" text-anchor="middle">${esc(String(points[index].t).slice(0, 10))}</text>`).join('');
  return `<div class="advanced-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(frame.timeframe)} K线、均线、趋势线和支撑阻力图">
    ${grids}${zones}${trend}${candles}${polyline('ma20', 'adv-ma20')}${polyline('ma50', 'adv-ma50')}
    <line class="adv-separator" x1="${left}" y1="${volumeTop - 10}" x2="${width-right}" y2="${volumeTop - 10}"/>
    ${dateTicks}
  </svg><div class="advanced-legend"><span class="candle-up">上涨K</span><span class="candle-down">下跌K</span><span class="ma20">MA20</span><span class="ma50">MA50</span><span class="trendline">趋势通道</span><span class="zone">支撑/阻力区</span></div></div>`;
}

function advancedPlan(plan, kind, active) {
  return `<article class="trade-plan ${active ? `active ${kind}` : ''}">
    <div><strong>${kind === 'long' ? '做多计划' : '做空计划'}</strong><span>${active ? '当前优先方向' : '备用情景'}</span></div>
    <div class="plan-levels">
      <span>触发价<b>$${techNumber(plan.trigger)}</b></span>
      <span>止损/失效<b>$${techNumber(plan.stop)}</b></span>
      <span>目标一<b>$${techNumber(plan.target1)}</b><small>盈亏比 ${techNumber(plan.risk_reward1)}</small></span>
      <span>目标二<b>$${techNumber(plan.target2)}</b><small>盈亏比 ${techNumber(plan.risk_reward2)}</small></span>
    </div><p>${esc(plan.invalidation)}</p>
  </article>`;
}

function renderAdvancedFrame() {
  if (!activeTechnicalData) return;
  const frame = activeTechnicalData.timeframes?.[activeTechnicalTimeframe];
  $('advancedFrameChart').innerHTML = advancedCandlestick(frame);
  document.querySelectorAll('.advanced-timeframe-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.timeframe === activeTechnicalTimeframe);
  });
  const indicators = frame?.indicators || {};
  $('advancedFrameStats').innerHTML = frame?.sufficient ? `
    <article><span>趋势评分</span><b class="${frame.trend === 'UP' ? 'positive' : frame.trend === 'DOWN' ? 'negative' : ''}">${frame.trend_score > 0 ? '+' : ''}${frame.trend_score}</b><small>${frame.trend}</small></article>
    <article><span>RSI14</span><b>${techNumber(indicators.rsi14, 1)}</b><small>${Number(indicators.rsi14) >= 70 ? '偏热' : Number(indicators.rsi14) < 40 ? '偏弱' : '中性区间'}</small></article>
    <article><span>MACD</span><b>${techNumber(indicators.macd, 3)}</b><small>${Number(indicators.macd) >= 0 ? '零轴上方' : '零轴下方'}</small></article>
    <article><span>ATR</span><b>${techNumber(indicators.atr14)}</b><small>股价的 ${techNumber(indicators.atr_pct)}%</small></article>
    <article><span>数据完整度</span><b>${techNumber(frame.quality?.ohlcv_complete_pct, 1)}%</b><small>${frame.bars}根K线</small></article>` :
    '<p class="empty">该周期数据不足。</p>';
}

function renderTechnical(data) {
  activeTechnicalData = data;
  const preferred = ['1D', '4h', '1h', '15m', '1W'];
  activeTechnicalTimeframe = preferred.find(label => data.timeframes?.[label]?.sufficient) || data.available_timeframes?.[0] || '1D';
  const biasClass = data.bias === 'LONG' ? 'positive' : data.bias === 'SHORT' ? 'negative' : 'watch';
  const decisionClass = data.decision === 'LONG_READY' ? 'positive' : ['SHORT_READY', 'SELL_REVIEW'].includes(data.decision) ? 'negative' : 'watch';
  const executionText = data.data.execution_ready ? '官方盘中实时数据满足执行核对条件' : '当前行情不是官方盘中5分钟内数据，只能制定计划，不能视为即时下单信号';
  const timeframeOrder = ['15m', '1h', '4h', '1D', '1W'];
  const timeframeCards = timeframeOrder.map(label => {
    const frame = data.timeframes?.[label];
    if (!frame?.sufficient) return `<article class="tf-card unavailable"><span>${label}</span><b>数据不足</b><small>${frame?.bars || 0}根</small></article>`;
    return `<article class="tf-card ${String(frame.trend).toLowerCase()}"><span>${label}</span><b>${frame.trend_score > 0 ? '+' : ''}${frame.trend_score}</b><small>${frame.trend} · RSI ${techNumber(frame.indicators?.rsi14, 1)}</small></article>`;
  }).join('');
  const tabs = timeframeOrder.filter(label => data.timeframes?.[label]).map(label =>
    `<button class="advanced-timeframe-tab ${label === activeTechnicalTimeframe ? 'active' : ''}" data-timeframe="${label}">${label}</button>`).join('');
  const patterns = (data.patterns || []).map(pattern => `<article class="pattern-card ${String(pattern.direction).toLowerCase()}">
    <div><span>${esc(pattern.timeframe)}</span><b>${esc(pattern.name)}</b><em>${techNumber(pattern.confidence, 0)}%</em></div>
    <strong>${esc(pattern.direction)} · ${esc(pattern.status)}</strong>
    <p>${esc(pattern.explanation)}</p>
    <small>触发 $${techNumber(pattern.trigger)} · 失效 $${techNumber(pattern.invalidation)} · 目标 $${techNumber(pattern.target)}</small>
  </article>`).join('') || '<p class="empty">当前没有达到阈值的经典形态，等待结构进一步形成。</p>';
  const backtest = data.backtest || {};
  const backtestRows = [5, 10, 20].map(day => {
    const row = backtest[`day_${day}`] || {};
    return `<article><span>${day}根K线后</span><b>${backtest.sufficient && row.win_rate != null ? `${techNumber(row.win_rate, 1)}%` : '样本不足'}</b><small>同方向中位回报 ${backtest.sufficient && row.median_return_pct != null ? `${techNumber(row.median_return_pct)}%` : '—'}</small></article>`;
  }).join('');
  const errors = Object.entries(data.timeframe_errors || {}).map(([label, message]) => `${label}：${message}`).join('；');
  $('technicalSource').textContent = `${data.data.provider} · 多周期OHLCV · ${data.data.market_session} · ${data.available_timeframes.join('/')}`;
  $('technicalContent').innerHTML = `<div class="advanced-tech-head">
    <div><span class="option-symbol">${esc(data.symbol)}</span><b>$${techNumber(data.price)}</b></div>
    <div class="advanced-consensus"><span class="${biasClass}">${esc(data.bias)}</span><b>${data.consensus_score > 0 ? '+' : ''}${techNumber(data.consensus_score, 1)}</b><small>多周期共振分 · 置信度 ${techNumber(data.confidence, 1)}%</small></div>
    <div class="technical-verdict"><strong class="${decisionClass}">${esc(data.decision_label)}</strong><small>${esc(data.reasoning?.summary)}</small></div>
  </div>
  <div class="execution-gate ${data.data.execution_ready ? 'ready' : 'blocked'}">${data.data.execution_ready ? '✓' : '⚠'} ${esc(executionText)}</div>
  <div class="timeframe-strip">${timeframeCards}</div>
  <div class="advanced-reasoning"><b>AI式结构推理</b><p>${esc(data.reasoning?.summary)}</p><small>原则闸门：${esc(data.reasoning?.principle_gate)} · 数据闸门：${esc(data.reasoning?.data_gate)}</small></div>
  <div class="trade-plans">${advancedPlan(data.plans.long, 'long', data.bias === 'LONG')}${advancedPlan(data.plans.short, 'short', data.bias === 'SHORT')}</div>
  <section class="advanced-chart-section">
    <div class="advanced-chart-head"><div><h3>多周期K线与自动结构</h3><span>真实OHLCV · MA20/MA50 · 趋势通道 · 支撑阻力区</span></div><div class="advanced-timeframe-tabs">${tabs}</div></div>
    <div id="advancedFrameChart"></div><div id="advancedFrameStats" class="advanced-frame-stats"></div>
  </section>
  <section class="advanced-pattern-section"><div class="advanced-section-title"><h3>自动识别形态</h3><span>只有“已确认”形态才可进入执行核对</span></div><div class="pattern-grid">${patterns}</div></section>
  <section class="advanced-backtest"><div><h3>相似技术结构历史验证</h3><p>${esc(backtest.note || '')}</p><small>样本 ${backtest.sample_count || 0} 次，已做事件去重</small></div><div class="backtest-grid">${backtestRows}</div></section>
  ${errors ? `<p class="timeframe-warning">部分周期降级：${esc(errors)}</p>` : ''}
  <p class="option-warning">${esc(data.warning)}</p>`;
  document.querySelectorAll('.advanced-timeframe-tab').forEach(button => {
    button.onclick = () => { activeTechnicalTimeframe = button.dataset.timeframe; renderAdvancedFrame(); };
  });
  renderAdvancedFrame();
}
