import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";


test("public adapter refreshes manifests and exposes evidence entry points", async () => {
  const originalNow = Date.now;
  let clock = 1_000_000;
  Date.now = () => clock;
  let version = "one";
  let manifestRequests = 0;
  const storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
  };

  const manifest = snapshotId => ({
    schema_version: "1.0.0",
    snapshot_id: snapshotId,
    rule_version: "1.0.0",
    generated_at: "2026-07-31T14:02:00+00:00",
    as_of: "2026-07-31T14:00:00+00:00",
    source: { provider: `provider-${snapshotId}`, session: "REGULAR" },
    quality: { status: "OK", missing: [], errors: [] },
    modules: {
      "market-overview": { path: `snapshots/${snapshotId}/market-overview.json` },
      watchlist: { path: `snapshots/${snapshotId}/watchlist.json` },
      opportunities: { path: `snapshots/${snapshotId}/opportunities.json` },
      "sector-pulse": { path: `snapshots/${snapshotId}/sector-pulse.json` },
      "evidence/NVDA": { path: `snapshots/${snapshotId}/evidence/NVDA.json` },
    },
  });

  const envelope = data => ({ data });
  const nativeFetch = async input => {
    const url = new URL(String(input), "https://example.test/radar/index.html");
    if (url.pathname.endsWith("/data/manifest.json")) {
      manifestRequests += 1;
      return new Response(JSON.stringify(manifest(version)));
    }
    if (url.pathname.endsWith("/market-overview.json")) {
      return new Response(JSON.stringify(envelope({ provider: `overview-${version}` })));
    }
    if (url.pathname.endsWith("/watchlist.json")) {
      return new Response(JSON.stringify(envelope({
        symbol_count: 1,
        sector_status: { "US Mega Cap": { benchmark: "QQQ", above_ma50: true } },
        symbols: [{ symbol: "NVDA", evidence_available: true }],
      })));
    }
    if (url.pathname.endsWith("/opportunities.json")) {
      return new Response(JSON.stringify(envelope([{
        symbol: "NVDA",
        opportunity: { ai_fresh: false },
      }])));
    }
    if (url.pathname.endsWith("/sector-pulse.json")) {
      return new Response(JSON.stringify(envelope({ state: `state-${version}` })));
    }
    if (url.pathname.endsWith("/evidence/NVDA.json")) {
      return new Response(JSON.stringify(envelope({
        symbol: "NVDA",
        analyzed_at: "2026-07-31T13:30:00+00:00",
        verification_status: "AI_UNVERIFIED",
        analysis: { summary: "public summary", risk_score: 20, confidence: 80 },
        evidence_quality: { grade: "PARTIAL" },
        market_context: { price: 160 },
        news: [{ title: "headline", publisher: "source", url: "https://news.example/item" }],
        sec_filings: [{ form: "8-K", url: "https://www.sec.gov/item" }],
        fundamentals: { metrics: {} },
      })));
    }
    return new Response("not found", { status: 404 });
  };

  globalThis.window = {
    fetch: nativeFetch,
    location: { href: "https://example.test/radar/index.html" },
  };
  const source = fs.readFileSync(
    new URL("../web/public_adapter.js", import.meta.url),
    "utf8",
  );
  vm.runInThisContext(source, { filename: "public_adapter.js" });

  try {
    const first = await (await window.fetch("/api/status")).json();
    assert.equal(first.provider, "provider-one");
    assert.equal(first.sector_status["US Mega Cap"].above_ma50, true);
    assert.equal(manifestRequests, 1);

    version = "two";
    clock += 26_000;
    const second = await (await window.fetch("/api/status")).json();
    assert.equal(second.provider, "provider-two");
    assert.equal(second.market_overview.provider, "overview-two");
    assert.equal(manifestRequests, 2);

    const opportunities = await (
      await window.fetch("/api/opportunities")
    ).json();
    assert.equal(opportunities[0].evidence_available, true);
    assert.equal(opportunities[0].opportunity.ai_fresh, true);
    assert.equal(opportunities[0].ai_analysis.event_class, "脱敏证据");

    const evidence = await (
      await window.fetch("/api/ai/analysis?symbol=NVDA")
    ).json();
    assert.equal(evidence.summary, "public summary");
    assert.equal(evidence.risk_score, 20);
    assert.equal(evidence.news_items.length, 1);
    assert.equal(evidence.sources.length, 2);
    assert.equal(evidence.analysis, undefined);
  } finally {
    Date.now = originalNow;
    delete globalThis.window;
    delete globalThis.localStorage;
  }
});
