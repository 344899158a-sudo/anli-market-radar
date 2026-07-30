import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { buildDecision, fetchMarketData } from "./core.mjs";
import { buildEventCalendar } from "./events.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const now = new Date();
const market = await fetchMarketData();
const calendar = buildEventCalendar(now);
const payload = {
  generatedAt: now.toISOString(),
  market,
  calendar,
  decision: buildDecision(market, calendar, now)
};

const outputDir = root;
await mkdir(outputDir, { recursive: true });
await writeFile(
  join(outputDir, "dashboard.json"),
  `${JSON.stringify(payload, null, 2)}\n`,
  "utf8"
);
console.log(
  `QQQ snapshot generated: ${market.price} | ${market.quoteLabel} | ${market.bars.length} chart bars`
);
