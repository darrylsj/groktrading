# Trading Desk live board

In-repo SoT: [`dashboard/`](../dashboard/). Pack sync path (Grok box, **not**
this git tree): `/home/box/agent-data/projects/trading-desk/dashboard/`.

This package ports the desk board **builder** so GitHub
(`darrylsj/groktrading/dashboard/`) matches the live-card process. It is
**not** a claim that Helsinki files exist in CI, that the board is
deployed, or that the sibling Vercel site is updated by this merge.

**Helsinki owns weekday RTH refresh** (zero LLM):
[`scripts/live_board_refresh.py`](../scripts/live_board_refresh.py) +
`trading-desk-live-board-refresh.timer`. Continual15 still writes pack
evidence cards separately. The board may lag the refuse ledger until
that file is on the host. Operator notes:
[LIVE_BOARD_REFRESH.md](LIVE_BOARD_REFRESH.md).

Sibling static site: [`darrylsj/trading-desk-live-board`](https://github.com/darrylsj/trading-desk-live-board)
(Vercel). Consume `board.json` and/or `index.html`. Rebuild from evidence.
Do **not** fetch `/opt/trading-desk` from Vercel.

Aligns with [WEBSOCKETS.md](WEBSOCKETS.md) and
[REALTIME_PLANES.md](REALTIME_PLANES.md).

## What it is

A secret-free, fail-closed builder:

1. **Opportunity-process funnel** — read
   `uw_opportunity_refuses.jsonl` (refuse reasons, last evidence OCCs).
   Optional hooks: `shortlist.json` (plane 2) and a
   `tools/shadow_bets` `summarize` document. Hunt while the opportunity
   timer is paused: **Continual15 + `shortlist.json`**.
2. **Optional `ws_stats`** — READ-ONLY snapshots of Helsinki *health*
   files, when the operator passes them:
   - `finnhub_tape.json`: connection, freshness, symbols (stock last
     prints only; **Finnhub ≠ option NBBO**)
   - `live_tape.json` health keys only: `flow_n`, `flow_http`, `errors`,
     `candidates` (count). Host-owned tape shape is otherwise unknown;
     unknown files stay `empty_reason=unknown_shape`.
3. **Static HTML/JSON** (`board.json` + `index.html`) for the sibling
   Vercel repo. No backend, no credentials, no sockets.

Schema: `groktrading.desk_board.v1` ([`schemas/desk_board.json`](../schemas/desk_board.json)).

## Hard rules (code, not prose)

| Rule | Meaning |
| --- | --- |
| No new WebSocket subscriptions | Builder never opens Finnhub / UW / Tradier sockets |
| `sit_match` stays **OFF** | No unmute. Not the hunt bus |
| `shortlist_opportunity` stays **paused** | No webhook resume. Re-enable remains an operator decision if refuse-or-lift is &lt;30s |
| Never invent prices / P&L / OCCs | Invented refuse rows are skipped. Missing asks stay missing. `pnl` is always `null` on the shadow hook |
| Helsinki optional | Missing `/opt/trading-desk/*.json` → `present=false`. CI uses `tests/fixtures/dashboard/` |
| Not an order path | `live_gate=false`. Does not import or change `tools/live_order_gate` |

## What it is not

- **Not a Helsinki deploy.** Merge ≠ restart. Host paths below are ops
  documentation only.
- **Not a live tape schema.** `live_tape.json` remains host-owned
  ([REALTIME_PLANES.md](REALTIME_PLANES.md)). This builder reads four
  health keys when present and otherwise reports `unknown_shape`.
- **Not a sit_match or opportunity unmute.** See
  [WEBSOCKETS.md](WEBSOCKETS.md).
- **Not a price feed.** It does not copy prints or NBBO off the tape
  into the board.

## Host paths (docs only — not required in CI)

| Path | Role |
| --- | --- |
| `/opt/trading-desk/evidence/uw_opportunity_refuses.jsonl` | Opportunity refuse ledger |
| `/opt/trading-desk/state/shortlist.json` | Plane 2 shortlist (when the ranker is wired) |
| `/opt/trading-desk/finnhub_tape.json` | Finnhub health / last-print tape |
| `/opt/trading-desk/live_tape.json` | UW+Tradier tape (host-owned). Health keys only |
| `/opt/trading-desk/state/live_board/` | Helsinki RTH refresh output (`live.json`, `index.html`) |

## Sibling site contract

`darrylsj/trading-desk-live-board` should treat this repo as the schema
source:

| File | Role |
| --- | --- |
| `live.json` | Host refresh artifact (same document as `board.json`) |
| `board.json` | Whole document (`book` + `open_orders` + `funnel` + optional `ws_stats` + `hard_rules`) |
| `index.html` | Self-contained render + `<script type="application/json" id="board-data">` |

Copy those two files. Do not add API keys to the Vercel project for this
board. Do not point Vercel at Helsinki.

Example built from fixtures: [`dashboard/example/`](../dashboard/example/).

## CLI

```bash
PYTHONPATH=src:. python -m dashboard build \
  --refuses tests/fixtures/dashboard/uw_opportunity_refuses.jsonl \
  --out-dir /tmp/desk-board
```

Tape flags are optional. Tests prove funnel + `ws_stats` schema **without**
live Helsinki.
