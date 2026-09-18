# Shadow bets RSI (observational only)

In-repo SoT: [`tools/shadow_bets`](../tools/shadow_bets). Pack sync path
(Grok box, not this git tree):
`/home/box/agent-data/projects/trading-desk/tools/shadow_bets/`.

This is the useful slice of Monday RSI: take the **refuse ledger**
(`I1_stale` wake-latency backlog and other consume refuses), open
observational shadow bets, then attach **Tradier-cited** marks the
operator already has. It is **not** a broker client and **not** a live
unlock.

## What it is

A pack-rooted, append-only ledger:

1. `open-from-refuses` — ingest refuse rows (OCC + reason + optional
   hop clocks / refuse ask)
2. `mark-session` — attach later Tradier bid/ask only when those marks
   are supplied (`invented` must not be true)
3. `summarize` — counts, observational labels, one-lot ask→bid $ when
   both prices were already present
4. `run-session --session YYYY-MM-DD` — the three steps for one PT day

CLI names match the Trading Desk pack so Continual15 prompts stay
portable.

## What it is not

- **Not a live order path.** `live_gate` is **false** and forced false.
  This tool never previews, submits, or imports `live_order_gate`.
- **Not a Tradier / Unusual Whales client.** Marks are citations of
  quotes the operator already captured. This package does not fetch
  NBBO and does not read credentials.
- **Not a price inventor.** Missing marks stay unmarked. `invented:
  true` / `source=synthetic` marks are refused. `summarize.pnl` is
  always `null`.
- **Not an I1 unlock.** Live consume age stays **60s**. Passing a wider
  max-age is `i1_widen_forbidden`. Labels such as
  `yes_latency_fix_wake` are observational only.
- **Not a sit_match unmute.** `sit_match` stays **OFF**. Hunt default
  while the opportunity timer is paused: Continual15 +
  `shortlist.json`. See [REALTIME_PLANES.md](REALTIME_PLANES.md).
- **Not a `MUST_TRADE_SMALL_ASK_CAP` change.** That cap stays $1.50.

## Labels

| Label | When |
| --- | --- |
| `yes_latency_fix_wake` | `I1_stale` / `stale_print` / `sit_match_stale` and (fresh at emit + stale at consume), or I1_stale without hop clocks |
| `no_latency_fix_wake` | Other refuse reasons, or hops that do not show a wake miss |
| `yes_fresh_wake` | Consume still inside then-I1 60s (historical label; operator live I1 is SOFT 180s as of 2026-09-17) |
| `unscored` / `other` | Operator-set on the refuse row |

## Storage

Pack root = env `SHADOW_BETS_PACK` (required in CI/tests) or the repo
root when unset:

| Path | Role |
| --- | --- |
| `evidence/shadow_bets_events.jsonl` | Append-only actions |
| `evidence/shadow_bets_ledger.jsonl` | Bet snapshots (last write wins) |
| `state/shadow_bets_session.json` | Derived session index |

CI tests point `SHADOW_BETS_PACK` at a temp directory so the repo tree
is not used as a desk pack.

## Operator loop

```bash
export SHADOW_BETS_PACK=/tmp/shadow-bets-pack

PYTHONPATH=src:. python -m tools.shadow_bets run-session \
  --session 2026-09-14 \
  --refuses path/to/refuses.jsonl \
  --marks path/to/tradier_marks.jsonl
```

Refuse rows need an OCC. Useful optional fields: `reason`,
`executed_at`, `emitted_at`, `consumed_at` / `woken_at`, `ask` /
`refuse_ask`, `label`. Mark rows need OCC + `bid` (or `mark_bid`) and
should cite `source=tradier_production` (sandbox allowed as delayed
artifact). Never invent a mid/last to fill a hole.
