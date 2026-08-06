import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  dispatchRefresh,
  inspectSnapshot,
  MARKET_REFRESH_CRON,
  newYorkSession,
  WEEKEND_CALENDAR_CRON,
} from "../src/index.js";

const env = {
  PUBLIC_MANIFEST_URL: "https://example.test/data/manifest.json",
  GITHUB_OWNER: "owner",
  GITHUB_REPO: "repo",
  GITHUB_WORKFLOW: "deploy.yml",
  GITHUB_ACTIONS_TOKEN: "test-token",
};

function snapshotFetcher({ session = "REGULAR", marketTime }) {
  return async input => {
    const url = new URL(String(input));
    if (url.pathname.endsWith("manifest.json")) {
      return Response.json({
        snapshot_id: "snapshot-one",
        generated_at: marketTime,
        source: { session },
        modules: { "market-overview": { path: "snapshots/one/market-overview.json" } },
      });
    }
    return Response.json({ as_of: marketTime, data: {} });
  };
}

test("uses New York market sessions", () => {
  assert.equal(newYorkSession(new Date("2026-08-05T14:00:00Z")), "REGULAR");
  assert.equal(newYorkSession(new Date("2026-08-05T12:00:00Z")), "PREMARKET");
  assert.equal(newYorkSession(new Date("2026-08-08T14:00:00Z")), "CLOSED");
});

test("marks a current regular snapshot fresh", async () => {
  const result = await inspectSnapshot(
    env,
    new Date("2026-08-05T14:00:00Z"),
    snapshotFetcher({ marketTime: "2026-08-05T13:55:00Z" }),
  );
  assert.equal(result.stale, false);
  assert.equal(result.age_seconds, 300);
});

test("marks premarket data stale after the regular open", async () => {
  const result = await inspectSnapshot(
    env,
    new Date("2026-08-05T14:00:00Z"),
    snapshotFetcher({ session: "PREMARKET", marketTime: "2026-08-05T13:58:00Z" }),
  );
  assert.equal(result.stale, true);
  assert.equal(result.expected_session, "REGULAR");
});

test("dispatch uses a secret without exposing it in the URL or body", async () => {
  let request;
  await dispatchRefresh(env, async (input, options) => {
    request = { input: String(input), options };
    return new Response(null, { status: 204 });
  });
  assert.equal(request.input, "https://api.github.com/repos/owner/repo/actions/workflows/deploy.yml/dispatches");
  assert.equal(request.options.headers.Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(request.options.body), { ref: "main" });
});

test("wrangler cron expressions match the Worker constants", () => {
  const config = JSON.parse(readFileSync(new URL("../wrangler.jsonc", import.meta.url), "utf8"));
  assert.deepEqual(config.triggers.crons, [MARKET_REFRESH_CRON, WEEKEND_CALENDAR_CRON]);
});
