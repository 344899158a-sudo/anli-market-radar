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
  const v32StorageKey = "anli-public-v32-holdings";

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

  function localV32Positions() {
    try {
      const values = JSON.parse(localStorage.getItem(v32StorageKey) || "[]");
      return Array.isArray(values) ? values.filter(item => item && item.symbol) : [];
    } catch (_) {
      return [];
    }
  }

  function saveLocalV32Positions(values) {
    localStorage.setItem(v32StorageKey, JSON.stringify(values));
  }

  const publicThemes = {
    "光模块": {symbols:["LITE","COHR","MRVL","AVGO","ANET"],aliases:["光通信","AI数据中心","电光互联"]},
    "AI数据中心": {symbols:["NVDA","AMD","MRVL","AVGO","ANET","MSFT","AMZN","META"],aliases:["AI云","云资本开支","加速计算"]},
    "存储": {symbols:["MU","SNDK","WDC","STX","DELL"],aliases:["HBM","NAND","DRAM"]},
    "半导体设备": {symbols:["AMAT","LRCX","KLAC","ASML","FORM"],aliases:["晶圆设备","先进封装","测试设备"]},
  };

  function publicHoldingEvents(position, calendar) {
    const symbol = String(position.symbol || "").toUpperCase();
    const sector = String(position.sector || "未分类");
    const themes = new Set();
    Object.entries(publicThemes).forEach(([name, profile]) => {
      if (profile.symbols.includes(symbol)) {
        themes.add(name);
        profile.aliases.forEach(alias => themes.add(alias));
      }
    });
    const verified = calendar?.verification_status === "已核验";
    const rows = [];
    (calendar?.weeks || []).slice(0, 4).forEach(week => {
      (week.events || []).forEach(raw => {
        const scopes = new Set((raw.scope || []).map(String));
        const theme = [...themes].filter(item => scopes.has(item));
        let relevance = null, relevanceLabel = null, matched = [];
        if (scopes.has(symbol)) [relevance,relevanceLabel,matched] = ["DIRECT","公司直接事件",[symbol]];
        else if (theme.length) [relevance,relevanceLabel,matched] = ["SUPPLY_CHAIN","产业链关联",theme];
        else if (scopes.has(sector)) [relevance,relevanceLabel,matched] = ["SECTOR","行业关联",[sector]];
        else if (scopes.has("全市场") || scopes.has("QQQ")) [relevance,relevanceLabel,matched] = ["GLOBAL","全市场事件",["全市场"]];
        if (!relevance) return;
        rows.push({...raw, verified:verified && !String(raw.verification || "").includes("暂定"),
          week:{index:week.index,label:week.label,start:week.start,end:week.end}, relevance,
          relevance_label:relevanceLabel, matched, why_relevant:`${relevanceLabel}：${matched.join("、")}`});
      });
    });
    const priority = {DIRECT:0,SUPPLY_CHAIN:1,SECTOR:2,GLOBAL:3};
    return rows.sort((a,b) => (priority[a.relevance]-priority[b.relevance]) || String(a.at || "").localeCompare(String(b.at || "")));
  }

  async function publicV32Dashboard() {
    const base = await loadOverlay("dashboard-v31", "3.1.0");
    const positions = localV32Positions();
    const symbols = new Map((base.symbols || []).map(row => [String(row.symbol || "").toUpperCase(), row]));
    const privatePositions = positions.map(raw => {
      const market = symbols.get(String(raw.symbol || "").toUpperCase()) || {};
      return {...raw, symbol:String(raw.symbol || "").toUpperCase(), name:market.name || raw.symbol,
        sector:raw.sector || market.sector || "未分类", sector_benchmark:market.sector_benchmark || "QQQ",
        price:market.price, quote_time:market.quote_time, source:"公开脱敏快照", data_state:market.symbol?"READY":"DATA_GAP"};
    });
    const calendar = base.events || {};
    const bySymbol = Object.fromEntries(privatePositions.map(row => [row.symbol, publicHoldingEvents(row, calendar)]));
    const cards = privatePositions.map(row => ({...row,events:bySymbol[row.symbol] || [],mean_reversion:{
      version:"1.0.0",state:"DATA_GAP",label:"公开基准历史不足",execution_ready:false,research_only:true,
      sector_benchmark:row.sector_benchmark,metrics:{},nearest_event:(bySymbol[row.symbol] || []).find(item => item.verified) || null,
      evidence:["公开站不上传私人持仓，也不发布足以重建私人组合的联合基准历史。"],
      invalidation:"数据不足时不生成均值回归结论。",next_condition:"在本机ANLI 3.2使用完整历史重算。",automatic_ordering:false,
    }}));
    const snapshotId = base.meta?.snapshot_id || "public-snapshot";
    return {...base,schema_version:"3.2.0",system_version:"ANLI 3.2",rule_version:"3.2.0",
      meta:{...base.meta,public_read_only:true,automatic_ordering:false,research_only:true},
      private_holdings:{state:privatePositions.length?"ACTIVE":"EMPTY",count:privatePositions.length,positions:privatePositions,
        profile:{snapshot_id:`browser-${snapshotId}`,created_at:base.meta?.as_of},local_only:true,automatic_ordering:false},
      holding_event_graph:{version:"2.0.0",state:privatePositions.length?(calendar.verification_status==="已核验"?"ACTIVE":"UNVERIFIED"):"NO_SELECTION",
        verification_status:calendar.verification_status,verified_at:calendar.verified_at,weeks:(calendar.weeks || []).slice(0,4),leads:[],by_symbol:bySymbol,
        decision_eligible:false,automatic_ordering:false,lead_errors:[]},holding_cards:cards};
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

  async function loadOverlay(name, expectedSchema) {
    const manifest = await loadManifest();
    const cacheKey = `${manifest.snapshot_id}:overlay:${name}`;
    if (moduleCache.has(cacheKey)) return moduleCache.get(cacheKey);
    const promise = (async () => {
      const response = await nativeFetch(
        `./data/${name}.json?t=${encodeURIComponent(manifest.snapshot_id)}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error(`${name} HTTP ${response.status}`);
      const payload = await response.json();
      if (payload?.schema_version !== expectedSchema) {
        throw new Error(`${name} 版本不匹配`);
      }
      if (payload?.meta?.snapshot_id !== manifest.snapshot_id) {
        throw new Error(`${name} 与公开快照不一致`);
      }
      return payload;
    })();
    moduleCache.set(cacheKey, promise);
    try {
      return await promise;
    } catch (error) {
      moduleCache.delete(cacheKey);
      throw error;
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

  function currentNewYorkSession(nowMs = Date.now()) {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date(nowMs)).map(part => [part.type, part.value]),
    );
    if (["Sat", "Sun"].includes(parts.weekday)) return "CLOSED";
    const minuteOfDay = Number(parts.hour) * 60 + Number(parts.minute);
    if (minuteOfDay >= 9 * 60 + 30 && minuteOfDay < 16 * 60) return "REGULAR";
    if (minuteOfDay >= 4 * 60 && minuteOfDay < 9 * 60 + 30) return "PREMARKET";
    if (minuteOfDay >= 16 * 60 && minuteOfDay < 20 * 60) return "AFTERHOURS";
    return "CLOSED";
  }

  function snapshotFreshness(manifest, overviewEnvelope) {
    const snapshotSession = manifest.source?.session || "CLOSED";
    const expectedSession = currentNewYorkSession();
    const marketDataTime = overviewEnvelope?.as_of
      || overviewEnvelope?.data?.as_of
      || manifest.generated_at;
    const timestamp = Date.parse(marketDataTime);
    const ageSeconds = Number.isFinite(timestamp)
      ? Math.max(0, Math.floor((Date.now() - timestamp) / 1000))
      : null;
    const maxAgeSeconds = {
      REGULAR: 30 * 60,
      PREMARKET: 60 * 60,
      AFTERHOURS: 60 * 60,
      CLOSED: 96 * 60 * 60,
    }[expectedSession];
    const sessionMismatch = expectedSession === "REGULAR" && snapshotSession !== "REGULAR";
    const tooOld = ageSeconds == null || ageSeconds > maxAgeSeconds;
    const stale = sessionMismatch || tooOld;
    let staleReason = null;
    if (sessionMismatch) {
      staleReason = `\u7f8e\u80a1\u5df2\u5f00\u76d8\uff0c\u4f46\u4e91\u7aef\u4ecd\u662f${sessionLabel(snapshotSession)}\u5feb\u7167`;
    } else if (tooOld) {
      staleReason = ageSeconds == null
        ? "\u4e91\u7aef\u884c\u60c5\u65f6\u95f4\u672a\u77e5"
        : `\u4e91\u7aef\u884c\u60c5\u5df2${Math.ceil(ageSeconds / 60)}\u5206\u949f\u672a\u66f4\u65b0`;
    }
    return { ageSeconds, expectedSession, marketDataTime, snapshotSession, stale, staleReason };
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
    const freshness = snapshotFreshness(manifest, overviewEnvelope);
    const qualityFailed = manifest.quality?.status === "FAILED";
    const lastError = qualityFailed
      ? "\u516c\u5f00\u5feb\u7167\u751f\u6210\u5931\u8d25\uff0c\u5df2\u6682\u505c\u884c\u60c5\u7ed3\u8bba"
      : freshness.stale
        ? `${freshness.staleReason}\uff0c\u5df2\u6682\u505c\u76d8\u4e2d\u7ed3\u8bba`
        : null;
    return {
      running: true,
      configured: true,
      public_read_only: true,
      last_error: lastError,
      provider: manifest.source?.provider || overview.provider || "公开行情",
      feed: manifest.source?.feed || "static-snapshot",
      is_official_realtime: false,
      last_refresh: manifest.generated_at,
      market_data_time: freshness.marketDataTime,
      quote_age_seconds: freshness.ageSeconds,
      quote_is_fresh: !qualityFailed && !freshness.stale && freshness.expectedSession === "REGULAR",
      market_data_stale: qualityFailed || freshness.stale,
      stale_reason: freshness.staleReason,
      market_session: freshness.expectedSession,
      market_session_label: freshness.stale
        ? `${sessionLabel(freshness.expectedSession)}\u00b7\u5feb\u7167\u8fc7\u671f`
        : sessionLabel(freshness.expectedSession),
      snapshot_session: freshness.snapshotSession,
      snapshot_id: manifest.snapshot_id,
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
    if (path === "/api/v3.2/dashboard") {
      return jsonResponse(await publicV32Dashboard());
    }
    if (path === "/api/v3.2/holdings") {
      return jsonResponse((await publicV32Dashboard()).private_holdings);
    }
    if (path === "/api/v3/dashboard") {
      return jsonResponse(await loadOverlay("dashboard-v3", "3.0.0"));
    }
    if (path === "/api/v3.1/dashboard") {
      return jsonResponse(await loadOverlay("dashboard-v31", "3.1.0"));
    }
    if (path === "/api/v3.1/portfolio") {
      const dashboard = await loadOverlay("dashboard-v31", "3.1.0");
      return jsonResponse(dashboard.portfolio_risk || {});
    }
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
    if (path === "/api/v3.2/holdings") {
      let payload;
      try { payload = JSON.parse(String(options.body || "{}")); }
      catch (_) { return errorResponse("请求格式错误", 400); }
      if (!Array.isArray(payload.positions)) return errorResponse("必须提供持仓列表", 400);
      if (payload.positions.length > 30) return errorResponse("最多跟踪30只持仓", 400);
      const base = await loadOverlay("dashboard-v31", "3.1.0");
      const allowed = new Set((base.symbols || []).map(row => String(row.symbol || "").toUpperCase()));
      const seen = new Set(), normalized = [];
      for (const raw of payload.positions) {
        const symbol = String(raw?.symbol || "").trim().toUpperCase();
        if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol)) return errorResponse(`股票代码格式无效：${symbol || "空"}`, 400);
        if (!allowed.has(symbol)) return errorResponse(`${symbol}不在当前公开股票池；可在本机3.2验证任意美股代码`, 400);
        if (seen.has(symbol)) return errorResponse(`股票代码重复：${symbol}`, 400);
        seen.add(symbol);
        const row = {symbol};
        for (const field of ["sector","quantity","average_cost","stop_price"]) if (raw[field] !== undefined && raw[field] !== "") row[field] = String(raw[field]);
        normalized.push(row);
      }
      saveLocalV32Positions(normalized.sort((a,b) => a.symbol.localeCompare(b.symbol)));
      return jsonResponse({snapshot_id:`browser-holdings-${Date.now()}`,created_at:new Date().toISOString(),
        payload:{positions:normalized},local_only:true,automatic_ordering:false}, 201);
    }
    if (path === "/api/v3.1/portfolio") {
      return errorResponse(
        "公开版不接收账户或持仓资料；请在本机3.1中录入",
        405,
      );
    }
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
      const before = activeSnapshotId || (await loadManifest()).snapshot_id;
      const manifest = await loadManifest(true);
      const refreshed = manifest.snapshot_id !== before;
      return jsonResponse({ accepted: false, public_snapshot: true, refreshed,
        snapshot_id: manifest.snapshot_id,
        message: refreshed ? "\u5df2\u52a0\u8f7d\u4e91\u7aef\u6700\u65b0\u5feb\u7167" : "\u4e91\u7aef\u6682\u65f6\u6ca1\u6709\u66f4\u65b0\uff1b\u7cfb\u7edf\u4f1a\u7ee7\u7eed\u81ea\u52a8\u68c0\u67e5",
      });
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
