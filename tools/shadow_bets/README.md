# Shadow bets RSI (observational)

Refuse ledger → Tradier-cited shadow outcomes. Desk pack CLI, ported here
so Continual15 prompts stay portable.

**`live_gate=false` always.** This tool never places orders, never POSTs,
never calls Tradier or Unusual Whales, and never invents NBBO or P&L.
Observational labels (`yes_latency_fix_wake`, …) do **not** unlock live
I1 past **60s**, do **not** re-enable `sit_match`, and do **not** change
`MUST_TRADE_SMALL_ASK_CAP`.

Pack source of truth (Grok box):
`/home/box/agent-data/projects/trading-desk/tools/shadow_bets/`
(`cli.py` + README). This tree mirrors that CLI.

Longer note: [docs/SHADOW_BETS.md](../../docs/SHADOW_BETS.md).
Wake-latency posture: [docs/REALTIME_PLANES.md](../../docs/REALTIME_PLANES.md).

## What it scores

Monday I1_stale backlog is mostly **wake latency**: the print was fresh
at emit, stale by the time Continual15 woke. Open those refuses as
shadow bets, then attach later **Tradier-cited** marks the operator
already captured. Missing marks stay **unmarked**. Coverage is reported.
OCC is required. `invented: true` marks are refused.

One-lot ask→bid dollars `(mark_bid − refuse_ask) × 100` only when both
prices were already on the input files. `summarize.pnl` is always
`null`.

## Labels (observational only)

| Label | Meaning |
| --- | --- |
| `yes_latency_fix_wake` | I1_stale / stale consume after a fresh emit (or I1_stale without hop clocks) |
| `no_latency_fix_wake` | Refuse was not a wake-latency miss |
| `yes_fresh_wake` | Consume still inside I1 60s |
| `unscored` | Operator-set |
| `other` | Operator-set |

These are **ledger labels**. They do not widen I1, unmute `sit_match`,
or flip `live_order_gate`.

## Pack layout

Root = `SHADOW_BETS_PACK` (tests) or the repo root:

- `evidence/shadow_bets_events.jsonl`
- `evidence/shadow_bets_ledger.jsonl`
- `state/shadow_bets_session.json`

## CLI

```bash
export SHADOW_BETS_PACK=/tmp/shadow-bets-pack

PYTHONPATH=src:. python -m tools.shadow_bets open-from-refuses \
  --session 2026-09-14 \
  --refuses tests/fixtures/shadow_bets/refuses.jsonl

PYTHONPATH=src:. python -m tools.shadow_bets mark-session \
  --session 2026-09-14 \
  --marks tests/fixtures/shadow_bets/marks.jsonl

PYTHONPATH=src:. python -m tools.shadow_bets summarize --session 2026-09-14

PYTHONPATH=src:. python -m tools.shadow_bets run-session \
  --session 2026-09-14 \
  --refuses tests/fixtures/shadow_bets/refuses.jsonl \
  --marks tests/fixtures/shadow_bets/marks.jsonl
```

`--session` is required (`YYYY-MM-DD`). Marks must cite
`tradier_production` or `tradier_sandbox` and set `invented` false (or
omit it). Synthetic / invented NBBO is refused.

## Kill this tool if

- It becomes a live gate or auto-allows a wider I1
- It starts calling Tradier / UW or inventing marks
- It re-enables `sit_match` as the hunt bus
