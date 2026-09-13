# live_order_gate (in-repo SoT)

Grok Bot submit/close policy. **This package never POSTs.** Dry-run form +
audit only. The Bot / operator HTTP client is a separate step.

Until this note, `tools/live_order_gate` was **not in this tree**. The Grok
box hot-patched STC so Friday’s QQQ lot could close. GitHub `main` was still
BTO-only at submit: `close_with_audit` reused entry `assert_submit_policy` and
could not emit `sell_to_close`.

## Commands (dry-run)

```bash
PYTHONPATH=src:. python -m tools.live_order_gate write-thesis --out thesis.json \
  --signal-id sig1 --option-symbol SPY260903C00600000 --side buy_to_open \
  --limit 1.25 --strategy must_trade_small --thesis-text "…" \
  --written-at 2026-09-03T14:30:00+00:00 \
  --how-it-dies "bid <= 0.80 or thesis dead"

# Overnight hold: carry notes become required.
PYTHONPATH=src:. python -m tools.live_order_gate write-thesis --out thesis.json \
  --signal-id sig1 --option-symbol SPY260903C00600000 --side buy_to_open \
  --limit 1.25 --strategy must_trade_small --thesis-text "…" \
  --written-at 2026-09-03T14:30:00+00:00 \
  --falsifier "spot through the wall" \
  --overnight-carry --carry-dte 4 \
  --carry-event-risk "Monday gap into CPI" \
  --carry-rationale "Pin still below the gamma wall; 1% gap does not kill it." \
  --receipt receipt.json --evidence evidence.md --thinking thinking.jsonl

PYTHONPATH=src:. python -m tools.live_order_gate submit --thesis thesis.json --cash 600

PYTHONPATH=src:. python -m tools.live_order_gate close --thesis exit.json
PYTHONPATH=src:. python -m tools.live_order_gate close --thesis exit.json --form-json form.json
```

`--form-json` is optional. When present it must match the thesis-built form
(class, OCC, side, qty, type, duration, price, tag). Preview is the only
flag this CLI sets (`preview=true`). There is no `--submit` / live POST.

## Entry (fail-closed)

- Thesis required (`written_at` timezone-aware).
- `how_it_dies` / `falsifier` required on every **written** thesis
  (`write-thesis`). Alias accepted. Missing either name still fails.
- Overnight carry fields are **soft** (not a live flatten / cash-floor
  change). Same-day new entries may omit them. `--overnight-carry` /
  `overnight_carry=true` requires `carry_dte`, `carry_event_risk`, and
  `carry_rationale` (mechanism survival — not "cash floor OK"). Stamped on
  the thesis JSON, optional receipt JSON, evidence markdown, and a
  `thinking.jsonl` row under `gates/carry`.
- Side `buy_to_open` only.
- 12:30 PT new-entry cutoff (`past_entry_cutoff`).
- Cash debit: `limit × 100 × qty`; `cash_required` / `insufficient_cash`.
- Credit / STO is a **dated hold through Tue 2026-09-15 RTH** (not a
  forever ban), still refused by **exact** side and strategy
  (`sell_to_open`, `credit_spread`, …). Thesis **prose is not scanned**
  for `credit` / `sell`. **Naked STO stays refused** after any later
  allowlist. Defined-risk I4 unlock is the **Wed 2026-09-16 open card**,
  through this gate only — **no raw POST**. Plan:
  [STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md).
- Tag `A-Za-z0-9` only (Tradier).
- Same PT session + 8h entry thesis TTL.
- Exit thesis cannot be submitted as a BTO (`exit_thesis_not_for_submit`).

## Exit (`take_gain_exit` and named exits)

- Thesis required. STC without a thesis is `thesis_required`.
- Sides `sell_to_close` / `buy_to_close` only when `strategy` ∈
  `take_gain_exit`, `dead_thesis_exit`, `falsifier_exit`, `stop_exit`,
  `manual_exit`, `time_stop_exit`.
- **Skips** 12:30 cutoff and cash debit.
- `parent_signal_id` required. Closed parent/signal → `already_closed`.
- `write_thesis` allows exit sides; that is not a credit-ban hole.

## Not encoded here

Take-gain math (arm +40% / ratchet 50%) stays Bot process — **TRIAL n=1,
do not lock**. `evaluate_gate` / `OrderPayload.side` remain BTO-only so the
package FSM does not silently grow a credit type. This tool is the Bot
submit/close SoT, not a rewrite of `gate.py`. Overnight carry notes do
**not** auto-flatten, do **not** change the cash floor, and do **not**
allow credits/STO. Credit/STO remain on the dated hold (see
[STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md)). Optional green-week note:
[GREEN_WEEK_OPTIONAL_20260912.md](GREEN_WEEK_OPTIONAL_20260912.md).
