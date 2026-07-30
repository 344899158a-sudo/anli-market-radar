import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dashboardPath = join(root, "public", "data", "dashboard.json");
const payload = JSON.parse(await readFile(dashboardPath, "utf8"));
const failures = [];
const generatedAt = Date.parse(payload.generatedAt);
const ageMs = Date.now() - generatedAt;

if (!Number.isFinite(generatedAt)) {
  failures.push("generatedAt 无法解析");
} else if (ageMs < -5 * 60_000 || ageMs > 10 * 60_000) {
  failures.push(`generatedAt 不是本次生成（年龄 ${Math.round(ageMs / 60_000)} 分钟）`);
}

if (!Number.isFinite(payload.market?.price)) {
  failures.push("market.price 不是有效数字");
}
if (!Array.isArray(payload.market?.bars) || payload.market.bars.length < 132) {
  failures.push("market.bars 少于132根");
}
if ((payload.market?.dataQuality?.historyRows ?? 0) < 200) {
  failures.push("历史日K少于200根");
}
if (!Array.isArray(payload.market?.dataQuality?.missing)) {
  failures.push("dataQuality.missing 缺失");
} else if (payload.market.dataQuality.missing.length > 0) {
  failures.push(`数据缺口：${payload.market.dataQuality.missing.join("、")}`);
}
if (!payload.market?.provider || typeof payload.market.delayed !== "boolean") {
  failures.push("行情来源或延时标记缺失");
}
if (!payload.decision?.ruleVersion || !Array.isArray(payload.calendar?.weeks)) {
  failures.push("决策或四周事件结构不完整");
}

if (failures.length) {
  throw new Error(`拒绝部署公开快照：${failures.join("；")}`);
}

console.log(
  [
    "公开快照发布闸门通过",
    `generatedAt=${payload.generatedAt}`,
    `quote=${payload.market.quoteLabel}`,
    `price=${payload.market.price}`,
    `bars=${payload.market.bars.length}`
  ].join(" | ")
);
