# Current desk policy

This is the dated operator policy snapshot moved from the README in PR #46.
It records reported desk behavior as of **2026-09-17 PT**; it does not verify
host configuration or change package defaults. For an introduction, start with
[README.md](../README.md). Host observations are in
[OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md); executable behavior is defined
by the checked-in code.

## Reading this snapshot

- **I1** refers to flow-print freshness and the `must_trade_small` entry path;
  **I2 / sit-2** refers to the two-confirmation path; **I4** is the proposed
  defined-risk credit-spread experiment.
- **OCC** is an option contract identifier. **BTO**, **STC**, and **STO** mean
  buy to open, sell to close, and sell to open. **UW** means Unusual Whales.
- **KEEP_PAUSED** means the opportunity webhook remains disabled.
  **SCORE-ONLY** means a diagnostic tag cannot authorize or veto a live order.

**Two unresolved labels from the source:** the review is recorded as
“Fri 2026-09-19 I4 review”, but 2026-09-19 is Saturday (Friday is 2026-09-18).
The intended review date needs operator confirmation; STO remains refused.
Also, `*/5 9-15 * * 1-5` fires from 09:00 through 15:55 ET, while the stated
hunt window ends at 15:00 ET. The Bot must enforce the stated window separately;
this document does not change a scheduler or authorize additional trading time.

## Current live card (operator-reported)

As of **2026-09-17 PT** (operator-deployed desk). Encoded cutoff and session labels use **PT**. Host trading routines use **`CRON_TZ=America/New_York`**. This card is **ops context**, not a claim that **this commit** is running on Helsinki. **Merge ≠ Helsinki restart.** Host observations: [docs/OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md).

Any older **≥50% cash floor**, **flatten-at-12:30 / cash-flat-by-close**, **no-overnight**, **take-gain ×1.40**, **I1 hard-60s as live consume**, **opportunity / `sit_match` as active hunt**, **UW MCP installed for live**, or **STO unlocked after Wed 2026-09-16** claim in this tree is **stale**.

### Capital / session

- **Planning frame: ~$25k** (may not be fully deposited). Live fills still respect actual Tradier cash/BP. Planning capital ≠ current broker equity
- **Cash/equity ≥20%** at all times / **max deploy 80%**
- **Overnight long options: ALLOWED**
- **12:30 PT = NEW-ENTRY CUTOFF ONLY** (15:30 ET; not a forced flatten). Fail-closed = no new risk; continue monitoring existing positions
- **Open stand-down new entries: 9:30–9:45 ET only**, then hunt. Close card **16:00 ET** (= 1:00 PM PT). Close is a card, not a flatten machine
- **Small size / one-lot preference (~$200)** — no extra house loss caps, no PDT caps, no hard concurrent-position caps, no daily-loser circuit breaker

### Hunt loop

- **Live hunt is Continual15** on `CRON_TZ=America/New_York */5 9-15 * * 1-5` (5-minute floor, **not** a literal 15-minute-only loop)
- **Opportunity / `sit_match` / `shortlist_opportunity` wake: KEEP_PAUSED** (latency / I1_stale history). Not the hunt bus
- **Helsinki = sensors/webhooks only**; **Grok Bot = sole decision + order path**
- **Live orders ONLY via `live_order_gate` write-thesis first** — raw POST forbidden. Entry is BTO-only; named exits may **sell_to_close** via the gate (dry-run / audit in this package)
- **Ask band HARD ±$0.02** at decision **and** submit recheck (`ask_drift`); never chase
- **I1 freshness SOFT 180s** (hard stale only **>180**). Package default `SIT_MATCH_MAX_AGE_SEC` is still **60s** until an operator copies a change — do not treat that encoded default as the live consume clock. Disagreement OPTIONAL on fresh OCCs; hard exception for same-OCC reentry after `dead_thesis` exit
- **Hard skips: META / NET / MU / AMD**; no SPCX; no INTC puts
- **Live STO / credit: still refused** pending **Fri 2026-09-19 I4 review**. Not unlocked. Do not invent an unlock. **Naked STO stays refused.** Plan: [docs/STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md)

### Take-gain (TRIAL — Darryl 2026-09-17)

- **Arm:** bid ≥ entry × **1.25** (was ×1.40; operator-stated INTC miss: peak 2.02 vs old arm 2.03 missed green)
- **Protect:** entry + **0.50** × (peak_bid − entry); ratchet with peak
- Dead thesis / operator flatten can override; no first-red stop as a house rule
- Do **not** lock. Do **not** treat ×1.40 as current. Fri `QQQ260911P00717000` remains historical n=1 only

### UW usage (2026-09-17)

- Live path mainly UW option-trades / flow → Tradier ask match
- **GUI live on plan:** 0DTE Flow, Interval Flow, Market Tide, Dark Pool/Large Trades, Multi-leg, News, Catalyst/Earnings calendars
- **GUI still delayed/gated:** Flow Alerts (2-day), Options Screener (2-day), Custom Alerts (30m)
- **UW MCP: DEFERRED** — do not install; if ever, box-only research toy, **never Helsinki**, **never Continual15 submit path**
- Continual15 **Friday+ shadow tags** are **SCORE-ONLY**: `stale_event>30s`, `stale_quote>2s`, `duplicate_event`, `spread_or_size`, `multileg_unresolved`, `catalyst_unknown` (+ latency ages)

**Live orders must NEVER be triggered by WebSocket alone**; final gates recheck fresh Tradier **production** quotes. **Grok/LLM is outside the broker execution boundary**: approve/skip on frozen facts only; never set OCC, qty, limit, account, or order action.

**Friday 2026-09-11 book (operator-stated; historical; not in `logs/trades.jsonl`):** open $421.74 → close flat $460.56. Sole live lot `QQQ260911P00717000` BTO 1.06 → STC 1.45; Tradier `close_pl` +$39. n=1. Do not treat as expectancy. Do not invent later fills or P&L.

OpenAI P0.4 flatten-everything / no-overnight is **rejected**. Checklist: [docs/SAFETY.md](SAFETY.md). Gate: [docs/LIVE_ORDER_GATE.md](LIVE_ORDER_GATE.md).

