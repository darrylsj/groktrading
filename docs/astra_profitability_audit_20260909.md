# Astra profitability audit — 2026-09-09

Read-only audit of `darrylsj/groktrading` at `68d4ce9` (Helsinki harden C2/C4/C5, PR #29).
Goal: make the **live Tradier options desk** profitable on the operator-stated YOLO book
(~$422 equity; plan toward $1,000+). Planning frame stays $25k; live fills must respect
actual cash/BP.

This is **not** a cleanliness review and **not** a proposal for more agents, more markets,
or a personal hedge fund.

**Scope split (do not collapse):**

| Surface | In this git tree? | Places live orders? |
| --- | --- | --- |
| Helsinki sensor farm (`flow_ledger`, companions, `sit_match` freshness) | Package helpers + example units | **No** |
| Encoded gate / FSM (`gate.py`, `quote_gate.py`, `order_fsm.py`) | Yes | Only if Grok Bot calls them |
| `live_order_gate`, Continual15, I1/I2, `must_trade_small` | **Not in this tree** | Operator / Grok Bot process |
| Host `ws_tape.py` | **Not in this tree** (`install_helsinki.sh` does not copy it) | Webhooks only |

Operator-stated house rules used as context (not re-derived here): Daily lot · small
unless committed; hard gates (executed_at ≤60s, Tradier ask matches print, skip
already-run ≥0.5% open, ≥20% cash, 12:30 PT new-entry cutoff, one-lot, never WS→orders,
never raw POST `/orders` without thesis+exit+falsifier); Helsinki = sensors;
account-events stays **disabled**; Schwab read-only until green Tradier days;
abandoned locks = morning-flow first-print, tuned 0.5% skip, spray, undocumented 0DTE
credits as default.

---

## 1) VERDICT

**FAIL** — the encoded sit-2 hard reject plus a dirty tape (0 clean lifts) cannot
execute the locked daily-lot plan, and the only recent realized bleed sits outside
`live_order_gate` / the journal, so there is no measured path to profitability on
this ~$422 book.

---

## 2) PROFIT LEAKS (ranked)

Each leak is tagged **process** (how the desk decides / records) vs **outcome**
(realized or blocked P&L). Outcomes use only committed journal rows or
operator-stated facts labeled as such.

### L1 — Sit-2 is a hard reject; the locked plan needs I1 `must_trade_small`

- **Process:** `evaluate_gate` rejects whenever derived sit confirmations `< 2`
  (`src/groktrading/gate.py:76-77`). Tests lock that (`tests/test_gate.py:57-59`).
  Session facts **min** with the candidate (`gate.py:45`), so stale/zero Helsinki
  `sit_confirmations` cannot be cleared by the Bot claiming sit-2
  (`gate.py:35-53`). `OPERATING_MODEL.md:21-22` still writes sit-2 as required
  before candidacy. `SAFETY.md:97-98` freezes sit-2 except safety.
- **Process (locked plan, not encoded):** lean/hold only on full I1+I2; if still
  flat by ~11:00 PT, take the best small I1 clearer (`must_trade_small`). That
  path is **absent** from this repo (no `must_trade_small`, no Continual15, no
  `live_order_gate` symbol).
- **Outcome:** operator-stated: sit-2 hygiene refused dirty tape (**0 clean
  lifts**); ~8 red/flat days. Encoded gate would also block the I1 clearer that
  is supposed to stop those sit-outs.
- **Do not “fix” by spraying or loosening executed_at.** Freshness is working as
  designed (L5).

### L2 — Live fills can bypass the package gate; credits are not even a type

- **Process:** `Candidate.side` and `OrderPayload.side` are `Literal["buy_to_open"]`
  only (`src/groktrading/models.py:92`, `src/groktrading/models.py:241`). There is
  no credit-spread / STO payload. `Executor.maybe_submit` live path **previews
  only** (`src/groktrading/executor.py:97-102`). CHANGELOG records this repo is
  **not** the live executor (PR #1 note, `CHANGELOG.md` “Previously added”).
- **Process:** Grok Bot can POST Tradier without calling `evaluate_gate`. The
  house rule “never raw POST without `live_order_gate`” is **not enforced in
  this package**.
- **Outcome (journaled):** 2026-09-03 SPCX 145p BTO **sit-1** at 0.86
  (`CHANGELOG.md` `[2026-09-03]`; `logs/trades.jsonl` last row). Encoded sit-2
  did not stop that fill.
- **Outcome (operator-stated, not in journal):** Wed unaudited **SPY credit −$37**.
  That fill is not in `logs/trades.jsonl`. Credit-as-default is already abandoned;
  this is a process hole, not an encoded strategy.

### L3 — No exit machine; LLM has no falsifier; old exits were 12:30 flatten

- **Process:** `LLMDecision` is `approve`/`skip` + `thesis` only
  (`src/groktrading/models.py:159-165`, `src/groktrading/llm.py:1-8`). No exit
  price, no invalidation, no STC side. `OrderMachine` payloads are BTO
  (`src/groktrading/order_fsm.py:74-82`). `policy.evaluate_entry_cutoff` **never**
  flattens (`src/groktrading/policy.py:70-118`) — 12:30 is new-entry cutoff only.
- **Outcome (journaled, n=4 closed):**

  | Session | OCC | Entry | Exit reason | `realized_usd` |
  | --- | --- | --- | --- | --- |
  | 2026-08-25 | AMZN 265c | 1.12 | `dead_thesis` (~16 min) | −28 |
  | 2026-08-25 | DRAM 57c | 0.98 | `12:30_cash_up` | −3 |
  | 2026-08-26 | NVDA 225c | 2.06 | `12:30_cash_up` | −31 |
  | 2026-08-27 | AAPL 312.5c | 1.33 | `12:30_cash_up` | +101 |

  Net of those four rows: **+$39**. That is **n=4, not expectancy**. Two of three
  losers were hold-to-cutoff. AAPL won the same way. Do not restore flatten as a
  default; do not claim hold-to-cutoff “works.”
- **Outcome (journal hole):** SPCX 9/04 145p (`SPCX260904P00145000`) remains
  `status=open`, `realized_usd=null` in `logs/trades.jsonl`. Listed expiry is
  2026-09-04; this audit is written 2026-09-10. **Missing measurement:** Tradier
  position/order reconcile vs that row. Do not invent an expiry P&L.

### L4 — Already-run is name/OCC, not “≥0.5% open”; can block or admit the wrong print

- **Process:** `already_run` is a boolean union of candidate +
  `already_run_underlyings` + `already_run_option_symbols`
  (`src/groktrading/gate.py:47-51`, `src/groktrading/models.py:123-128`). Replay
  scorecard counts first OCC vs later OCC (`src/groktrading/replay_scorecard.py:6-8`,
  `63-88`) and sets `pnl: None` always (`replay_scorecard.py:53`).
- **Process:** operator hard gate “skip already-run ≥0.5% open” is **not
  encoded**. There is no open-move percent check in `gate.py` / `sit_match.py`.
  CHANGELOG `2026-09-02` still says “do not drop already-run off MU hyp” — a
  different, undocumented rule.
- **Outcome:** insufficient. If Bot treats any prior print as already-run, a
  later clean I1 on a new name can still lift; if Bot marks the whole
  underlying, the daily lot dies after the first skip. **Need:** per-session
  refuse log (OCC, underlying %, reason).

### L5 — Freshness / host gap: package fail-closes; live tape may not

- **Process (helps):** `sit_match` uses **only** `executed_at`, default ≤60s;
  `created_at` / `timestamp` are not substitutes (`src/groktrading/sit_match.py:1-15`,
  `111-119`, `129-134`; C2 tests `tests/test_sit_match.py:145-154`,
  `tests/test_flow_ledger.py:155+`). Package webhook outbox + Grok inbox refuse
  stale sit_match (`src/groktrading/webhook.py:89-97`, `167-170`). Quote gate
  uses Tradier provider `bid_date`/`ask_date`, not HTTP receive time
  (`src/groktrading/quote_gate.py:1-6`, `92-105`); live default max quote age
  **5s** (`src/groktrading/policy.py:22`). Candidate TTL default **15s**
  (`src/groktrading/models.py:99`).
- **Process (hurts if host is stale):** `ws_tape.py` is host-owned and **not**
  copied by `scripts/install_helsinki.sh` (header ~lines 20, 131-132). Observed
  Helsinki debounce is in-memory ~90s/OCC — **not** a freshness gate
  (`docs/OBSERVED_DEPLOYMENT.md:18-22`). Merge ≠ restart.
- **Outcome:** operator-stated 0 clean lifts is consistent with either (a) sit-2
  hygiene on a dirty tape or (b) executed_at/TTL/matching-ask all refusing.
  **Missing measurement:** sit_match allow/deny counts by reason for those
  eight days. `replay_scorecard` can count stale_filtered vs first_print but
  does not prove the **host** tape applied C2.

### L6 — $25k / ~$200 notional frame vs ~$422 cash

- **Process:** `PREFERRED_ONE_LOT_NOTIONAL = 200` (`src/groktrading/policy.py:19`).
  Opening15 hygiene defaults `planning_equity_usd=25000`,
  `premium_budget_pct=0.008` → $200 debit / $2.00 ask
  (`src/groktrading/research/hygiene.py:22-28`) — **paper path only**, not
  imported by live gate. Cash floor math is real: remaining cash/equity ≥20%
  and premium ≤80% equity (`src/groktrading/policy.py:137-151`,
  `src/groktrading/gate.py:112-124`).
- **Outcome:** a $2.00 one-lot is ~$200 premium on a ~$422 book (~47% of
  equity). Locked default cheap band is ~$0.80–$1.50. Journaled NVDA entry
  **2.06** (−$31) is above that band. Planning-$25k selection that ignores
  funded cash is a size leak, not an edge.

### L7 — Companions and research theater do not create a daily lot

- **Process:** host companions are operator-wired, not installer-enabled;
  `emit_sit_match=False`; flow-alerts material is local JSONL, no Grok webhook
  (`scripts/flow_alerts_companion.py:4-6`, `README.md` Helsinki sensor-farm
  bullets). Flow-ledger companion stores UW option-trades (OTM, `min_premium=10000`,
  `max_dte=7`, …) and **does not emit** (`scripts/flow_ledger_companion.py:3-4`,
  `49-61`). Opening15 / selector_v3 / expanded collectors are paper-only
  (`src/groktrading/research/hygiene.py:7-8`). Account-events unit is files-only
  / disabled (`deploy/examples/systemd/groktrading-account-events.service:1-9`).
- **Outcome:** none of this produces a gated RTH one-lot. Enabling account-events,
  companion sit_match spray, or Opening15→live would add wake-ups, not a
  measured edge. **Do not enable them for P&L.**

### L8 — Closed-loop P&L measurement is off

- **Process:** `replay_scorecard.document()` always emits `"pnl": null`
  (`src/groktrading/replay_scorecard.py:9`, `53`). `PaperLedger.reconcile`
  is explicitly not P&L (`src/groktrading/paper.py:39-58`). `logs/trades.jsonl`
  has **no rows after 2026-09-03**. CHANGELOG session notes stop at 2026-09-03
  (flat $0 on 08-28, 09-01, 09-02).
- **Outcome:** operator-stated stretch (~8 red/flat days, Wed −$37) is **not
  reconstructible from git**. Cannot compute hit rate or expectancy. Do not
  invent Sharpe.

---

## 3) EDGE GAPS

Mechanisms a **$422 one-lot desk could use this week**. No Kelly, no 300-agent
fantasy, no vol-surface HF, no unverified overnight 10× claims.

1. **`must_trade_small` as a Continual15 clock, not a gate rewrite.** By ~11:00 PT,
   if no I2 lean, pick the best I1 that already passes executed_at ≤60s + matching
   ask + cash floor + qty=1 + BTO. Write `live_order_gate` (entry **and** exit +
   falsifier) **before** preview. Encoded `SIT2_INCOMPLETE` will still fire unless
   Bot logs an explicit I1 exception (see CHANGE). This is the only way the daily
   lot exists on a dirty tape.
2. **Pre-trade falsifier that can fire before 12:30.** Journaled losers were
   `dead_thesis` (AMZN −$28 in ~16 min) or `12:30_cash_up`. Need a written “bid ≤
   X or thesis dead → STC via `live_order_gate`” on every ticket. Not a flatten
   cron. Not encoded today.
3. **Actual-cash size band.** Use funded ~$422 (and live BP/cash snapshot) so
   default ask stays ~$0.80–$1.50; treat `PREFERRED_ONE_LOT_NOTIONAL` $200 as
   **not** the live default. Hygiene $25k math stays paper.
4. **Refuse-reason tape.** One JSONL line per Continual15 look: sit_match reason,
   `evaluate_gate` reasons, already-run underlying %, ask vs print. Until that
   exists, L1 vs L5 cannot be ranked with counts.
5. **Journal close + credit ban.** Reconcile SPCX vs Tradier; append Wed credit
   as a closed row if it filled; treat any new credit/spread as a process fail,
   not a strategy. Schwab stays read-only.

**Not gaps (do not chase):** new paid UW/LLM tiers, account-events, UW WS
subscribe protocol, Opening15 promotion, morning-flow first-print, spray,
enabling companion `emit_sit_match`.

---

## 4) KEEP / DROP / CHANGE

Only items that move expected P&L or kill a known bleed. **One CHANGE.**

### KEEP (3)

1. **`sit_match` executed_at ≤60s + C2 (no `created_at`/`timestamp` substitute) +
   matching-ask / production quote gate.** Stops stale UW re-wake and chase.
   Package: `sit_match.py`, `webhook.py:89-97`, `quote_gate.py`. Host must still
   apply the same check in `ws_tape.py` (not in tree).
2. **BTO-only payload + WS-never-orders + preview-before-submit + account-events
   disabled + companions `emit_sit_match=False`.** These are the bleeds already
   named: credits, WS→orders, spray, extra Grok wakes. Keep them off.
3. **≥20% cash floor / 80% max deploy / 12:30 new-entry cutoff / qty=1**, evaluated
   on **funded** cash, not $25k. `policy.py` + `gate.py:112-132`.

### DROP (3)

1. **Opening15 / selector_v3 / expanded UW slices as a live edge.** Paper theater;
   no broker path (`research/hygiene.py:7-8`). Does not fill Tradier.
2. **Abandoned live locks:** morning-flow first-print, tuned 0.5% skip, spray,
   undocumented 0DTE credits as default. DSR already REJECT on morning-flow
   sample (operator). Do not resurrect for “activity.”
3. **~$200 preferred notional and 12:30-flatten-as-exit as desk defaults.**
   `PREFERRED_ONE_LOT_NOTIONAL` is the wrong size on ~$422; `12:30_cash_up` exits
   are rejected policy (`policy.py:21`, `70-75`) and mixed P&L in the journal.

### CHANGE (1)

**Sit-2 becomes the I2 lean/hold bar; I1 `must_trade_small` after ~11:00 PT is an
explicit, logged exception on Grok Bot `live_order_gate` — not a silent gate
bypass, not a package edit in this PR.** All other hard gates stay. If Bot keeps
using `evaluate_gate` unchanged, `SIT2_INCOMPLETE` will keep producing sit-out
days. A later, operator-approved code PR may add a `must_trade_small` flag; do
**not** relax executed_at, matching ask, cash floor, or qty.

---

## 5) MUST-FIX-BEFORE-NEXT-LIVE-LIFT

| Check | Required? | Notes |
| --- | --- | --- |
| `live_order_gate` written **before** preview: entry thesis + exit + falsifier | **Yes** | Not in this repo; Bot process. No raw POST. |
| `executed_at` age ≤60s (`sit_match` allow) | **Yes** | Package + inbox already fail-close. |
| Tradier **production** ask matches print (matching ask) | **Yes** | `gate.py:98-100`, `quote_gate.py`. |
| qty=1, **BTO only** | **Yes** | No credit/spread default. |
| Cash/equity ≥20% after premium on **actual** book (~$422), not $25k | **Yes** | `breaches_cash_floor`. |
| Ask in ~$0.80–$1.50 unless full I1+I2 committed | **Yes** | Locked plan; override $200 preference. |
| Skip if already-run **≥0.5% open** (Tradier/underlying print) | **Yes** | Operator hard gate; **not encoded** — Bot must check. |
| Before 12:30 PT; not WS→orders | **Yes** | Encoded. |
| Journal `logs/trades.jsonl` row (`invented=false`) before next lift | **Yes** | Close or note SPCX; record Wed credit if it filled. |
| If sit-2 incomplete: only I1 `must_trade_small` after ~11:00 PT, exception on ticket | **Yes** | Else sit-out continues. |
| Account-events unit enabled | **No** | Keep disabled. |
| Schwab live / dual-fire | **No** | Read-only until green Tradier days. |
| Opening15 → live, companion `emit_sit_match`, UW WS subscribe | **No** | Excluded. |
| Morning-flow first-print, spray, credit default | **No** | Abandoned. |

Disabled/excluded features stay off.

---

## 6) 48-HOUR EXPERIMENT CARD

Fits **Continual15** (Grok Bot RTH loop; not in this tree) + **`live_order_gate`**.
Does not enable account-events, WS→orders, spray, or credits. No new paid data.

| Field | Value |
| --- | --- |
| **Name** | Continual15 I1 `must_trade_small` clearer (journaled BTO) |
| **Hypothesis** | On a dirty-tape day, if no I2 by ~11:00 PT, one I1 that already passes executed_at ≤60s + matching ask + cash floor + qty=1 + ask ∈ ~$0.80–$1.50, with a written `live_order_gate` (entry+exit+falsifier), produces ≥1 journaled RTH fill and replaces sit-out / unaudited-credit days. |
| **Metric** | (1) sit_match allow vs deny-by-reason and `evaluate_gate` reasons by 11:00 PT; (2) journaled fills with `invented=false`; (3) `realized_usd` vs no-lift / credit-bleed. Do not invent expectancy. |
| **Sample** | **2 consecutive RTH sessions**, Continual15 until 12:30 PT new-entry cutoff. |
| **Paper vs live** | **Session 1 = paper/shadow only:** run the same I1 candidate through `evaluate_gate` + `sit_match`; write refuse reasons; **no** live POST. **Session 2 = live one-lot only if** session 1 showed ≥1 I1 that failed **solely** on `sit2_incomplete` (or passed) **and** matching ask held at shadow time. Otherwise stay paper and treat as L5 (host freshness), not a selection miss. |
| **Kill criteria** | Any credit/spread; any raw POST / WS→order; any fill without exit+falsifier on the ticket; ask > $1.50 unless full I2; cash after premium < 20%; two session-1 days with **zero** sit_match allows (stop lifting — patch host `executed_at` first). |
| **Falsifier** | If session 1 has **zero** sit_match-fresh I1s, the hypothesis is false for Grok selection: the bottleneck is Helsinki emit / dirty tape / host `ws_tape.py`, not missing `must_trade_small`. If session 2 fills and the falsifier is not honored (hold-to-cutoff with no written exit), kill — that is L3 repeating, not a win. |

Smallest diff: **process + journal**, not a gate/deploy PR.

---

## invented=false checklist

| Claim | Verified | Assumed / operator-stated |
| --- | --- | --- |
| HEAD `68d4ce9` = PR #29 C2/C4/C5 | `git rev-parse` after `git fetch origin main` | — |
| No `live_order_gate` / Continual15 / `must_trade_small` / I1/I2 symbols in tree | repo-wide search | Bot implements them off-tree |
| `evaluate_gate` sit&lt;2 hard reject; BTO-only; preview-only live stub | `gate.py`, `models.py`, `executor.py`, tests | Bot may or may not call them |
| `sit_match` executed_at-only, default 60s; C2 tests | `sit_match.py`, `test_sit_match.py` | Host `ws_tape.py` applies the same check |
| C4 `public_url` strips token/userinfo; C5 Box deny symlink/case/suffix | `tests/test_uw_ws.py`, `box_rotate.py` | Not a P&L lever this week |
| Account-events example unit not auto-enabled; companions `emit_sit_match=False` | unit file, companion headers, README | Host has not enabled them |
| Journal rows AMZN −28, DRAM −3, NVDA −31, AAPL +101, SPCX open 0.86 | `logs/trades.jsonl` | SPCX terminal P&L unknown |
| Sit-1 SPCX fill | CHANGELOG `[2026-09-03]` | — |
| ~$422 equity, account id, ~8 red/flat days, Wed −$37 SPY credit, 0 clean lifts, locked daily-lot plan | — | **Operator brief only** (credit not in journal) |
| Already-run ≥0.5% open | **Not in code** | Operator hard gate |
| Helsinki still on 2026-09-05 map (`/opt/trading-desk`, no this commit) | `docs/OBSERVED_DEPLOYMENT.md` | Host may have moved since; not re-SSH’d |
| Replay `pnl` always null | `replay_scorecard.py` | — |
| No orders placed, no credentials touched, no services enabled | this PR is docs-only | — |

**Not verified:** live Helsinki unit state, Tradier balances, Box archive contents,
Grok Bot `live_order_gate` source, host `ws_tape.py` freshness patch, Wed credit
fill details, SPCX exit/expiry fill.
