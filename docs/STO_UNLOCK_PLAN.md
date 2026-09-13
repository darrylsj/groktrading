# STO / I4 unlock plan (operator contract)

**Source of truth:** Trading Desk pack, operator intent **2026-09-12**.
Dates below are pasted from that pack. **Do not invent extra dates.**
This page is the GitHub README contract for the credit/STO hold. It is
**not** a live unlock and it does **not** flip `live_order_gate`.

**Mindset:** abundance — a **dated process hold**, not a forever ban.
Naked STO stays refused. Defined-risk I4 can unlock after the Wed card.

This PR does **not** weaken the cash floor (≥20% / max deploy 80%), the
**WebSocket → orders** ban, or the rule that live credit (when/if
unlocked) still goes through `tools/live_order_gate` — **no raw POST**.

Paper toolkit (when present): [`tools/i4_credit_paper`](../tools/i4_credit_paper).
This tree shipped a **stub README only** (pack-first). Do not treat the
stub as a live or paper executor.

---

## Current posture (as of this page)

| Item | Status |
| --- | --- |
| Live STO / credit | **Dated hold through Tue 2026-09-15 RTH** |
| Paper I4 | **Mon–Tue** (2026-09-14 and 2026-09-15) only |
| Unlock review | **Wed 2026-09-16 open card** |
| Default bias at that card | Remove the **blanket** ban; **allowlist defined-risk I4** through `live_order_gate` |
| Naked STO after unlock | **Still refused** |
| This package POST | **Never** (`live_order_gate` is dry-run / audit only) |

Do not read “credit/STO banned” in older comments as a permanent religion.
The hold ends at a **named session** or a **named next review**, not “until
someone feels like it.”

---

## Calendar (do not invent)

All session labels are **regular trading hours (RTH)** unless marked
otherwise. Host trading routines use `CRON_TZ=America/New_York`. Encoded
new-entry cutoff stays **12:30 America/Los_Angeles**.

| When | What |
| --- | --- |
| Operator intent written | **2026-09-12** |
| Sat–Sun 2026-09-12/13 | Weekend. Not RTH. Not a paper-I4 day. Not an unlock. |
| Mon 2026-09-14 RTH | Paper I4 day 1 |
| Tue 2026-09-15 RTH | Paper I4 day 2. **Live STO/credit stay on hold through this session.** |
| Wed 2026-09-16 **open card** | Unlock review. Default bias = drop blanket ban + allowlist defined-risk I4. |

**Weekend calendar risk:** the first paper day is the Monday after the
intent was written. If Mon or Tue paper does not happen, checklist item 4
allows a **logged no-0DTE refuse** — log it; do not silently skip and
then unlock. If the Wed card is missed, the FAIL path below applies
(name the gap; next review **≤3 RTH days**). Do not slide into an
open-ended ban.

US market calendar for this window: **2026-09-14 and 2026-09-15 are
scheduled RTH** (Labor Day 2026 was 2026-09-07). This page does not
invent holiday closures.

---

## Paper I4 (Mon–Tue only)

Paper **only**. Not live. Not a raw POST. Not Continual15 BTO hunt.

| Constraint | Value |
| --- | --- |
| Structure | Defined-risk vertical |
| Legs | **2-leg** |
| Width | **$1** |
| Underlyings | **SPY / QQQ** only |
| Quantity | **1** |
| Venue of this experiment | **Paper** (sandbox / journal). Production NBBO remains pricing truth. |
| Settlement (Codex) | **SPY/QQQ American / physical.** Timed **pre-expiry close**. Paper intrinsic = **simulation** — not assignment truth. |

This is **I4** (defined-risk credit vertical). It is **not**:

- **I1** print freshness (`SIT_MATCH_MAX_AGE_SEC=60`)
- **I1** `must_trade_small` (BTO debit clearer after ~11:00 PT)
- **I2** sit-2 lean bar
- **Opening15** (research-only first-15 paper)
- A **Wheel Desk** (cash-secured puts / covered calls / CSP roll). Wheel
  is a different book. Do not route I4 through Wheel language, Wheel
  sizing, or Wheel “collect premium and wait” exits.

---

## Wed 2026-09-16 open card (unlock review)

**Default bias:** remove the **blanket** credit/STO ban and **allowlist
defined-risk I4** through `live_order_gate`.

That is **not** “credits are free.” After a PASS card:

