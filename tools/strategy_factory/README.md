# Strategy factory (observational ledger)

Hypothesis ledger for continuous strategy discovery:
**generate → paper → validate → kill**. Desk pack CLI, ported here so
Continual15 prompts stay portable.

**`live_gate=false` always.** This tool never places orders, never POSTs,
never calls Tradier or Unusual Whales, and never invents prices or P&L.
`live_allow` is a **ledger label only**. It does **not** replace
[`live_order_gate`](../live_order_gate) and it does **not** unlock STO / I4.
Those stay on the dated plan: [STO_UNLOCK_PLAN.md](../../docs/STO_UNLOCK_PLAN.md).

Longer note: [docs/STRATEGY_FACTORY.md](../../docs/STRATEGY_FACTORY.md).

## Stages

`candidate` → `paper` → `validated` → `live_allow` → `killed` | `retired`

`reject` is allowed from the earlier stages (`candidate`, `paper`,
`validated`).

## Categories (allowlist)

`flow_debit_bto`, `i4_defined_risk_credit`, `gex_shadow_obs`,
`overnight_carry`, `external_shadow`, `other`

## Confirmation sources (allowlist)

`uw_print`, `tradier_fresh_ask`, `gex_agree`, `shortlist_hit`,
`helsinki_fresh`, `mechanism_named`, `falsifier_named`

Those names are **citations** of evidence the operator already has. The
factory does not fetch a quote. Structured price fields (`ask`, `bid`,
`pnl`, …) are refused.

## Pack layout

Root = `STRATEGY_FACTORY_PACK` (tests) or the repo root:

- `evidence/strategy_factory_events.jsonl`
- `evidence/strategy_factory_ledger.jsonl`
- `state/strategy_factory_active.json`

Desk defaults: [`config/strategy_factory.json`](../../config/strategy_factory.json).
`live_gate` in that file is false and **forced false in code**.

## CLI

```bash
export STRATEGY_FACTORY_PACK=/tmp/sf-pack

PYTHONPATH=src:. python -m tools.strategy_factory propose \
  --id smoke-flow-001 --category flow_debit_bto \
  --title "UW print + matching ask BTO" \
  --mechanism "Fresh UW print + sit-2 + matching ask" \
  --falsifier "Print stale >60s or thesis dead" \
  --session 2026-09-03

PYTHONPATH=src:. python -m tools.strategy_factory confirm \
  --hyp-id smoke-flow-001 --source uw_print \
  --note "cited existing tape print" --evidence-ref tape:fixture

PYTHONPATH=src:. python -m tools.strategy_factory advance --id smoke-flow-001
PYTHONPATH=src:. python -m tools.strategy_factory list --session 2026-09-03
PYTHONPATH=src:. python -m tools.strategy_factory status --id smoke-flow-001
PYTHONPATH=src:. python -m tools.strategy_factory score-day --session 2026-09-03
```

`--id` and `--hyp-id` are the same flag. Other commands: `reject`, `kill`,
`retire` (each requires `--reason`).

Validated needs a named mechanism and 2 unique confirmation sources.
`live_allow` needs a named falsifier and 3 unique sources. Cap: 3 active
hypotheses per category per PT session.

## Kill this tool if

- It becomes a live gate or auto-allows STO / credits
- It starts calling Tradier / UW or inventing marks
- It grows an 8-bot / Telegram / Kimi architecture
