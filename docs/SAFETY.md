# Safety

Public-audit context: [OPENAI_AUDIT_BRIEF.md](OPENAI_AUDIT_BRIEF.md) · [CLAUDE_AUDIT.md](CLAUDE_AUDIT.md). WebSockets: [WEBSOCKETS.md](WEBSOCKETS.md).

This is Darryl’s **YOLO** desk. Goal is **capital expansion** on a **$25,000 planning** frame, not capital preservation. Live fills may still be cash-constrained on a smaller funded balance until the $25k is deposited — planning capital ≠ current broker equity. Do **not** restore flatten-everything, no-overnight, daily-loser breakers, hard concurrent caps, or a ≥50% cash floor as “safer defaults.”

## Live card (authoritative)

Rewrite any older ≥50% / flatten-at-12:30 / no-overnight text to this card.

- **Overnight long options: ALLOWED.**
- **12:30 PT = NEW-ENTRY CUTOFF ONLY** (not a forced flatten). Fail-closed = no new risk; continue monitoring existing positions.
- **Cash/equity ≥20%** at all times as a pre-entry reserve / **max deploy 80%**. One-lot preference (~$200). No hard concurrent-position caps. No daily-loser circuit breaker.
- **Live orders must never be triggered by WebSocket alone.** Final gates recheck a **fresh Tradier production** option quote.
- **Grok/LLM is outside the broker execution boundary.** Approve/skip on frozen facts only. The model must never set OCC, qty, limit, account, or order action.

## Defaults

- `OperatingMode.SIGNALS_ONLY`
- `live_explicitly_enabled=False`
- Executor WebSocket path raises `LiveGatingError` if live mode is requested
- On-disk JSON is redacted
- HTTP timeouts fail closed
- `policy.CASH_EQUITY_FLOOR = 0.20` / `MAX_DEPLOY_RATIO = 0.80`
- `policy.OVERNIGHT_LONG_OPTIONS_ALLOWED = True`
- `policy.ENTRY_CUTOFF_FLATTENS_BOOK = False`

## Forbidden

- Credentials in git, unit files, tape JSON, or README examples beyond `YOUR_*` / `changeme` / `ACCOUNT_ID_REDACTED` placeholders. No live Tradier account numbers, `/home/box` audit-pack secrets, or host tokens.
- First-class live orders from Finnhub/UW/Tradier WS ticks
- Cash/equity below **20%** after a contemplated entry (max deploy 80%)
- Multi-lot options in this policy
- Invented quotes, fills, or P&L
- Auto-flatten of an overnight-allowed book at 12:30 PT
- GPL/AGPL runtime dependencies (Backtrader, Lumibot, Optopsy). See README research notes.

## Explicit REJECT of OpenAI P0.4 flatten-everything / no-overnight

An external engineering note proposed flattening everything at 12:30 PT and forbidding overnight holds. **That is rejected.** Darryl’s live card allows overnight long options. 12:30 PT stops **new entries** and may cancel working **entry** orders. It does not liquidate the book. If the cutoff cancel path fails, emit an alert and keep new entries blocked — do not flatten as a fallback.

## Gate checklist (final)

1. Fresh **Tradier production** option quote (sandbox/synthetic cannot pass live)
2. OCC symbol match after normalize; `delayed==false`; ask>0; bid≥0; bid≤ask
3. Provider `bid_date` / `ask_date` age (not HTTP receive time); reject future timestamps; max spread; no-chase
4. Candidate TTL
5. Matching ask
6. Buying power / cash vs ask × 100 × qty **and** cash/equity ≥20% after premium
7. Quantity exactly 1
8. Duplicate / working / in-position from **fresh broker** account + positions + orders (not candidate booleans alone)
9. Sit-2 / already-run / first-red from **durable session facts** unioned with the candidate (candidate cannot clear a block). Sit-2 remains the **I2 lean bar**. `must_trade_small` is a logged I1 exception (daily-lot floor after ~11:00 PT; clock is Continual15, not this package) and skips only `SIT2_INCOMPLETE` — not freshness, matching ask, cash floor, qty, BTO-only, cutoff, or already-run.
10. Market clock open
11. Before 12:30 PT new-entry cutoff (not a forced flatten; overnight long options allowed)
12. Preview-before-order for paper/live paths
13. Not a WebSocket-direct live submit

## Hardening (P0)

### P0.1 Quote freshness

