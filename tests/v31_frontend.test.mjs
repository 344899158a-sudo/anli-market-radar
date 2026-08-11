import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "web", "v31_app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web", "v31_index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "v31_styles.css"), "utf8");

function extract(name) {
  const match = source.match(new RegExp(`  function ${name}\\([\\s\\S]*?\\n  \\}`));
  assert.ok(match, `missing formatter ${name}`);
  return match[0].trim();
}

const context = {};
vm.createContext(context);
vm.runInContext(
  `${extract("fmt")}\n${extract("integer")}\n${extract("money")}\n${extract("signed")}\n${extract("changeClass")}\nthis.formatters={fmt,integer,money,signed,changeClass};`,
  context,
);

test("v3.1 formatters never turn missing market or risk values into zero", () => {
  const { fmt, integer, money, signed, changeClass } = context.formatters;
  for (const value of [null, undefined, ""]) {
    assert.equal(fmt(value), "—");
    assert.equal(integer(value), "—");
    assert.equal(money(value), "—");
    assert.equal(signed(value), "—");
    assert.equal(changeClass(value), "");
  }
});

test("v3.1 calls the new contract and keeps the 3.0 route visible", () => {
  assert.match(source, /\/api\/v3\.1\/dashboard/);
  assert.match(source, /schema_version !== "3\.1\.0"/);
  assert.match(html, /ANLI 3\.1/);
  assert.match(html, /href="\.\/v3\.html"/);
});

test("v3.1 public mode hides portfolio entry and blocks writes", () => {
  assert.match(source, /window\.ANLI_PUBLIC_MODE/);
  assert.match(source, /公开版不接收账户或持仓资料/);
  assert.match(source, /公开只读版/);
});

test("v3.1 labels heuristic scores without presenting them as probability", () => {
  assert.match(source, /趋势环境强度/);
  assert.match(source, /不等于适合交易概率/);
  assert.match(source, /不会把短期结果称为胜率/);
});

test("v3.1 mobile navigation exposes all five views without changing the desktop contract", () => {
  assert.equal((html.match(/class="mobile-nav"[\s\S]*?<\/nav>/)?.[0].match(/data-view=/g) || []).length, 5);
  assert.match(css, /@media \(max-width: 840px\)/);
  assert.match(css, /\.mobile-nav \{[^}]*grid-template-columns:repeat\(5,1fr\)/);
  assert.match(css, /\.portfolio-position-input \{ grid-template-columns:1fr; \}/);
});
