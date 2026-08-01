(function () {
  const actionLabels = {
    EXIT: "必须退出",
    REDUCE: "必须减仓",
    FREEZE: "账户冻结",
    BLOCKED: "禁止执行",
    WATCH: "继续观察",
    READY: "准备计划",
    PROBE: "允许试探",
    STANDARD: "允许标准仓",
    ADD: "允许加仓",
  };

  const actionClass = action => (
    action === "EXIT" ? "critical" :
    action === "REDUCE" || action === "FREEZE" ? "urgent" :
    action === "BLOCKED" ? "blocked" :
    action === "PROBE" || action === "STANDARD" || action === "READY" ? "ready" :
    "watch"
  );

  const safe = value => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  function renderDecisionSummary(data) {
    document.getElementById("decisionRiskState").textContent = data.account_risk_state || "UNKNOWN";
    document.getElementById("decisionMustAct").textContent = String(data.must_act_count || 0);
    document.getElementById("decisionRuleVersion").textContent = data.rule_config_version || "—";
    document.getElementById("decisionAsOf").textContent =
      `冻结快照 · ${new Date(data.generated_at).toLocaleString("zh-CN")} · 不连接券商下单`;

    const rows = data.must_act?.length ? data.must_act : data.recent_decisions || [];
    const root = document.getElementById("decisionActions");
    if (!rows.length) {
      root.innerHTML = `
        <div class="decision-empty">
          <strong>尚无交易计划评估</strong>
          <p>先创建计划并补齐逻辑失效条件、正股失效位、最晚验证日和风险数据。缺失字段时系统会保守阻断。</p>
        </div>`;
      return;
    }
    root.innerHTML = rows.slice(0, 8).map(item => {
      const blockers = (item.rule_results || [])
        .filter(rule => ["BLOCK", "UNKNOWN", "TRIGGERED"].includes(rule.status))
        .slice(0, 3);
      return `
        <article class="decision-action-card ${actionClass(item.action)}">
          <div>
            <span>${safe(actionLabels[item.action] || item.action)}</span>
            <b>${safe(item.market_regime)} · ${safe(item.account_risk_state)}</b>
          </div>
          <strong>评分 ${Number(item.score || 0)} · 上限 ${Number(item.max_contracts || 0)} 张</strong>
          <ul>${blockers.map(rule => `<li><code>${safe(rule.rule_id)}</code>${safe(rule.message)}</li>`).join("") || "<li>硬性规则全部通过</li>"}</ul>
          <small>规则 ${safe(item.rule_config_version)} · 决策 ${safe(item.id).slice(0, 18)}…</small>
        </article>`;
    }).join("");
  }

  async function loadDecisionSummary() {
    try {
      const response = await fetch("/api/v1/dashboard/summary", {cache: "no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderDecisionSummary(await response.json());
    } catch (error) {
      document.getElementById("decisionActions").innerHTML =
        `<p class="empty negative">纪律决策中心暂不可用：${safe(error.message)}</p>`;
    }
  }

  window.loadDecisionSummary = loadDecisionSummary;
  loadDecisionSummary();
  setInterval(loadDecisionSummary, 30000);
})();

