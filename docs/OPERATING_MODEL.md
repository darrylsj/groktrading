# Operating model

## Purpose and non-promises

This package supports a discretionary **YOLO options** workflow. **Planning / selection / multi-lift sizing is framed as $25,000 desk capital.** The goal is **capital expansion**, not capital preservation. Live Tradier fills may still be **cash-constrained on a smaller funded balance** until the $25k is deposited — do not confuse planning capital with current broker equity.

Historical note only: the live funded book started small (early operator notes used hundreds of dollars; milestones $1,000 then $10,000). That is not the primary planning frame.

There is also a Tradier sandbox paper account. Operator goals are not forecasts. This software **does not promise profitability** and **must not invent prices or P&L**. Encoded gate math remains **one-lot** (`quantity == 1`) unless the operator changes policy in code.

## Modes

| Mode | How to enable | Places orders? |
| --- | --- | --- |
| `signals_only` (default) | Implicit | No |
| `paper` | Explicit `GROKTRADING_MODE=paper` | Sandbox only, after preview + gate |
| `live` | Explicit mode **and** `live_explicitly_enabled` | Never from this package by default; WS path hard-fails |

## Live rules (operator policy encoded in the gate)

1. One-lot options only (`quantity == 1`).
2. Sit-2 is the **I2 lean/hold bar**: at least two confirmations before candidacy, unless `Candidate.must_trade_small=True`. That flag is a **logged** I1 exception (`must_trade_small_exception` on the gate result). It skips **only** `SIT2_INCOMPLETE`. Freshness, matching ask, ≥20% cash, qty=1, BTO-only, entry cutoff, and already-run stay hard. The ~11:00 PT daily-lot clock is Grok Bot Continual15 (not encoded in this package). On that path, ask/limit > $1.50 is refused unless `committed_i2` is true. Live Bot cheap band on funded cash is ~$0.80–$1.50; `PREFERRED_ONE_LOT_NOTIONAL` ($200) is not a silent live default.
3. Matching ask (limit equals fresh ask, optional tick tolerance).
4. Skip already-run names/contracts for the session.
5. No first-red.
6. No spray (Helsinki filter; not a WS fan-out to the broker).
7. Cash/equity **≥20%** at all times (max deploy 80%). Overnight long options are allowed. **12:30 PT is a new-entry cutoff only** (not a forced flatten). Flatten-everything / no-overnight is rejected.
8. WebSocket events must never directly trigger live orders.
9. Final gate rechecks: fresh Tradier **production** option quote (provider timestamps, OCC, delayed flag), TTL, matching ask, buying power/cash/20% reserve, quantity 1, duplicate/working/in-position from the broker snapshot, durable session facts, market hours, 12:30 new-entry cutoff. The LLM must not set OCC, qty, limit, account, or order action.

## Paper vs production pricing

Sandbox market data is delayed. Paper fills are **artifacts**. **Tradier production NBBO is pricing truth**. Reconciliation records `sandbox_fill − production_ask` and explicitly is **not P&L**.

## LLM

The LLM thesis / approve-skip path is not in the broker path and must not call Tradier. Helsinki does not poll the model. Hunt is three planes ([REALTIME_PLANES.md](REALTIME_PLANES.md)): tape stays hot; a thin ranker may write `shortlist.json`; Continual15 **pulls** frozen facts. `sit_match` POSTs are not the hunt bus. A skip is always valid. An approve still cannot bypass the gate. The deterministic gate / executor **does** use Tradier production for fresh OCC quotes and live orders.

## Reviewer

The passive reviewer inspects git and audit files **after** the fact. The reviewer is not a runtime dependency and must not be placed inside the webhook or gate loop.

## Rebuild / new host

Operator install path (new VPS, parallel `/opt/groktrading`, cutover checklist): [DEPLOY.md](DEPLOY.md). Different-provider full rebuild: [REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md). The installer never enables live trading and never claims this commit is deployed.
