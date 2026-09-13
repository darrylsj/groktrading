# Strategy factory (observational only)

In-repo SoT: [`tools/strategy_factory`](../tools/strategy_factory). Desk
defaults: [`config/strategy_factory.json`](../config/strategy_factory.json).

This is the useful slice of continuous strategy discovery
(**generate → paper → validate → kill**). It is a **hypothesis ledger**,
not a RenTech clone, not an 8-bot farm, and not a broker client.

## What it is

A pack-rooted, append-only ledger of strategy hypotheses with a stage
machine and an allowlisted confirmation set. Continual15 (or an operator)
records a candidate, cites existing evidence, advances it to paper, and
later validates or kills it. The CLI matches the Trading Desk pack so
existing prompts stay portable (`--id` / `--hyp-id`, `propose`, `confirm`,
`advance`, `reject`, `kill`, `retire`, `list`, `status`, `score-day`).

## What it is not

- **Not a live order path.** `live_gate` is **false** in config and
  **forced false in code**. Reaching `live_allow` does not submit, preview,
  or flip [`live_order_gate`](LIVE_ORDER_GATE.md).
- **Not a Tradier / Unusual Whales client.** Confirmation sources such as
  `tradier_fresh_ask` and `uw_print` are **citations** of evidence the
  operator already observed. This package does not fetch quotes.
- **Not a price or P&L inventor.** This tool never invents prices or P&L.
  Structured price fields are refused.
  `score-day` counts stages and confirmations. `pnl` is always `null`.
- **Not an STO / I4 unlock.** Defined-risk I4 and live credit remain on
  the dated hold / Wed open-card review:
  [STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md). A hypothesis in category
  `i4_defined_risk_credit` is observational paper tracking only.
- **Not a replacement for `evaluate_gate` / `Executor`.** Those stay
  BTO-only / operator-gated. This ledger does not write allowlist flags
  into the gate.

## Stage machine

```
candidate → paper → validated → live_allow → killed | retired
                 ↘ rejected (from candidate / paper / validated)
```

`kill` may also close any still-open stage. `retire` is for a graduated
idea (`validated` or `live_allow`) that is done being observed.

Desk gates (also in `config/strategy_factory.json`):

| Rule | Default |
| --- | --- |
| Active hyps per category per PT session | 3 |
| Unique confirmation sources for `validated` | 2 |
| Unique confirmation sources for `live_allow` | 3 |
| Named mechanism required for `validated` | true |
| Named falsifier required for `live_allow` | true |
| `live_gate` | **false (forced)** |

Categories: `flow_debit_bto`, `i4_defined_risk_credit`, `gex_shadow_obs`,
`overnight_carry`, `external_shadow`, `other`.

Confirmation allowlist: `uw_print`, `tradier_fresh_ask`, `gex_agree`,
`shortlist_hit`, `helsinki_fresh`, `mechanism_named`, `falsifier_named`.

## Storage

Pack root = env `STRATEGY_FACTORY_PACK` (required in CI/tests) or the
repo root when unset:

| Path | Role |
| --- | --- |
| `evidence/strategy_factory_events.jsonl` | Append-only actions |
| `evidence/strategy_factory_ledger.jsonl` | Hypothesis snapshots (last write wins) |
| `state/strategy_factory_active.json` | Derived open-hyp index |

CI tests point `STRATEGY_FACTORY_PACK` at a temp directory so the repo
tree is not used as a desk pack.

## Operator loop (Continual15-portable)

1. `propose` a candidate with category, title, mechanism, falsifier.
2. `confirm` only from the allowlist, citing existing evidence refs.
3. `advance` to `paper` (no extra confirmation bar).
4. After two distinct sources + a named mechanism, `advance` to
   `validated`.
5. After three distinct sources + a named falsifier, `advance` to
   `live_allow` — **still observational**. Live tickets still go through
   `live_order_gate` (dry-run here; Bot HTTP is a separate step).
6. `reject` / `kill` / `retire` with a written reason. `score-day` at the
   close card. Do not invent a mark to make a hyp look validated.
