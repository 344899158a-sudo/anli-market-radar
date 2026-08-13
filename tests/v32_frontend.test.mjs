import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "web", "v32_app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web", "v32_index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "v32_styles.css"), "utf8");

test("3.2 uses its versioned dashboard and holdings write contract", () => {
  assert.match(source, /\/api\/v3\.2\/dashboard/);
  assert.match(source, /\/api\/v3\.2\/holdings/);
  assert.match(source, /X-ANLI-Confirm/);
  assert.match(source, /Idempotency-Key/);
  assert.match(source, /automatic_ordering|不会自动下单/);
});

test("3.2 accepts code-only holdings and clearly labels all optional fields", () => {
  assert.match(html, /只填股票代码即可/);
  assert.match(source, /quantity/);
  assert.match(source, /average_cost/);
  assert.match(source, /stop_price/);
  assert.match(source, /Object\.entries\(row\)\.filter/);
});

test("3.2 exposes four-week event relevance and verification boundary", () => {
  assert.match(source, /FOUR-WEEK EVENT GRAPH/);
  assert.match(source, /公司直接 → 产业链 → 行业 → 全市场/);
  assert.match(source, /待核验线索不改变决策状态/);
  assert.match(source, /item\.verified/);
});

test("3.2 renders evidence, invalidation and next condition for reversion research", () => {
  assert.match(source, /r\.evidence/);
  assert.match(source, /r\.invalidation/);
  assert.match(source, /r\.next_condition/);
  assert.match(source, /相对.*行业ETF与QQQ/);
});

test("3.2 preserves every earlier version and has a three-view mobile layout", () => {
  for (const route of ["v1.html", "playbooks.html", "v3.html", "v3.1.html"]) {
    assert.match(html, new RegExp(route.replace(".", "\\.")));
  }
  assert.equal((html.match(/class="mobile-nav"[\s\S]*?<\/nav>/)?.[0].match(/data-view=/g) || []).length, 3);
  assert.match(css, /@media\(max-width:900px\)/);
});

test("3.2 automatically refreshes once a minute", () => {
  assert.match(source, /AUTO_REFRESH = 60_000/);
  assert.match(source, /setInterval/);
  assert.match(source, /document\.hidden/);
});
