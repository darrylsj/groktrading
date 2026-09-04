# Operating model

## Purpose and non-promises

This package supports a small discretionary options workflow with a live Tradier account on the order of **hundreds of dollars of cash** and a Tradier sandbox paper account. Stated milestones are **$1,000** then **$10,000**. Those are operator goals, not forecasts. This software **does not promise profitability** and **must not invent prices or P&L**.

## Modes

| Mode | How to enable | Places orders? |
| --- | --- | --- |
| `signals_only` (default) | Implicit | No |
| `paper` | Explicit `GROKTRADING_MODE=paper` | Sandbox only, after preview + gate |
| `live` | Explicit mode **and** `live_explicitly_enabled` | Never from this package by default; WS path hard-fails |

## Live rules (operator policy encoded in the gate)

1. One-lot options only (`quantity == 1`).
2. Sit-2: at least two confirmations before candidacy.
3. Matching ask (limit equals fresh ask, optional tick tolerance).
4. Skip already-run names/contracts for the session.
5. No first-red.
6. No spray (Helsinki filter; not a WS fan-out to the broker).
7. Cash/equity **≥50%** at all times. Overnight long options are allowed. **12:30 PT is a new-entry cutoff only** (not a forced flatten).
8. WebSocket events must never directly trigger live orders.
9. Final gate rechecks: fresh Tradier option quote, TTL, matching ask, buying power/cash, quantity 1, duplicate/working orders, market hours, 12:30 new-entry cutoff.

## Paper vs production pricing

Sandbox market data is delayed. Paper fills are **artifacts**. **Tradier production NBBO is pricing truth**. Reconciliation records `sandbox_fill − production_ask` and explicitly is **not P&L**.

## LLM

The LLM thesis / approve-skip path is not in the broker path and must not call Tradier. Helsinki does not poll the model; it **pushes** signed facts. A skip is always valid. An approve still cannot bypass the gate. The deterministic gate / executor **does** use Tradier production for fresh OCC quotes and live orders.

## Reviewer

The passive reviewer inspects git and audit files **after** the fact. The reviewer is not a runtime dependency and must not be placed inside the webhook or gate loop.

## Rebuild / new host

Operator install path (new VPS, parallel `/opt/groktrading`, cutover checklist): [DEPLOY.md](DEPLOY.md). The installer never enables live trading and never claims this commit is deployed.