- Defined-risk I4 may be live **only** via the gate allowlist (flag +
  shape checks). **Not** a raw POST. **Not** WebSocket-triggered.
- **Naked STO stays refused.**
- **One unlock authority:** Trading Bot on Wed open checklist PASS +
  controlled flag. Not a raw POST. Not a silent merge.
- **Pause** (post-unlock kill) **blocks new entries, preserves exits.**
- Cash/equity **≥20%** (max deploy 80%) is unchanged. Define the cash
  budget / spread max-loss **against that floor** — do not lower it.
- 12:30 PT remains a **new-entry cutoff only** (not a flatten).
- `evaluate_gate` / `OrderPayload.side` staying BTO-only on the package
  FSM is fine; I4 live (when/if) is a `live_order_gate` path, not a
  silent FSM credit type.

If the checklist **FAIL**s: **name the gap** and set the **next review
≤3 RTH days**. No open-ended ban. Example: a FAIL on Wed 2026-09-16
implies a next card no later than **Mon 2026-09-21** RTH (3 RTH days:
Thu 17, Fri 18, Mon 21). Do not invent a later date.

---

## Unlock checklist (all six)

Score **PASS** only if every line is true at the Wed open card. A FAIL
names the gap.

1. **Entry=exit audit on paper I4** — every paper I4 ticket has a written
   entry thesis **and** a named exit / falsifier (same standard as BTO
   `how_it_dies`). No “open credit, figure it out later.”
2. **Defined risk only** — 2-leg, **$1** wide, **SPY/QQQ**, **qty=1**,
   **max_loss ≤ cash**. Not a short naked, not a 3+ leg condor, not a
   wide vertical, not an earnings lotto.
3. **Naked STO still refused** — `sell_to_open` without the defined-risk
   long leg is still `credit_or_sto_banned` (or a more specific refuse).
   After unlock this remains true.
4. **Paper scorecard Mon+Tue** — both sessions have a scorecard **or** a
   logged **no-0DTE refuse**. Silence is not a scorecard.
   **Refuse-only Mon–Tue ≠ lifecycle proof**; if there is no paper
   trade, require a **deterministic lifecycle test**.
5. **Gate allowlist flag ready (not raw POST)** — a named, default-off
   flag in `live_order_gate` (or the Bot wrapper that **only** submits
   what the gate emits). Operator HTTP is still a separate step. There
   is **no** “just POST the spread.”
6. **`reconcile-book` still cancels orphan credits** — any credit that
   is not on the allowlisted book / parent signal is cancelled. Do not
   leave a working short that the gate did not admit.

---

## Kills after unlock

These fire **after** a PASS card. They do not weaken the hold before
Wed.

| Trigger | Action |
| --- | --- |
| Ungated live credit (raw POST, WS→order, or submit that skipped `live_order_gate`) | **Re-ban + audit** |
| **−1× max_loss** twice in **5 sessions** | **Pause live I4** |

Pause ≠ forever ban. **Pause blocks new entries, preserves exits.** A
pause is a new dated hold + a named next review (again ≤3 RTH days if
the card FAILs). Re-ban+audit is a process event, not a personality
change. Do **not** recommend keeping a forever ban.

---

## What this repo encodes today (facts)

Verified in this tree at the time this page was written. Not a host
deploy claim.

| Surface | Fact |
| --- | --- |
| `tools/live_order_gate` | Dry-run. Never POSTs. Entry `buy_to_open` only. Exact-side / exact-strategy credit+STO refuse (`credit_or_sto_banned`). |
| `BANNED_ENTRY_SIDES` | Includes `sell_to_open`, `sell`, `credit`, `credit_spread`, `sto` |
| `BANNED_ENTRY_STRATEGIES` | Includes `credit_spread`, `short_put`, `short_call`, `iron_condor`, `sell_to_open`, `sto`, `naked_short`, … |
| `ENTRY_STRATEGIES` | `must_trade_small`, `sit2`, `i1`, `i2`, `discretionary_entry` — **no `i4`**. The set is documentary; submit does not allowlist from it. |
| Tradier form builder | **Single-leg** (`class=option`, one OCC, one side). No 2-leg vertical payload. |
| Allowlist flag | **Absent.** Refuse strings now say **dated hold through Tue 2026-09-15 RTH**, not “forever.” The refuse **code** is unchanged. |
| `tools/i4_credit_paper` | **Stub README** in this PR. Pack-first. Not an executor. |
| `reconcile-book` | **Not in this tree.** `PaperLedger.reconcile` is sandbox fill vs production ask (not P&L). `OrderMachine.reconcile_flat` is BTO FSM. Neither cancels orphan **credits**. |
| Cash floor / WS / no raw POST | Unchanged. Do not “unlock” by lowering them. |