`quote_gate.validate_entry_quote` is the production-quote validator. Live requires `source=tradier_production`, `delayed=false`, OCC match, provider timestamps, and a non-crossed, non-stale, non-future NBBO. HTTP time alone is not freshness.

### P0.2 Broker-authoritative final gate

`evaluate_gate` derives sit / already-run / duplicate / position from `SessionFacts` plus a fresh `AccountSnapshot` (cash, equity, working orders, open positions) and `ClockSnapshot`. Live without session facts fails closed. WebSocket cannot submit live. Live also requires `candidate.executed_at` age ≤ `SIT_MATCH_MAX_AGE_SEC` (default 60s); missing/unparseable/stale print fails closed (`missing_executed_at` / `stale_print`) — no `created_at` / `timestamp` substitute. `AccountSnapshot` cash/BP come from nested `cash.cash_available` or `margin`/`pdt.option_buying_power`, never `total_cash` (unsettled inflates BP / GFV).

### P0.3 Preview → submit state machine

`order_fsm.OrderMachine` is stub-safe (no live credentials). Lifecycle as practical:

`RECEIVED → VALIDATED → QUOTED → PREVIEW → FINAL_GATE → SUBMIT → ACK → FILLED|REJECTED|… → FLAT_RECONCILED`

Rules: immutable payload; preview the exact payload; refresh quote and rerun the gate; submit the same payload with `preview=false`; `tag=signal_id`; persist `signal_id` / payload hash / broker id; store `gate_passed_ts` on a pass and refuse FINAL_GATE→SUBMIT if older than `max_quote_age_seconds` (policy default 5s, same as quote_gate); **never blind-retry** an unknown submit — query Tradier (or the stub) by tag first.

### P0.4 Entry-cutoff (rewritten)

`policy.evaluate_entry_cutoff` blocks new entries after 12:30 PT and cancels working **entry** orders when the stub/API exists. It **never** calls flatten. Cancel failure raises an alert (`entry_cutoff_gate_failed`).

### Durable webhook idempotency

Helsinki today: in-memory debounce (~90s) only — weekend same-digest spam. Package: `idempotency.DurableIdempotency` (SQLite WAL) for **outbox** (Helsinki emitter) and **inbox** (Grok consumer). RTH: exact key + 90s debounce. After-hours / weekend: coalesce by digest so AH spam does not fan out. Copy this onto `/opt/trading-desk` only after an operator authorizes a restart.

### LLM boundary

`llm.LLMDecision` is approve/skip + thesis on frozen facts. `assert_no_broker_attr` / `assert_llm_decision_boundary` refuse OCC, qty, limit, account, and order action.

## Open-source pattern references (not vendored)

- **LEAN Tradier plugin** (QuantConnect, Apache-2.0) — preview/submit and broker adapter shape. Design reference only.
- **NautilusTrader** — reconciliation / lifecycle concepts. Design reference only.
- **Lumibot** (GPL) and **Optopsy** (AGPL) — **not vendored**, not imported, not a runtime.

This PR does **not** migrate the desk to LEAN, C#, Nautilus, Lumibot, or Optopsy.

## Measurement

- Freeze strategy parameters (sit-2 as the I2 lean bar, already-run, matching-ask, one-lot) except **safety** defaults (quote age, cash floor, cutoff). `must_trade_small` is an explicit logged exception, not a silent sit-2 loosen.
- Keep **selection / execution / risk** separate: Helsinki filters select; Grok approves/skips facts; the gate/executor owns risk and orders.
- **n=3 live days ≠ edge.** Do not invent fills or claim profitability.

## Secrets handling

Env files on a host: **root-owned, mode 0600**. Examples under `deploy/examples/env/`. Never copy real env files into this repo. `scripts/install_helsinki.sh` creates `/etc/trading-desk` (0700) if missing and **does not** overwrite existing `*.env`, print tokens, `--enable`/`--start` unless asked, or set live mode. See [DEPLOY.md](DEPLOY.md).

## This cloud agent

Must not deploy to, SSH to, or restart Helsinki systemd units. Helsinki deploy of this hardening is a **follow-up**: copy `ws_tape` debounce/idempotency later; apply `sit_match` `executed_at` freshness (`SIT_MATCH_MAX_AGE_SEC`, default 60s) on the live tape; wire account-events / flow ledger / Box rotate only after an operator authorizes any restart. **Grok Update Computer does not rebuild Helsinki.**
