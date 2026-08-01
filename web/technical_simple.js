(function () {
  if (typeof window.renderTechnical === "function") return;
  const decisionView = {
    LONG_READY: { tone: "long", icon: "↗", title: "核对后做多", action: "突破已确认，先核对原则与限价" },
    LONG_WATCH: { tone: "watch", icon: "↗", title: "偏多，等突破", action: "未触发前不追涨" },
    SHORT_READY: { tone: "short", icon: "↘", title: "核对后做空", action: "跌破已确认，先核对事件与流动性" },
    SHORT_WATCH: { tone: "watch", icon: "↘", title: "偏空，等跌破", action: "未触发前不提前做空" },
    SELL_REVIEW: { tone: "short", icon: "!", title: "持仓减仓复核", action: "先处理风险，再考虑新机会" },
    WAIT: { tone: "neutral", icon: "—", title: "观望", action: "多周期没有共振，暂不操作" },
  };

  const trendView = {
    UP: { icon: "↗", label: "偏多", tone: "up" },
    DOWN: { icon: "↘", label: "偏空", tone: "down" },
    RANGE: { icon: "→", label: "震荡", tone: "range" },
  };

  const number = (value, digits = 2) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
  };

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

  const price = value => `$${number(value)}`;

  function timeframePill(label, frame) {
    if (!frame?.sufficient) {
      return `<div class="simple-tf unavailable"><span>${label}</span><b>·</b><small>无数据</small></div>`;
    }
    const view = trendView[frame.trend] || trendView.RANGE;
    return `<div class="simple-tf ${view.tone}">
      <span>${label}</span><b>${view.icon}</b><small>${view.label}</small>
    </div>`;
  }

  function levelCards(data) {
    const longPlan = data.plans?.long || {};
    const shortPlan = data.plans?.short || {};
    if (data.bias === "LONG") {
      return [
        ["触发价", price(longPlan.trigger), "站上再确认", "trigger"],
        ["失效价", price(longPlan.stop), "跌破则取消", "stop"],
        ["第一目标", price(longPlan.target1), `盈亏比 ${number(longPlan.risk_reward1, 1)}`, "target"],
      ];
    }
    if (data.bias === "SHORT") {
      return [
        ["触发价", price(shortPlan.trigger), "跌破再确认", "trigger"],
        ["失效价", price(shortPlan.stop), "站上则取消", "stop"],
        ["第一目标", price(shortPlan.target1), `盈亏比 ${number(shortPlan.risk_reward1, 1)}`, "target"],
      ];
    }
    return [
      ["向上确认", price(longPlan.trigger), "突破后再评估做多", "trigger"],
      ["当前价格", price(data.price), "现在不操作", "current"],
      ["向下确认", price(shortPlan.trigger), "跌破后再评估做空", "stop"],
    ];
  }

  function indicatorDetails(data, primaryLabel) {
    const frame = data.timeframes?.[primaryLabel] || {};
    const indicators = frame.indicators || {};
    const rows = [
      ["MA20", price(indicators.ma20)],
      ["MA50", price(indicators.ma50)],
      ["RSI14", number(indicators.rsi14, 1)],
      ["MACD", number(indicators.macd, 3)],
      ["ATR14", price(indicators.atr14)],
      ["波动率", `${number(indicators.atr_pct)}%`],
    ];
    return rows.map(([label, value]) => `<div><span>${label}</span><b>${value}</b></div>`).join("");
  }

  function patternDetails(data) {
    const patterns = (data.patterns || []).slice(0, 4);
    if (!patterns.length) return '<p class="simple-empty">暂无达到阈值的形态。</p>';
    const direction = { BULLISH: "偏多", BEARISH: "偏空", NEUTRAL: "中性" };
    return patterns.map(pattern => `<article class="simple-pattern ${String(pattern.direction).toLowerCase()}">
      <div><b>${escapeHtml(pattern.name)}</b><span>${escapeHtml(pattern.timeframe)} · ${direction[pattern.direction] || "中性"} · ${number(pattern.confidence, 0)}%</span></div>
      <p>${escapeHtml(pattern.explanation)}</p>
      <small>触发 ${price(pattern.trigger)} · 失效 ${price(pattern.invalidation)}</small>
    </article>`).join("");
  }

  window.renderTechnical = function renderTechnicalSimple(data) {
    activeTechnicalData = data;
    const view = decisionView[data.decision] || decisionView.WAIT;
    const order = ["15m", "1h", "4h", "1D", "1W"];
    const primaryLabel = data.timeframes?.["1D"]?.sufficient ? "1D"
      : order.find(label => data.timeframes?.[label]?.sufficient) || "1D";
    const primary = data.timeframes?.[primaryLabel] || {};
    const levels = levelCards(data);
    const topPattern = (data.patterns || [])[0];
    const patternText = topPattern
      ? `${topPattern.timeframe} ${topPattern.name}（${topPattern.status}）`
      : "暂无高置信度形态";
    const readiness = data.data?.execution_ready
      ? { label: "数据可执行", tone: "ready", detail: "官方盘中数据在时效范围内" }
      : { label: "仅做计划", tone: "plan", detail: "非官方盘中5分钟数据，不作为即时信号" };
    const confidence = Math.max(0, Math.min(100, Number(data.confidence) || 0));
    const quoteTime = String(data.data?.quote_time || "").replace("T", " ").slice(0, 16);

    $("technicalSource").textContent =
      `${data.data?.provider || "数据源未知"} · ${data.data?.market_session || "UNKNOWN"} · ${quoteTime || "时间未知"}`;

    $("technicalContent").innerHTML = `
      <section class="simple-tech ${view.tone}">
        <div class="simple-hero">
          <div class="simple-symbol"><span>${escapeHtml(data.symbol)}</span><b>${price(data.price)}</b></div>
          <div class="simple-decision">
            <span class="simple-direction">${view.icon}</span>
            <div><small>技术结论</small><h3>${view.title}</h3><p>${view.action}</p></div>
          </div>
          <div class="simple-confidence" style="--confidence:${confidence}">
            <b>${number(confidence, 0)}%</b><span>一致度</span>
          </div>
        </div>

        <div class="simple-gate ${readiness.tone}">
          <b>${readiness.label}</b><span>${readiness.detail}</span>
        </div>

        <div class="simple-levels">
          ${levels.map(([label, value, hint, tone]) => `<article class="${tone}">
            <span>${label}</span><b>${value}</b><small>${hint}</small>
          </article>`).join("")}
        </div>

        <div class="simple-section-head"><h3>多周期方向</h3><span>一致才行动</span></div>
        <div class="simple-timeframes">
          ${order.map(label => timeframePill(label, data.timeframes?.[label])).join("")}
        </div>

        <div class="simple-why">
          <h3>为什么</h3>
          <ul>
            <li><b>周期：</b>${escapeHtml(data.reasoning?.summary || "暂无")}</li>
            <li><b>形态：</b>${escapeHtml(patternText)}</li>
            <li><b>原则：</b>${escapeHtml(data.reasoning?.principle_gate || "等待原则复核")}</li>
          </ul>
        </div>

        <details class="simple-details">
          <summary><span>展开详细指标与形态</span><small>MA / RSI / MACD / ATR / K线形态</small></summary>
          <div class="simple-detail-grid">
            <section>
              <h4>${primaryLabel} 核心指标</h4>
              <div class="simple-indicators">${indicatorDetails(data, primaryLabel)}</div>
            </section>
            <section>
              <h4>主要形态</h4>
              <div class="simple-patterns">${patternDetails(data)}</div>
            </section>
          </div>
          <div class="simple-raw-summary">
            <b>系统原始判断</b>
            <p>${escapeHtml(data.decision_label)}；共振分 ${data.consensus_score > 0 ? "+" : ""}${number(data.consensus_score, 1)}。</p>
            <small>${escapeHtml(data.warning || "")}</small>
          </div>
        </details>

        <p class="simple-risk-note">技术分析只负责“何时观察和确认”，不能绕过基本面、账户风险和数据时效闸门，也不会自动下单。</p>
      </section>`;
  };
})();