---

## Codex / Astra audit (blunt)

Auditor posture: process contract vs coded unlock are different
questions. Do not grade the operator for writing a dated hold. Do not
grade the repo as if Wed already happened. **Do not recommend keeping a
forever ban.** Naked STO stays refused.

### Local Codex gpt-6-astra (pack unlock review)

**PASS-WITH-FIXES** (not forever-ban). Gaps before Wed unlock — Codex
bullets, almost verbatim:

1. gate still single-leg submit — need full audited spread path before live allowlist
2. validate OCC root/expiry/type/width/$1/protective direction at live submit
3. define cash budget / spread max-loss vs ≥20% floor
4. exit evidence must require confirmed fills (not ack=closed)
5. fix settlement language — SPY/QQQ American/physical; timed pre-expiry close; paper intrinsic = simulation
6. refuse-only Mon–Tue ≠ lifecycle proof; require deterministic lifecycle test if no paper trade
7. one unlock authority (Trading Bot on Wed open checklist PASS) + controlled flag; pause blocks new entries, preserves exits
8. naked STO stays refused — do not keep a forever ban

These seven engineering gaps plus the standing eighth (naked STO
refused / no forever ban) are the pre-Wed bar. A PASS card without
them is a process wish, not a live allowlist.

### Is the plan clear, dated, and non-arbitrary?

**Yes, as operator intent.** The hold has a **last live-ban session**
(Tue 2026-09-15 RTH). Paper has **two named days**. Unlock has a **named
open card** (Wed 2026-09-16) and a **default bias** (drop blanket ban;
allowlist defined-risk I4). FAIL is not vibes: name the gap, next review
**≤3 RTH days**. Post-unlock kills are numeric (ungated credit;
−1× max_loss ×2 / 5 sessions). Naked STO is carved out on both sides of
the card. That is the opposite of a forever ban and the opposite of
“YOLO the short put.”

The abundance read is correct: **process hold**, then a **narrow
allowlist**, not “never sell premium again.”

### Gaps

1. **Missing code hooks (expected; this PR is docs-first).** There is no
   `i4` strategy, no 2-leg form, no `max_loss` field, no SPY/QQQ
   allowlist, no qty/width/cash-vs-max_loss check that would admit a
   vertical. `credit_spread` is banned **by name**. `sell_to_open` is
   banned **as a side**. A Wed PASS card without a follow-up code PR
   cannot lawfully live-I4 through this package — and **must not**
   bypass via raw POST.
2. **“Allowlist” is still a phrase, not a flag.** Checklist item 5 says
   the flag must be ready by the card. Today it is not. Spell the
   contract before coding: one named flag (example:
   `LIVE_I4_DEFINED_RISK_ALLOWLIST=0`), default **off**, read only by
   `live_order_gate`, never by a WebSocket callback. Shape checks
   (2-leg, $1, SPY/QQQ, qty=1, max_loss ≤ cash, naked STO refuse) are
   the allowlist **body**. A boolean with no shape checks is a hole.
   A shape check with no flag is a silent unlock. Need both.
3. **Weekend / calendar risk.** Intent is Friday 2026-09-12; first
   paper day is Monday. Easy to lose Mon to “it’s the weekend / I’ll
   start Tuesday.” Item 4 already has the escape (`logged no-0DTE
   refuse`). Use it. Do **not** unlock on Wed with zero paper
   artifacts and no refuse log. If Wed is missed, the clock is **≤3
   RTH days**, not “next month when we remember.”
4. **I1 / I2 / I4 / Wheel collision.** This repo already overloads
   **I1** (print freshness **and** `must_trade_small`). **I4** is a
   third namespace from the pack. Wheel is a fourth idea (CSP/CC) that
   must not inherit this allowlist. Continual15 remains **BTO debit
   hunt**. Opening15 remains **research paper**. I4 paper/live is a
   **separate book** with its own scorecard. Mixing them will produce
   a fake PASS (BTO scorecard used as I4 evidence) or a fake FAIL
   (sit-2 rejected a credit that was never supposed to use sit-2).
