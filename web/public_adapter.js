(function () {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const moduleCache = new Map();
  const MANIFEST_TTL_MS = 25_000;
  let manifestPromise = null;
  let manifestFetchedAt = 0;
  let activeSnapshotId = null;

  const jsonResponse = (payload, status = 200) => new Response(
    JSON.stringify(payload),
    {
      status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
    },
  );

  const errorResponse = (message, status = 404) => jsonResponse(
    { error: message, public_read_only: true },
    status,
  );

  const storageKey = "anli-public-local-holdings";

  function localHoldings() {
    try {
      const values = JSON.parse(localStorage.getItem(storageKey) || "[]");
      return new Set(Array.isArray(values) ? values.map(String) : []);
    } catch (_) {
      return new Set();
    }
  }

  function saveLocalHoldings(values) {
    localStorage.setItem(storageKey, JSON.stringify([...values].sort()));
  }

  async function loadManifest(force = false) {
    const expired = manifestFetchedAt > 0
      && Date.now() - manifestFetchedAt >= MANIFEST_TTL_MS;
    if (force || expired) manifestPromise = null;
    if (!manifestPromise) {
      manifestFetchedAt = Date.now();
      manifestPromise = nativeFetch(
        `./data/manifest.json?t=${Date.now()}`,
        { cache: "no-store" },
      ).then(async response => {
        if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
        const manifest = await response.json();
        if (!manifest?.modules || !manifest.schema_version || !manifest.snapshot_id) {
          throw new Error("公开快照 manifest 结构不完整");
        }
        if (activeSnapshotId && activeSnapshotId !== manifest.snapshot_id) {
          moduleCache.clear();
        }
        activeSnapshotId = manifest.snapshot_id;
        return manifest;
      }).catch(error => {
        manifestPromise = null;
        manifestFetchedAt = 0;
        throw error;
      });
    }
    return manifestPromise;
  }

  async function loadModule(name) {
    const manifest = await loadManifest();
    const cacheKey = `${manifest.snapshot_id}:${name}`;
    if (moduleCache.has(cacheKey)) return moduleCache.get(cacheKey);
    const promise = (async () => {
      const entry = manifest.modules[name];
      if (!entry?.path) throw new Error(`公开快照缺少模块 ${name}`);
      const response = await nativeFetch(
        `./data/${entry.path}?t=${encodeURIComponent(manifest.snapshot_id)}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error(`${name} HTTP ${response.status}`);
      const envelope = await response.json();
      if (!envelope || envelope.data === undefined) {
        throw new Error(`${name} 快照结构不完整`);
      }
      return envelope;
    })();
    moduleCache.set(cacheKey, promise);
    try {
      return await promise;
    } catch (error) {
      moduleCache.delete(cacheKey);
      throw error;
    }
  }

  async function optionalModule(name) {
    try {
      return await loadModule(name);
    } catch (_) {
      return null;
    }
  }

  function sessionLabel(session) {
    return {
      REGULAR: "盘中",
      PREMARKET: "盘前",
      AFTERHOURS: "盘后",
      CLOSED: "休市",
    }[session] || "快照";
  }

  async function publicStatus() {
    const [manifest, overviewEnvelope, watchlistEnvelope] = await Promise.all([
      loadManifest(),
      loadModule("market-overview"),
      optionalModule("watchlist"),
    ]);
    const overview = overviewEnvelope.data || {};
    const watchlist = watchlistEnvelope?.data || {};
    const sectorStatus = watchlist.sector_status || Object.fromEntries(
      (watchlist.sectors || []).map(item => [
        item.name,
        { benchmark: item.benchmark, above_ma50: null },
      ]),
    );
    const ageSeconds = Math.max(
      0,
      Math.floor((Date.now() - Date.parse(manifest.as_of || manifest.generated_at)) / 1000),
    );
    return {
      running: true,
      configured: true,
      public_read_only: true,
      last_error: manifest.quality?.status === "FAILED" ? "公开快照生成失败" : null,
      provider: manifest.source?.provider || overview.provider || "公开行情",
      feed: manifest.source?.feed || "static-snapshot",
      is_official_realtime: false,
      last_refresh: manifest.generated_at,
      market_data_time: manifest.as_of,
      quote_age_seconds: Number.isFinite(ageSeconds) ? ageSeconds : null,
      quote_is_fresh: false,
      market_session: manifest.source?.session || "CLOSED",
      market_session_label: sessionLabel(manifest.source?.session),
      poll_seconds: 60,
      ticker_count: Number(watchlist.symbol_count || 0),
      symbol_count: Number(watchlist.symbol_count || 0),
      sector_status: sectorStatus,
      market_overview: overview,
      sector_pulse: (await optionalModule("sector-pulse"))?.data || null,
      holdings: [...localHoldings()].sort(),
      rule_config_version: manifest.rule_version,
      snapshot_quality: manifest.quality,
    };
  }

  async function publicOpportunities() {
    const [envelope, watchlistEnvelope] = await Promise.all([
      loadModule("opportunities"),
      optionalModule("watchlist"),
    ]);
    const holdings = localHoldings();
    const evidenceSymbols = new Set(
      (watchlistEnvelope?.data?.symbols || [])
        .filter(item => item?.evidence_available)
        .map(item => String(item.symbol || "").toUpperCase()),
    );
    return (envelope.data || []).map(item => {
      const symbol = String(item.symbol || "").toUpperCase();
      const evidenceAvailable = evidenceSymbols.has(symbol);
      const opportunity = { ...(item.opportunity || {}) };
      if (evidenceAvailable) opportunity.ai_fresh = true;
      return {
        ...item,
        opportunity,
        evidence_available: evidenceAvailable,
        ai_analysis: item.ai_analysis || (evidenceAvailable ? {
          verdict: "已生成",
          event_class: "脱敏证据",
          risk_score: null,
          confidence: null,
          summary: "点击查看已脱敏的新闻、SEC与AI复核依据",
        } : null),
        holding: holdings.has(symbol),
      };
    });
  }

  async function publicDecisionSummary() {
    const manifest = await loadManifest();
    return {
      tenant_id: "public-device",
      account_id: "local-only",
      rule_config_version: manifest.rule_version,
      account_risk_state: "仅本机",
      must_act_count: 0,
      must_act: [],
      recent_decisions: [],
      generated_at: manifest.generated_at,
      automatic_ordering: false,
      public_read_only: true,
    };
  }

  function publicEvidence(data) {
    const newsItems = Array.isArray(data?.news) ? data.news : [];
    const secFilings = Array.isArray(data?.sec_filings) ? data.sec_filings : [];
    const sources = [
      ...newsItems.map(item => ({
        publisher: item.publisher || "新闻来源",
        title: item.title || "新闻标题",
        url: item.url,
      })),
      ...secFilings.map(item => ({
        publisher: "SEC",
        title: `${item.form || "申报"} · ${item.description || item.items || "公司披露"}`,
        url: item.url,
      })),
    ].filter(item => /^https:\/\//i.test(String(item.url || "")));
    return {
      ...(data?.analysis || {}),
      symbol: data?.symbol,
      company: data?.company,
      analyzed_at: data?.analyzed_at,
      verification_status: data?.verification_status,
      evidence_quality: data?.evidence_quality || {},
      market_context: data?.market_context || {},
      news_items: newsItems,
      sec_filings: secFilings,
      fundamentals: data?.fundamentals || {},
      limitations: data?.limitations || [],
      sources,
      model: "ANLI 公开脱敏证据快照",
    };
  }

  async function handleGet(url) {
    const path = url.pathname;
    if (path === "/api/status") return jsonResponse(await publicStatus());
    if (path === "/api/v1/dashboard/summary") {
      return jsonResponse(await publicDecisionSummary());
    }
    if (path === "/api/market-overview") {
      return jsonResponse((await loadModule("market-overview")).data);
    }
    if (path === "/api/event-calendar") {
      return jsonResponse((await loadModule("event-calendar")).data);
    }
    if (path === "/api/sector-pulse") {
      return jsonResponse((await loadModule("sector-pulse")).data);
    }
    if (path === "/api/opportunities" || path === "/api/signals") {
      return jsonResponse(await publicOpportunities());
    }
    if (path === "/api/qqq-analysis") {
      return jsonResponse((await loadModule("qqq-analysis")).data);
    }
    if (path === "/api/ai/status") {
      const manifest = await loadManifest();
      const hasEvidence = Object.keys(manifest.modules).some(name => (
        name.startsWith("evidence/")
      ));
      return jsonResponse({
        configured: hasEvidence,
        last_error: null,
        model: "脱敏证据快照",
        scan_seconds: 1800,
        public_read_only: true,
      });
    }
    if (path === "/api/ai/jobs" || path === "/api/alerts") {
      return jsonResponse([]);
    }
    if (path === "/api/technical") {
      const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      if (!symbol) return errorResponse("缺少股票代码", 400);
      const envelope = await optionalModule(`technical/${symbol}`);
      return envelope
        ? jsonResponse(envelope.data)
        : errorResponse(`${symbol} 技术快照尚未生成`, 404);
    }
    if (path === "/api/ai/analysis") {
      const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      if (!symbol) return errorResponse("缺少股票代码", 400);
      const envelope = await optionalModule(`evidence/${symbol}`);
      return envelope
        ? jsonResponse(publicEvidence(envelope.data))
        : errorResponse(`${symbol} 暂无可公开的脱敏证据`, 404);
    }
    if (path === "/api/ai/analyses") {
      const manifest = await loadManifest();
      const names = Object.keys(manifest.modules).filter(name => (
        name.startsWith("evidence/")
      ));
      const envelopes = await Promise.all(names.map(optionalModule));
      return jsonResponse(
        envelopes.filter(Boolean).map(item => publicEvidence(item.data)),
      );
    }
    return errorResponse("公开版没有这个接口", 404);
  }

  async function handlePost(url, options) {
    const path = url.pathname;
    if (path === "/api/holding") {
      let payload;
      try {
        payload = JSON.parse(String(options.body || "{}"));
      } catch (_) {
        return errorResponse("请求格式错误", 400);
      }
      const symbol = String(payload.symbol || "").toUpperCase();
      if (!symbol) return errorResponse("缺少股票代码", 400);
      const holdings = localHoldings();
      if (payload.held) holdings.add(symbol);
      else holdings.delete(symbol);
      saveLocalHoldings(holdings);
      return jsonResponse({ symbol, held: Boolean(payload.held), local_only: true });
    }
    if (path === "/api/refresh") {
      await loadManifest(true);
      return jsonResponse({ accepted: true, public_snapshot: true }, 202);
    }
    if (path === "/api/ai/analyze") {
      return errorResponse(
        "公开版不运行私有AI任务；这里只显示已脱敏并自动更新的证据快照",
        409,
      );
    }
    return errorResponse("公开版为只读快照", 405);
  }

  window.ANLI_PUBLIC_MODE = true;
  window.fetch = async function publicSnapshotFetch(input, options = {}) {
    const raw = typeof input === "string" ? input : input.url;
    const url = new URL(raw, window.location.href);
    if (!url.pathname.startsWith("/api/")) {
      return nativeFetch(input, options);
    }
    try {
      const method = String(options.method || "GET").toUpperCase();
      return method === "GET"
        ? await handleGet(url)
        : await handlePost(url, options);
    } catch (error) {
      return errorResponse(
        `公开快照读取失败：${error instanceof Error ? error.message : "未知错误"}`,
        503,
      );
    }
  };
})();
