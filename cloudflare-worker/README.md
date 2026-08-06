# ANLI refresh Worker

This Worker is a reliability trigger for the existing Python public-release pipeline. It does not calculate trading rules or expose secrets to either frontend.

## Required secret

Create a fine-grained GitHub token limited to `344899158a-sudo/anli-market-radar` with Actions write access, then store it only in Cloudflare:

```powershell
wrangler secret put GITHUB_ACTIONS_TOKEN
```

Never put the token in `wrangler.jsonc`, source code, GitHub Pages, logs, or chat.

## Validate and deploy

```powershell
npm test
wrangler deploy --dry-run
wrangler deploy
```

The weekday cron checks the published market-overview shard every 15 minutes and dispatches the existing `deploy-pages.yml` only when the snapshot is stale. The weekend cron refreshes the verified event calendar once per day.
