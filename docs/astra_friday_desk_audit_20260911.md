# Astra-style desk audit — Fri 2026-09-11 → Mon 2026-09-14

Read-only audit of what got Darryl’s Tradier one-lot desk to Friday’s
flat, plus the in-repo STC port. **Process vs outcome are not the same
verdict.** Do not invent prices. Take-gain stays **TRIAL n=1**.

**Scope:** git `main` at `88c0c16` (PR #34) plus operator-stated Friday
facts below. Host `ws_tape.py`, Grok Bot routines, and the box hot-patch
are **not** in this tree unless noted.

---

## Facts used (`invented=false`)

**Outcome (operator-stated Friday book — not in `logs/trades.jsonl`):**

| Field | Value |
| --- | --- |
| Session | 2026-09-11 |
| Open equity | $421.74 |
| Close equity (flat) | $460.56 |
| Sole live lot | `QQQ260911P00717000` |
| Entry | BTO 1.06 |
| Exit | STC 1.45 |
| Tradier `close_pl` | +$39 |

**Process (operator-stated take-gain TRIAL, Darryl):** arm +40% on Tradier
**bid**; ratchet protect = entry + 50% of (peak_bid − entry). Peak bid
**1.88** → protect **1.47**; fill **1.45**. Trade Reviewer: **Process PASS /
Outcome WIN**. Do **not** lock the recipe.

**Webhook (repo + operator):** Cursor wake backlog from too many
`sit_match` POSTs (15–35m lag). `print_age_sec` frozen at emit looked
fresh; `executed_at` at consume was old. Producer already had
`SIT_MATCH_MAX_AGE_SEC=60` stale-at-POST. Mitigations: mute, `MIN_INTERVAL`
60 then 300, PR #34. Mon prep: unmuted, interval **300s**, mute cleared;
**consumer still refuses >60s**.

**Clocks (operator):** close card wrongly fired at **13:00 America/Toronto**
(mid-RTH). Fixed: trading routines `CRON_TZ=America/New_York` (open 09:00,
Continual15 9–15, close 16:00, AH 16:06). Open stand-down **permanent**:
hunt only after 09:30–09:45 ET.

**Repo (verified in this tree):** PR #34 (`88c0c16`, merged 2026-09-11)
overwrites `print_age_sec` from `executed_at`, stamps `emitted_at`,
fail-closes `sit_match_print_age_contradicts` / `sit_match_stale_at_post`,
OCC-only debounce, default `SIT_MATCH_MIN_INTERVAL_SEC=60`, mute file.
`tools/live_order_gate` was **absent**; `Candidate.side` /
`OrderPayload.side` remain `Literal["buy_to_open"]`. Encoded cutoff is
**12:30 America/Los_Angeles**. Example host cron docs still say
`CRON_TZ=America/Los_Angeles`. Inbox `WebhookInbox.claim` still refuses
stale `executed_at` (default 60s) and does **not** apply mute/interval.

---

## Process vs outcome

| Surface | Verdict | Why |
| --- | --- | --- |
| Process (Friday lot) | **PASS** (Reviewer) | Written take-gain + STC happened; not a 12:30 flatten. |
| Outcome (Friday lot) | **WIN** n=1 | BTO 1.06 → STC 1.45; book $421.74 → $460.56; `close_pl` +$39. |
| Process (webhook) | **PARTIAL** | Producer freshness was already correct; the bleed was wake queue + lying `print_age_sec`. PR #34 + mute + 300s are mitigations, not a new edge. |
| Process (clocks) | **FIXED on host; residual in repo** | Toronto 13:00 close was a real bug. Repo/docs still PT. |
| Take-gain | **TRIAL n=1** | Do not lock. Protect 1.47 vs fill 1.45 is one path, not expectancy. |

---

## A) What fixed a real bug (keep)

1. **`print_age_sec` is not a clock (PR #34).** Overwrite from `executed_at`
   at POST; `emitted_at` + hop stamps; contradict / stale-at-POST fail closed.
   That is the actual freshness bug. Inbox + I1 already refused old
   `executed_at` — the desk could not trade those wakes. **Keep.**
2. **OCC-only debounce + min interval + mute.** The firehose (~20+/min
   POSTs → Cursor p50 ~16m) was process risk, not a missing alpha. Mute
   cleared the queue. Interval (60, then host 300) stops a re-queue.
   **Keep the mute lever.** Default in-repo interval is still 60.
3. **STC exit on the box (now ported here).** Friday’s WIN required
   `sell_to_close`. Entry-only `assert_submit_policy` could not close.
   Keep BTO fail-closed; keep named-exit STC/BTC; skip cutoff + cash debit
   **on exits only**.
4. **`CRON_TZ=America/New_York` on trading routines.** 13:00 Toronto close
   mid-RTH was a real clock bug. Keep ET hours for open / Continual15 /
   close / AH **on the host**.
5. **Open stand-down 09:30–09:45 ET then hunt.** Permanent process. Do not
   encode a 09:00 “must lift” from a Toronto/PT cron.
6. **Consumer `executed_at` ≤60s.** Do not raise it to match a 300s
   producer interval. That would admit stale prints.

---

## B) What is still fragile into Monday

1. **`sit_match` interval 300s vs consume 60s.** A print that is 61s old
   at POST is refused. 300s between POSTs means most hunts will **not**
   arrive as a fresh webhook. Hunt is already Continual15 (9–15 ET). If
   Monday relies on sit_match wakes, the desk sits. See D.
2. **Mute / interval / `ws_tape.py` are host-owned.** Merge ≠ restart.
   Repo default interval is **60**, host Mon prep is **300**. Drift.
3. **Take-gain is TRIAL n=1.** Protect 1.47 vs fill 1.45: one tick through
   the ratchet is not a lock. No second name. Do not size up.
4. **`live_order_gate` was box-only.** This PR puts the policy in git.
   The Bot must actually **import this path** (or stay in sync). A stale
   box copy can diverge again.
5. **Package FSM is still BTO-only.** `evaluate_gate` / `OrderMachine` /
   `OrderPayload.side` cannot STC. If someone routes the Friday-style
   close through `Executor.maybe_submit`, it will not emit STC. Bot must
   keep using `tools/live_order_gate` for closes.
6. **Journal hole.** Friday QQQ is not in `logs/trades.jsonl` (no order
   ids in this brief). Process PASS is Reviewer-stated, not reconstructible
   from git. Same class of hole as Wed credit / SPCX.
7. **Timezone split.** Host routines = NY. Encoded cutoff + most docs = PT
   (`12:30` PT = `15:30` ET). Continual15 ends **15:00 ET** (before cutoff).
   A 12:30 job with the wrong `CRON_TZ` is a live-risk. See F.
8. **Account-events still off; position truth is Bot/Tradier REST.** After
   STC, `in_position` can lag if the Bot does not re-read positions before
   the next BTO.

---

## C) What to refuse to ship / remute / reverse (before Mon open)

**Refuse to ship**

- Lock take-gain (arm +40% / 50% ratchet) as a house rule after n=1.
- Raise `SIT_MATCH_MAX_AGE_SEC` (inbox or I1) to 300 so 300s POSTs “pass.”
- Credits / STO / multi-leg / `sell_to_open` on entry.
- Flatten-at-16:00 as an exit machine (that is the old `12:30_cash_up`
  bug in ET clothes).
- Opening15 → live, companion `emit_sit_match=True`, account-events on,
  Schwab live.
- Using inbound `print_age_sec` as the freshness clock.
- A live POST path inside this package (CLI stays dry-run).
- Rewriting `OrderPayload.side` to include credit types.

**Remute**

- If sit_match POSTs again outrun Cursor wakes (interval drifted back to
  15–60 with a hot tape), remute
  (`SIT_MATCH_WEBHOOK=0` and/or `sit_match_webhook_muted`) **before**
  chasing I1. Hunt on Continual15.

**Reverse**

- Any host cron still on Toronto local 13:00 / 16:00-as-PT.
- Any “open at 09:00 ET lift” that ignores the 09:30–09:45 stand-down.

---

## D) Is 300s sit_match enough, or Continual15-only hunt?

**300s is enough to stop the firehose. It is not enough to hunt.**

Producer interval 300s + consumer/I1 `executed_at` ≤60s is a near-empty
intersection: a webhook that waits 300s after the last POST will almost
always be stale at consume unless a brand-new print lands in the same
minute the interval opens. That is by design of the 60s gate (keep it).

**Monday hunt = Continual15-only** (09:45–15:00 ET after stand-down).
Reserve webhooks for **`in_position` / fills / working-order / flatten-risk
notices** — events that are not UW print-age gated. Keep `sit_match`
muted-capable; if left on at 300s it is a rare “maybe a fresh print”
nudge, not the selection loop.

Do not “fix” this by widening consume age.

---

## E) Fail-closed gaps in the STC exit path

Ported here (`tools/live_order_gate`). Residual gaps:

| Gap | Encoded now? | Residual |
| --- | --- | --- |
| Re-entry | Exit thesis cannot `submit`; `already_closed` on parent/signal; BTO still cutoff + cash + credit ban | Bot must pass `closed_signal_ids` and re-read Tradier positions. Package `evaluate_gate` still treats `in_position` as an **entry** block only if the Bot calls it. |
| Thesis TTL | Entry: same PT session + 8h; missing/naive `written_at` fail-closed. Exits skip entry TTL (overnight longs allowed) | Exit thesis has no max age. A stale take-gain ticket could still STC days later if the Bot feeds it. Prefer rewrite-at-trigger. |
| Tag alphanumeric | Fail-closed `tag_not_alphanumeric` | Package `OrderMachine` still sets `tag=signal_id` and allows hyphens (`sig-1`). Do not mix the two taggers. |
| Credit ban substring | **Exact** side/strategy only. Thesis prose mentioning “credit” / “sell” does **not** refuse STC | Do not add a text scan. A strategy named `take_gain_credit_exit` is not in the allow-list (must be an `EXIT_STRATEGIES` exact name). |
| STC without thesis | `thesis_required` | Keep. |
| Cutoff / cash on exit | Skipped | Correct. Do not “simplify” by running entry submit on close. |
| BTC | Allowed only as an exit side (short-cover). Desk is long-premium; BTC should stay rare | A BTC entry (buy-to-close a short that should not exist) still needs a parent thesis. |
| Package FSM | Not wired | `close_with_audit` must stay the close path. |

---

## F) Timezone residual risks

| Clock | Where | Risk into Monday |
| --- | --- | --- |
| 12:30 **PT** new-entry cutoff | `timeutil.py`, `policy.py`, `evaluate_gate` | Authoritative for **new BTO**. 12:30 PT = 15:30 ET. Continual15 already stops hunt at 15:00 ET — conservative vs cutoff. |
| Host trading routines | `CRON_TZ=America/New_York` 09:00 / 9–15 / 16:00 / 16:06 | Keep. Do not copy repo example crons (`America/Los_Angeles`, `* 6-12`, `15 19`) onto those routines. |
| Repo / installer docs | `CRON_TZ=America/Los_Angeles` in DEPLOY / REBUILD / `hot-retain.cron` / CHANGELOG | **Docs ≠ host.** A 16:00 PT retain is 19:00 ET (fine, after close). A **12:30** job with `CRON_TZ=America/New_York` would fire at **12:30 ET = 09:30 PT** (open), not cutoff. |
| `RTH_CLOSE_HINT_PT = 13:00` | `timeutil.py` | 13:00 PT = 16:00 ET (real close). The Friday bug was **13:00 America/Toronto** = 13:00 ET mid-RTH. Do not schedule “close” at 13:00 without `CRON_TZ=America/Los_Angeles`. |
| CHANGELOG / journal “PT” | docs | Session labels stay PT. Routines stay ET. Write both on cards. |
| Open stand-down | Bot process | 09:00 ET routine ≠ hunt. First lift window 09:45 ET. |

**Monday refuse:** any new cron, Grok routine, or “close card” that does not
state `CRON_TZ` and city. Default host TZ (Toronto) is how Friday’s close
fired mid-RTH.

---

## invented=false checklist

| Claim | Verified | Operator-stated |
| --- | --- | --- |
| HEAD / PR #34 freshness + mute + interval 60 | git + `sit_match.py` + WEBSOCKETS | Host already applied producer gate |
| No `live_order_gate` on `main` before this PR | repo search | Box hot-patch existed |
| BTO-only `Candidate` / `OrderPayload` | `models.py` | Bot submit was BTO-only until hot-patch |
| Encoded cutoff 12:30 PT; docs `CRON_TZ=America/Los_Angeles` | `timeutil.py`, DEPLOY, REBUILD | Host routines now NY |
| Inbox consume still ≤60s; mute/interval producer-only | `webhook.py` | Mon unmute + 300s interval |
| Friday QQQ BTO 1.06 / STC 1.45 / +$39 / book 421.74→460.56 | — | **Yes** (not journaled here; no order ids) |
| Peak bid 1.88 → protect 1.47 | — | Take-gain TRIAL |
| Reviewer Process PASS / Outcome WIN | — | Yes |
| Wake 15–35m / 20+/min POSTs / HTTP 0.5–0.7s | PR #34 body + CHANGELOG | Yes |
| Toronto 13:00 close; NY routines; 09:30–09:45 stand-down | — | Yes |

**Not verified:** live Helsinki unit state, Tradier balances, Box archive,
host crontab contents, Bot import of this module after merge.
