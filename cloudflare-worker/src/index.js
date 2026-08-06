const CONTRACT_VERSION = "anli-public-v1";
export const MARKET_REFRESH_CRON = "3,18,33,48 * * * MON-FRI";
export const WEEKEND_CALENDAR_CRON = "37 0 * * SAT,SUN";
const ALLOWED_ORIGINS = new Set([
  "https://344899158a-sudo.github.io",
  "http://127.0.0.1:8775",
  "http://localhost:8775",
]);

export function newYorkSession(now = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now).map(part => [part.type, part.value]),
  );
  if (["Sat", "Sun"].includes(parts.weekday)) return "CLOSED";
  const minute = Number(parts.hour) * 60 + Number(parts.minute);
  if (minute >= 9 * 60 + 30 && minute < 16 * 60) return "REGULAR";
  if (minute >= 4 * 60 && minute < 9 * 60 + 30) return "PREMARKET";
  if (minute >= 16 * 60 && minute < 20 * 60) return "AFTERHOURS";
  return "CLOSED";
}

export async function inspectSnapshot(env, now = new Date(), fetcher = fetch) {
  const manifestUrl = new URL(env.PUBLIC_MANIFEST_URL);
  manifestUrl.searchParams.set("worker_check", String(now.getTime()));
  const manifestResponse = await fetcher(manifestUrl, { cache: "no-store" });
  if (!manifestResponse.ok) throw new Error(`manifest HTTP ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  const overviewEntry = manifest.modules?.["market-overview"];
  if (!manifest.snapshot_id || !overviewEntry?.path) {
    throw new Error("public manifest is incomplete");
  }
  const dataRoot = new URL("./", manifestUrl);
  const overviewUrl = new URL(overviewEntry.path, dataRoot);
  overviewUrl.searchParams.set("snapshot", manifest.snapshot_id);
  const overviewResponse = await fetcher(overviewUrl, { cache: "no-store" });
  if (!overviewResponse.ok) throw new Error(`market-overview HTTP ${overviewResponse.status}`);
  const overview = await overviewResponse.json();
  const marketTime = overview.as_of || overview.data?.as_of || manifest.generated_at;
  const observedAt = Date.parse(marketTime);
  if (!Number.isFinite(observedAt)) throw new Error("market data time is invalid");
  const ageSeconds = Math.max(0, Math.floor((now.getTime() - observedAt) / 1000));
  const expectedSession = newYorkSession(now);
  const snapshotSession = manifest.source?.session || "CLOSED";
  const active = expectedSession !== "CLOSED";
  const maxAgeSeconds = expectedSession === "REGULAR" ? 25 * 60 : 70 * 60;
  const stale = active && (
    ageSeconds > maxAgeSeconds
    || (expectedSession === "REGULAR" && snapshotSession !== "REGULAR")
  );
  return {
    contract_version: CONTRACT_VERSION,
    snapshot_id: manifest.snapshot_id,
    generated_at: manifest.generated_at,
    market_data_time: marketTime,
    age_seconds: ageSeconds,
    expected_session: expectedSession,
    snapshot_session: snapshotSession,
    active,
    stale,
  };
}

export async function dispatchRefresh(env, fetcher = fetch) {
  if (!env.GITHUB_ACTIONS_TOKEN) throw new Error("GITHUB_ACTIONS_TOKEN is not configured");
  const endpoint = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const response = await fetcher(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "anli-market-radar-refresh-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (response.status !== 204) {
    throw new Error(`GitHub workflow dispatch HTTP ${response.status}`);
  }
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  return origin && ALLOWED_ORIGINS.has(origin)
    ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" }
    : {};
}

function json(payload, status, request) {
  return Response.json(payload, {
    status,
    headers: {
      ...corsHeaders(request),
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          ...corsHeaders(request),
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Max-Age": "86400",
        },
      });
    }
    if (request.method !== "GET" || url.pathname !== "/health") {
      return json({ error: "not found" }, 404, request);
    }
    try {
      const snapshot = await inspectSnapshot(env);
      return json({ ok: !snapshot.stale, ...snapshot }, snapshot.stale ? 503 : 200, request);
    } catch (error) {
      return json({
        ok: false,
        contract_version: CONTRACT_VERSION,
        error: error instanceof Error ? error.message : "snapshot inspection failed",
      }, 503, request);
    }
  },

  async scheduled(controller, env) {
    const now = new Date(controller.scheduledTime);
    if (controller.cron === WEEKEND_CALENDAR_CRON) {
      await dispatchRefresh(env);
      console.log(JSON.stringify({ event: "weekend_calendar_refresh_dispatched" }));
      return;
    }
    let snapshot;
    try {
      snapshot = await inspectSnapshot(env, now);
    } catch (error) {
      console.error(JSON.stringify({ event: "snapshot_check_failed", message: String(error) }));
      await dispatchRefresh(env);
      return;
    }
    if (snapshot.stale) {
      await dispatchRefresh(env);
      console.log(JSON.stringify({ event: "refresh_dispatched", ...snapshot }));
      return;
    }
    console.log(JSON.stringify({ event: "snapshot_fresh", ...snapshot }));
  },
};
