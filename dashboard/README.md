# Trading Desk live board

Observational board builder for the public `darrylsj/groktrading` package.
This is the GitHub home for the desk board that previously lived pack-only
(`dashboard/` 404 on this repo).

Pack sync path (Grok box, **not** this git tree):
`/home/box/agent-data/projects/trading-desk/dashboard/`

Longer note: [docs/DASHBOARD.md](../docs/DASHBOARD.md).
WebSockets: [docs/WEBSOCKETS.md](../docs/WEBSOCKETS.md).
Hunt planes: [docs/REALTIME_PLANES.md](../docs/REALTIME_PLANES.md).

Sibling static site (Vercel): [`darrylsj/trading-desk-live-board`](https://github.com/darrylsj/trading-desk-live-board).
This package writes `board.json` + `live.json` + `index.html`. The
offline builder does **not** deploy that repo. Helsinki weekday RTH
refresh ([`scripts/live_board_refresh.py`](../scripts/live_board_refresh.py))
is the zero-LLM deploy path when `vercel.env` has a token.
[docs/LIVE_BOARD_REFRESH.md](../docs/LIVE_BOARD_REFRESH.md).

## Hard rules

- **READ-ONLY** snapshots. **No new WebSocket subscriptions.**
- **`sit_match` stays OFF.** This builder does not unmute it.
- **`shortlist_opportunity` stays paused.** This builder does not resume
  the host webhook (`/opt/trading-desk/bin/shortlist_opportunity_webhook.py`).
- Never invent prices, P&L, or OCCs.
- Never commit credentials or API keys.
- Helsinki files (`/opt/trading-desk/finnhub_tape.json`,
  `live_tape.json`) are **optional**. CI uses fixtures. Missing files are
  `present=false` + `empty_reason`, not invented health.
- `live_gate=false`. Does **not** place orders or change
  `tools/live_order_gate`.

## What it builds

1. **Opportunity-process funnel** from `uw_opportunity_refuses.jsonl`
   (refuse reasons, last evidence OCCs, optional shortlist hook, optional
   shadow-bets summary hook).
2. **Optional `ws_stats`** — READ-ONLY keys from Helsinki *health* JSON:
   `finnhub_tape.json` (`connected` / freshness / symbols) and
   `live_tape` health (`flow_n` / `flow_http` / `errors` / `candidates`).
   Unknown `live_tape.json` shapes stay empty. Prints / NBBO are not copied.
3. **Static HTML/JSON** suitable for the Vercel sibling site.

## CLI

```bash
PYTHONPATH=src:. python -m dashboard build \
  --refuses tests/fixtures/dashboard/uw_opportunity_refuses.jsonl \
  --shortlist tests/fixtures/dashboard/shortlist.json \
  --shadow-summary tests/fixtures/dashboard/shadow_summary.json \
  --finnhub-tape tests/fixtures/dashboard/finnhub_tape.json \
  --live-tape tests/fixtures/dashboard/live_tape_health.json \
  --session 2026-09-14 \
  --out-dir /tmp/desk-board
```

Writes `/tmp/desk-board/board.json`, `/tmp/desk-board/live.json`, and
`/tmp/desk-board/index.html`.
Stdout prints the same JSON.

Omit tape flags in CI. The builder must not require `/opt/trading-desk`.

Committed example output (built from the same fixtures):
[`example/`](example/).

## Kill this tool if

- It opens a WebSocket or adds a subscribe
- It unmutes `sit_match` or resumes `shortlist_opportunity`
- It invents OCCs, marks, or P&L
- It becomes a live order path
