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
  let generatedAt = "2026-07-31T14:02:00+00:00";
  let overviewAsOf = "2026-07-31T14:00:00+00:00";
  let sourceSession = "REGULAR";
  const storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
  };

  const manifest = snapshotId => ({
    schema_version: "1.0.0",
    snapshot_id: snapshotId,
    rule_version: "1.0.0",
    generated_at: generatedAt,
    as_of: overviewAsOf,
    source: { provider: `provider-${snapshotId}`, session: sourceSession },
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
      return new Response(JSON.stringify({
        ...envelope({ provider: `overview-${version}` }),
        as_of: overviewAsOf,
      }));
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
    if (url.pathname.endsWith("/data/dashboard-v3.json")) {
      return new Response(JSON.stringify({
        schema_version: "3.0.0",
        meta: { snapshot_id: version, public_read_only: true },
        symbols: [{ symbol: "NVDA" }],
      }));
    }
    if (url.pathname.endsWith("/data/dashboard-v31.json")) {
      return new Response(JSON.stringify({
        schema_version: "3.1.0",
        meta: { snapshot_id: version, public_read_only: true },
        portfolio_risk: { state: "DATA_GAP", public_redacted: true },
        symbols: [{ symbol: "NVDA" }],
      }));
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

    const v3 = await (await window.fetch("/api/v3/dashboard")).json();
    assert.equal(v3.schema_version, "3.0.0");
    assert.equal(v3.meta.public_read_only, true);

    const v31 = await (await window.fetch("/api/v3.1/dashboard")).json();
    assert.equal(v31.schema_version, "3.1.0");
    assert.equal(v31.portfolio_risk.public_redacted, true);

    const rejected = await window.fetch("/api/v3.1/portfolio", {
      method: "POST",
      body: JSON.stringify({ account: { equity: 100000 } }),
    });
    assert.equal(rejected.status, 405);
    assert.match((await rejected.json()).error, /公开版不接收/);

    clock = Date.parse("2026-08-04T14:00:00Z");
    generatedAt = "2026-08-04T13:58:00Z";
    overviewAsOf = "2026-08-04T13:58:00Z";
    sourceSession = "PREMARKET";
    version = "three";
    const changedRefresh = await (
      await window.fetch("/api/refresh", { method: "POST" })
    ).json();
    assert.equal(changedRefresh.refreshed, true);
    const staleAtOpen = await (await window.fetch("/api/status")).json();
    assert.equal(staleAtOpen.market_session, "REGULAR");
    assert.equal(staleAtOpen.snapshot_session, "PREMARKET");
    assert.equal(staleAtOpen.market_data_stale, true);
    assert.equal(staleAtOpen.quote_is_fresh, false);
    assert.match(staleAtOpen.last_error, /\u5df2\u5f00\u76d8/);

    sourceSession = "REGULAR";
    version = "four";
    const freshRefresh = await (
      await window.fetch("/api/refresh", { method: "POST" })
    ).json();
    assert.equal(freshRefresh.refreshed, true);
    const freshRegular = await (await window.fetch("/api/status")).json();
    assert.equal(freshRegular.market_data_stale, false);
    assert.equal(freshRegular.quote_is_fresh, true);
    assert.equal(freshRegular.quote_age_seconds, 120);

    const unchangedRefresh = await (
      await window.fetch("/api/refresh", { method: "POST" })
    ).json();
    assert.equal(unchangedRefresh.refreshed, false);
    assert.equal(unchangedRefresh.accepted, false);
  } finally {
    Date.now = originalNow;
    delete globalThis.window;
    delete globalThis.localStorage;
  }
});
