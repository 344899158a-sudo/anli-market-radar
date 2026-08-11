import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "web", "v3_app.js"), "utf8");
const v2Source = fs.readFileSync(path.join(root, "web", "v2_app.js"), "utf8");

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

test("v3 formatters never turn missing market values into zero", () => {
  const { fmt, integer, money, signed, changeClass } = context.formatters;
  for (const value of [null, undefined, ""]) {
    assert.equal(fmt(value), "—");
    assert.equal(integer(value), "—");
    assert.equal(money(value), "—");
    assert.equal(signed(value), "—");
    assert.equal(changeClass(value), "");
  }
});

test("v3 formatters preserve real numeric zero", () => {
  const { fmt, integer, money, signed } = context.formatters;
  assert.equal(fmt(0), "0.0");
  assert.equal(integer(0), "0");
  assert.equal(money(0), "$0.00");
  assert.equal(signed(0), "0.00%");
});

test("v2 and v3 preserved routes check for newer snapshots while visible", () => {
  for (const script of [v2Source, source]) {
    assert.match(script, /AUTO_REFRESH_MS = 60_000/);
    assert.match(script, /document\.visibilityState === "visible"/);
    assert.match(script, /继续显示上一份快照/);
  }
});
