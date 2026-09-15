# Helsinki RTH live-board refresh (zero LLM)

Helsinki owns weekday US cash RTH refresh of the public desk board
([`darrylsj/trading-desk-live-board`](https://github.com/darrylsj/trading-desk-live-board),
Vercel). This path is a **host companion**: files in, static HTML/JSON
out. **No LLM. No Cursor wakes. No Grok webhooks.**

Grok Continual15 still writes pack evidence cards separately. The board
may lag the refuse ledger until that file is synced to the host — that
hole is reported, not invented.

Builder SoT: [`dashboard/`](../dashboard/). Companion:
[`scripts/live_board_refresh.py`](../scripts/live_board_refresh.py).
Example units:
[`deploy/examples/systemd/host-companions/`](../deploy/examples/systemd/host-companions/).

Related: [DASHBOARD.md](DASHBOARD.md), [REALTIME_PLANES.md](REALTIME_PLANES.md),
[WEBSOCKETS.md](WEBSOCKETS.md).

## What it does

Every 5 minutes **09:00–15:55 ET Monday–Friday** (`CRON_TZ=America/New_York`,
aligned with Continual15 looks):

1. Read `/opt/trading-desk/live_tape.json`,
   `/opt/trading-desk/finnhub_tape.json`,
   `/opt/trading-desk/state/shortlist.json`.
2. Best-effort refuse ledger (first file that exists):
   `evidence/uw_opportunity_refuses.jsonl`, `state/` or repo-root copies,
   or `/var/lib/trading-desk/...`. Missing → empty funnel + honest lag
   note.
3. Optional book / open orders if those JSON files exist or if
   `live_tape.json` already carries a positions / orders list. Never
   invent prices, marks, or P&L.
4. Write `/opt/trading-desk/state/live_board/live.json` and
   `index.html` (also `board.json` for the sibling-site alias).
5. If `/etc/trading-desk/vercel.env` has `VERCEL_TOKEN`, deploy those
   artifacts to Vercel production project `trading-desk-live-board`
   (Deploy API, then `npx vercel deploy --prod` fallback). Token
   missing: local write + **exit 0**.

Panels: book, open orders (if known), shortlist candidates, `ws_stats`
(Finnhub producer + live_tape + shortlist consumer), opportunity funnel.

## What it does not do

| Rule | Meaning |
| --- | --- |
| No LLM | Script is stdlib + the in-repo dashboard builder. No model APIs |
| No Cursor / Grok wake | No webhooks. `sit_match` stays **OFF** |
| Opportunity webhook stays paused | Does not resume `shortlist_opportunity` |
| Read-only toward brokers | Does not place, cancel, or replace orders |
| Never invent prices | Missing book / refuse / tape → `present=false` + `empty_reason` |
| Never log tokens | `vercel.env` values are not printed. Deploy uses env, not argv |

**Merge ≠ Helsinki restart.** `install_helsinki.sh` documents the
operator steps and does **not** copy, enable, or start these units.

## Operator enable (after `vercel.env` exists)

```bash
# 1. Token file (root 0600). Skip if dest exists.
sudo install -o root -g root -m 0600 \
  deploy/examples/env/vercel.env.example /etc/trading-desk/vercel.env
# edit in place — replace YOUR_* — chmod 0600

# 2. Writable artifact dir for User=tradingdesk
sudo install -d -o tradingdesk -g tradingdesk -m 0755 \
  /opt/trading-desk/state/live_board

# 3. Copy example units (not installer-managed)
sudo install -m 0644 \
  deploy/examples/systemd/host-companions/trading-desk-live-board-refresh.service \
  /etc/systemd/system/
sudo install -m 0644 \
  deploy/examples/systemd/host-companions/trading-desk-live-board-refresh.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-desk-live-board-refresh.timer
```

CI and hosts without a token still build locally:

```bash
PYTHONPATH=src:. python scripts/live_board_refresh.py \
  --live-tape tests/fixtures/dashboard/live_tape_health.json \
  --finnhub-tape tests/fixtures/dashboard/finnhub_tape.json \
  --shortlist tests/fixtures/dashboard/shortlist.json \
  --refuses tests/fixtures/dashboard/uw_opportunity_refuses.jsonl \
  --out-dir /tmp/live-board \
  --skip-deploy
```
