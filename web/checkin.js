const CHECKLIST = [
  ["市场环境允许", "大盘与板块没有明确风险否决"],
  ["不追涨、不冲动", "价格过热时宁可错过"],
  ["只看预设清单", "不临时追逐陌生股票"],
  ["入场与退出写清", "先知道什么情况证明判断错误"],
  ["仓位符合上限", "单仓不超过计划上限，不孤注一掷"],
  ["信息已完成复核", "新闻、财报与基本面没有明显恶化"],
];

const STORAGE_KEY = "anli-mobile-checkins-v1";
const DRAFT_KEY = "anli-mobile-checkin-draft-v1";
const todayKey = new Date().toLocaleDateString("sv-SE");

const state = {
  checks: Array(CHECKLIST.length).fill(false),
  action: "",
};

const $ = (selector) => document.querySelector(selector);
const list = $("#disciplineList");
const actionButtons = [...document.querySelectorAll(".action-button")];
const fields = ["symbolInput", "directionInput", "riskInput", "noteInput"];

function localDateLabel() {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}

function renderChecklist() {
  list.innerHTML = CHECKLIST.map(([title, detail], index) => `
    <button class="discipline-item ${state.checks[index] ? "checked" : ""}" type="button" data-index="${index}" aria-pressed="${state.checks[index]}">
      <span class="check">✓</span>
      <span><strong>${title}</strong><small>${detail}</small></span>
      <span class="state">${state.checks[index] ? "已确认" : "待确认"}</span>
    </button>
  `).join("");
  updateScore();
}

function updateScore() {
  const count = state.checks.filter(Boolean).length;
  const pct = Math.round((count / CHECKLIST.length) * 100);
  $("#scoreValue").textContent = count;
  $("#scoreRing").style.setProperty("--progress", `${pct}%`);
  const pill = $("#statusPill");

  if (count === CHECKLIST.length) {
    pill.className = "status-pill ready";
    pill.textContent = "纪律已通过";
    $("#statusTitle").textContent = "可以继续评估机会";
    $("#statusHint").textContent = "通过纪律不等于必须交易，仍需等待价格和触发条件。";
  } else if (count >= 4) {
    pill.className = "status-pill waiting";
    pill.textContent = `还差 ${CHECKLIST.length - count} 项`;
    $("#statusTitle").textContent = "暂缓出手";
    $("#statusHint").textContent = "把未确认项处理完，再决定是否交易。";
  } else {
    pill.className = "status-pill blocked";
    pill.textContent = "不满足出手条件";
    $("#statusTitle").textContent = "今天优先保护本金";
    $("#statusHint").textContent = "条件不足时，观望本身就是一次正确执行。";
  }
}

function readDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
    if (draft.date !== todayKey) return;
    state.checks = Array.isArray(draft.checks) ? draft.checks.slice(0, CHECKLIST.length) : state.checks;
    while (state.checks.length < CHECKLIST.length) state.checks.push(false);
    state.action = draft.action || "";
    fields.forEach((id) => {
      if (draft[id] != null) document.getElementById(id).value = draft[id];
    });
  } catch {
    localStorage.removeItem(DRAFT_KEY);
  }
}

function saveDraft() {
  const draft = { date: todayKey, checks: state.checks, action: state.action };
  fields.forEach((id) => { draft[id] = document.getElementById(id).value.trim(); });
  localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

function history() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
  catch { return []; }
}

function renderHistory() {
  const records = history().slice(0, 10);
  $("#historyList").innerHTML = records.length ? records.map((item) => `
    <article class="history-item">
      <header><strong>${item.action || "未选择行动"} · ${item.score}/6</strong><time>${item.date} ${item.time}</time></header>
      <p>${[item.symbol, item.direction, item.risk].filter(Boolean).join(" · ") || "无交易记录"}${item.note ? `<br>${escapeHtml(item.note)}` : ""}</p>
    </article>
  `).join("") : '<p class="history-empty">还没有打卡记录</p>';
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 1800);
}

list.addEventListener("click", (event) => {
  const button = event.target.closest(".discipline-item");
  if (!button) return;
  const index = Number(button.dataset.index);
  state.checks[index] = !state.checks[index];
  renderChecklist();
  saveDraft();
});

actionButtons.forEach((button) => button.addEventListener("click", () => {
  state.action = button.dataset.action;
  actionButtons.forEach((item) => item.classList.toggle("selected", item === button));
  saveDraft();
}));

fields.forEach((id) => document.getElementById(id).addEventListener("input", saveDraft));

$("#symbolInput").addEventListener("input", (event) => {
  event.target.value = event.target.value.toUpperCase().replace(/[^A-Z.-]/g, "");
});

$("#resetToday").addEventListener("click", () => {
  state.checks.fill(false);
  state.action = "";
  fields.forEach((id) => { document.getElementById(id).value = ""; });
  actionButtons.forEach((item) => item.classList.remove("selected"));
  localStorage.removeItem(DRAFT_KEY);
  renderChecklist();
  showToast("今天的内容已重置");
});

$("#saveButton").addEventListener("click", () => {
  if (!state.action) {
    showToast("请先选择今天的行动");
    return;
  }
  const now = new Date();
  const record = {
    id: now.toISOString(),
    date: todayKey,
    time: now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    score: state.checks.filter(Boolean).length,
    action: state.action,
    symbol: $("#symbolInput").value.trim(),
    direction: $("#directionInput").value,
    risk: $("#riskInput").value.trim(),
    note: $("#noteInput").value.trim(),
  };
  const records = history().filter((item) => item.date !== todayKey);
  records.unshift(record);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records.slice(0, 60)));
  renderHistory();
  showToast("今日打卡已保存");
});

$("#clearHistory").addEventListener("click", () => {
  if (!confirm("确定清空这台设备上的全部打卡记录吗？")) return;
  localStorage.removeItem(STORAGE_KEY);
  renderHistory();
  showToast("历史记录已清空");
});

$("#todayLabel").textContent = localDateLabel();
readDraft();
renderChecklist();
actionButtons.forEach((button) => button.classList.toggle("selected", button.dataset.action === state.action));
renderHistory();
