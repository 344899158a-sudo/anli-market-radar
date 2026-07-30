import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFile(join(root, path), "utf8");

test("公开首页没有大局观下方的小字副标题", async () => {
  const html = await read("public/index.html");
  const header = html.match(/<header class="app-bar">([\s\S]*?)<\/header>/)?.[1] ?? "";

  assert.match(header, /<h1>今天的大局观<\/h1>/);
  assert.doesNotMatch(header, /<p|<small/);
  assert.match(html, /styles\.css\?v=/);
  assert.match(html, /app\.js\?v=/);
});

test("大局观模块进入同数据源的 TrendIQ 详情", async () => {
  const app = await read("public/app.js");

  assert.match(app, /window\.location\.hash === "#trendiq"/);
  assert.match(app, /opportunity\.setAttribute\("role", "link"\)/);
  assert.match(app, /window\.location\.hash = "trendiq"/);
  assert.match(app, /QQQ 日K技术图/);
  assert.match(app, /analysis-grid/);
  assert.match(app, /云端快照偏旧/);
});

test("浏览器与 Pages 构建都有自动更新及发布闸门", async () => {
  const [app, workflow, generator, validator] = await Promise.all([
    read("public/app.js"),
    read(".github/workflows/deploy-pages.yml"),
    read("scripts/generate-dashboard.mjs"),
    read("scripts/validate-dashboard.mjs")
  ]);

  assert.match(app, /cache: "no-store"/);
  assert.match(app, /setInterval\(\(\) => load\(\{ silent: true \}\), 60_000\)/);
  assert.match(app, /visibilitychange/);
  assert.match(workflow, /cron: "7,22,37,52 \* \* \* 1-5"/);
  assert.match(workflow, /npm run refresh[\s\S]*npm run validate/);
  assert.match(workflow, /path: public/);
  assert.match(generator, /join\(root, "public", "data"\)/);
  assert.match(validator, /generatedAt 不是本次生成/);
  assert.match(validator, /market\.bars 少于132根/);
});