5. **`reconcile-book` is named in the checklist and missing in git.**
   Until a host command or in-repo helper exists and is proven to
   **cancel orphan credits**, item 6 cannot PASS. Do not rename
   `PaperLedger.reconcile` into that role — it does not cancel anything.
6. **Single-leg Tradier form.** Even a perfect flag cannot emit a
   defined-risk vertical until the form grows two legs (or two linked
   tickets with a documented atomic preview). Codex: **need full
   audited spread path before live allowlist.**
7. **OCC / width / protective direction not validated at submit.**
   Live I4 must check root (SPY/QQQ), expiry, type, **$1 width**, and
   protective direction. Missing any of those is a naked-shaped hole.
8. **Cash budget vs ≥20% floor is undefined for spreads.** Max-loss
   must sit **inside** the cash floor math. Do not lower
   `CASH_EQUITY_FLOOR` to “make room.”
9. **Exit evidence is ack-shaped today.** Confirmed **fills**, not
   `ack=closed`. Same bar for paper I4 entry=exit audit.
10. **Settlement language was ETF-casual.** SPY/QQQ options are
    **American / physical**. Require a **timed pre-expiry close**.
    Paper intrinsic marks are **simulation**, not assignment truth.
11. **Refuse-only Mon–Tue is not a lifecycle.** If no paper trade
    prints, run a **deterministic lifecycle test** (open→hold→close
    or documented refuse-at-each-step). Logged no-0DTE refuse alone
    does not prove the book can flatten a credit.
12. **Unlock authority must be singular.** Trading Bot on **Wed open
    checklist PASS** + **controlled flag**. Pause **blocks new
    entries, preserves exits.** Not N people flipping env.

### What this audit refuses to “fix”

- Do **not** lower `policy.CASH_EQUITY_FLOOR` (0.20) to “make room” for
  a credit.
- Do **not** let WebSocket (UW / Finnhub / Tradier account-events /
  sit_match) place or close I4.
- Do **not** treat a Bot HTTP client as the gate. The gate emits the
  form; the client may POST **that** form after operator policy. Raw
  POST of a short is the post-unlock **re-ban** trigger.

### Verdict: ready to be the README contract?

**PASS-WITH-FIXES.**

| Question | Grade |
| --- | --- |
| Dated, non-arbitrary process contract for README? | **PASS-WITH-FIXES** — dates, checklist, default bias, FAIL clock, and kills are enough to cite from README. Fixes = name the missing hooks so nobody thinks merge = unlock. |
| Coded live-I4 ready? | **FAIL** — correctly. Docs-first. Do not flip the gate in this PR. |
| Forever-ban language vs hold? | **PASS** after this PR’s refuse-string / comment soften. Code still refuses. |

A clean **PASS** as README contract would also require Codex’s pre-Wed
gaps closed (audited spread path, OCC/width/direction checks, cash
budget vs ≥20% floor, fill-not-ack exits, settlement language,
lifecycle test if no paper trade, one Trading Bot unlock authority +
controlled flag). Those are **pre-Wed** code/ops items, **not** reasons
to keep a forever ban in the README.

---

## Top fixes before Wed 2026-09-16 unlock

Do these **before** the open card if the default bias is to allowlist.
None of these is “lift the hold early.” Codex gpt-6-astra list, almost
verbatim — plus the standing refuse:

1. gate still single-leg submit — need full audited spread path before live allowlist
2. validate OCC root/expiry/type/width/$1/protective direction at live submit
3. define cash budget / spread max-loss vs ≥20% floor
4. exit evidence must require confirmed fills (not ack=closed)
5. fix settlement language — SPY/QQQ American/physical; timed pre-expiry close; paper intrinsic = simulation
6. refuse-only Mon–Tue ≠ lifecycle proof; require deterministic lifecycle test if no paper trade
7. one unlock authority (Trading Bot on Wed open checklist PASS) + controlled flag; pause blocks new entries, preserves exits
8. naked STO stays refused — do not keep a forever ban

Also still required (prior audit, not a substitute for the list above):
name the default-off flag in `live_order_gate`; point `reconcile-book`
at a real orphan-credit cancel; keep cash floor, WS→orders forbidden,
and no raw POST.

After the Wed card: **one unlock authority** — Trading Bot on open
checklist PASS + controlled flag. **Merge ≠ Helsinki restart. Merge ≠
live I4.** Pause later **blocks new entries, preserves exits.**
