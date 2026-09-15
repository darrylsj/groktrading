# Host companion examples (not auto-enabled)

Operator-wired units. **`install_helsinki.sh` does not copy, enable, or
start these.** **Merge ≠ Helsinki restart.** `User=tradingdesk`.
`emit_sit_match=False`. No `grok-webhook.env` on units that never emit.

| File | Role |
| --- | --- |
| `groktrading-flow-ledger.service` | UW option-trades → hot ledger |
| `groktrading-flow-alerts.service` | Local material JSONL only |
| `groktrading-tide.service` | Tide companion |
| `groktrading-screener.service` | Screener snapshot |
| `groktrading-quote-interest.service` | Quote interest |
| `groktrading-replay-scorecard.service` / `.timer` | After-close replay counts |
| `trading-desk-live-board-refresh.service` / `.timer` | Zero-LLM weekday RTH live-board refresh |

## Live-board refresh (zero LLM)

Helsinki owns weekday US cash RTH refresh of
[`darrylsj/trading-desk-live-board`](https://github.com/darrylsj/trading-desk-live-board).
Continual15 still writes pack evidence cards separately. This path does
**not** wake Cursor or Grok.

1. Place `/etc/trading-desk/vercel.env` (root **0600**) from
   `deploy/examples/env/vercel.env.example`. `VERCEL_TOKEN` required to
   deploy; `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` optional.
2. Ensure `tradingdesk` can write `/opt/trading-desk/state/live_board/`.
3. Copy the service + timer, `systemctl daemon-reload`, then
   `systemctl enable --now trading-desk-live-board-refresh.timer` **only
   if you intend to**.
4. Missing token: oneshot still writes local `live.json` + `index.html`
   and exits 0 (no crash loop).

Timer: `CRON_TZ=America/New_York`, every 5 minutes **09:00–15:55 ET**
Mon–Fri. `sit_match` stays OFF. Opportunity webhook stays paused.
See [docs/LIVE_BOARD_REFRESH.md](../../../../docs/LIVE_BOARD_REFRESH.md).
