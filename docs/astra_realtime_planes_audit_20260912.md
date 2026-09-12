# Astra-style audit — three-plane realtime desk (2026-09-12)

Read-only process audit of the hunt architecture after Friday’s book and
the weekend sit_match mute. **Process vs outcome are not the same
verdict.** Do not invent prices. Take-gain stays **TRIAL n=1**.
**Merge ≠ Helsinki restart.**

**Scope:** git `main` at `e9ecd50` (PR #36) plus this planes PR, plus
operator-stated Friday / host facts below. Host `ws_tape.py`, Grok Bot
routines, and whether `shortlist.json` exists on disk are **not** in this
tree unless noted.

Design SoT: [REALTIME_PLANES.md](REALTIME_PLANES.md).

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
| Take-gain | **TRIAL n=1** — do not lock |

**Repo (verified in this tree / GitHub):**

| Item | Fact |
| --- | --- |
| PR #34 | Webhook throttle: honest `print_age_sec`, `emitted_at`, OCC-only debounce, mute, package `MIN_INTERVAL` default 60 |
| PR #35 | `tools/live_order_gate` STC / named exits (dry-run; never POSTs) |
| PR #36 | README Continual15 as live hunt; Opening15 research-only |
| Package `SIT_MATCH_MAX_AGE_SEC` | **60** (I1 + inbox + ranker print clock) |
| Package `SIT_MATCH_MIN_INTERVAL_SEC` | **60** |

**Host (operator-stated ops facts — not a deploy claim for this commit):**

| Item | Fact |
| --- | --- |
| `sit_match` | Weekend-muted |
| `SIT_MATCH_MIN_INTERVAL_SEC` | **300** |
| `SIT_MATCH_MAX_AGE_SEC` | **60** — do not raise |
| Finnhub | Restarted |
| Shortlist timer | **Not** claimed live. This PR adds the package + example units only |

**Discarded hypotheses**

- “Raise consume age to 300 so Mon webhooks pass” — that admits stale
  prints. I1 60s stays.
- “`live_tape.json` has a documented schema in git” — it does not. Host
  tape is not in this tree. Ranker treats unknown shapes as empty.
- “UW `premium` is the cheap-band price” — that field is dollar notional
  (companion `min_premium=10000`). Band is per-share ask/print
  $0.80–$1.50 (already documented I1 cheap band).
- “Merge restarts Helsinki / unmutes / enables the timer” — it does not.
- “300s is the realtime design” — it is a Cursor wake bandage.

---

## A) What to keep from Friday fixes

1. **`print_age_sec` is not a clock (PR #34).** Overwrite from
   `executed_at` at POST; `emitted_at` + hop stamps; contradict /
   stale-at-POST fail closed. Inbox + I1 already refused old
   `executed_at`. **Keep** on any rare `sit_match` alert path.
2. **OCC-only debounce + min interval + mute.** The firehose (~20+/min
   POSTs → Cursor p50 ~16m) was process risk. **Keep the mute lever.**
   Host 300s interval is a valid bandage on that optional path. It is
   **not** hunt cadence.
3. **Do not raise `SIT_MATCH_MAX_AGE_SEC`.** 60s is print freshness (I1).
   Friday’s “fresh” payloads were lies against minutes-old prints.
4. **STC via `live_order_gate` (PR #35).** Friday’s WIN required
   `sell_to_close`. Keep BTO fail-closed on entry; named-exit STC/BTC;
   skip cutoff + cash debit **on exits only**. Package never POSTs.
5. **`CRON_TZ=America/New_York` on trading routines.** 13:00 Toronto
   close mid-RTH was a real clock bug. Keep ET hours for open /
   Continual15 / close / AH **on the host**.
6. **Open stand-down 09:30–09:45 ET then hunt.** Permanent. Do not lift
   at 09:00 ET.
7. **Continual15 as the live hunt (PR #36 README).** Opening15 stays
   paper/research. The planes design **keeps** this and gives it a
   shortlist to pull instead of a sit_match firehose.
8. **Take-gain TRIAL n=1.** Process PASS / Outcome WIN on one name is
   not expectancy. **Do not lock.**

---

## B) What is still fragile into Monday

1. **300s producer ∩ 60s consume is still near-empty.** If Monday waits
   on `sit_match` wakes, the desk sits. Host is weekend-muted anyway.
   Hunt must be Continual15 **before** shortlist is live on the host.
2. **Shortlist is not on the host yet.** This PR ships the package,
   schema, tests, and example timer. `install_helsinki.sh` does not
   enable it. Until `ranked_at` is actually ≤30s old in RTH, plane 2 is
   paper.
3. **`ws_tape.py` / mute file / interval remain host-owned.** Merge ≠
   restart. Repo interval default is still 60; host is 300. Drift.
4. **`live_tape.json` shape unknown in git.** Ranker will not invent
   rows. If the operator points `--tape` at a document this helper does
   not understand, the shortlist is empty (fail closed / idle), not a
   guessed OCC.
5. **Already-run / in_position only when detectable.** Ranker skips
   META/NET/MU/AMD, SPCX, INTC puts, and session lists **if provided**.
   If Continual15 does not pass those lists, plane 2 cannot see them.
   Gate + Tradier REST remain the last word.
6. **Account-events still off.** After STC, `in_position` can lag.
   Friday-style flatten honesty is Bot/Tradier REST.
7. **Take-gain n=1.** Do not size up. Journal hole: Friday QQQ is still
   not in `logs/trades.jsonl`.
8. **Timezone split.** Host routines = NY. Encoded cutoff + most docs =
   PT. A 12:30 job with the wrong `CRON_TZ` is live-risk. See F.
9. **Finnhub restarted** (ops). That does not merge the Finnhub tape
   into `live_tape.json`. Finnhub ≠ option NBBO.

---

## C) What to refuse to ship

- Raise `SIT_MATCH_MAX_AGE_SEC` (inbox, I1, or ranker) to 300 — or to
  any producer interval — so sit_match POSTs “pass.”
- Treat `SIT_MATCH_MIN_INTERVAL_SEC=300` as the realtime design or the
  trading latency target.
- Turn `sit_match` POSTs back into the hunt bus (`emit_sit_match=True`
  on companions / ranker; `SIT_MATCH_WEBHOOK=1` as the selection loop).
- Lock take-gain (arm +40% / 50% ratchet) after n=1.
- Credits / STO / multi-leg / `sell_to_open` on entry.
- Flatten-at-16:00 as an exit machine.
- Opening15 → live.
- Enable account-events or the shortlist timer **from this merge**.
- Using inbound `print_age_sec` or UW dollar `premium` as the cheap-band
  clock.
- A live POST path inside this package.
- Claiming Helsinki already writes `/opt/trading-desk/state/shortlist.json`.
- Auto-deploy / SSH restart from a cloud agent.

**Remute** if anyone re-enables sit_match as a firehose (interval drifted
back to 15–60 with a hot tape): `SIT_MATCH_WEBHOOK=0` and/or
`sit_match_webhook_muted` **before** chasing I1. Hunt on Continual15.

**Reverse** any host cron still on Toronto local 13:00 / 16:00-as-PT, or
any “open at 09:00 ET lift” that ignores the 09:30–09:45 stand-down.

---

## D) Is shortlist + Continual15 correct vs 300s sit_match?

**Yes.** 300s sit_match is the wrong layer.

| Design | What it rates | Latency vs I1 60s | LLM wake |
| --- | --- | --- | --- |
| sit_match POST every 300s | Whole-tape firehose, then Cursor | Almost never a print still ≤60s old | Per lucky webhook (or a queued pile) |
| Thin ranker every 5–15s | ≤1–3 OCCs that already pass I1 + band + skips | Print age is still 60s (or 15–30 tighten) | None |
| Continual15 pull | Frozen facts + fresh Tradier quotes | Independent of webhook interval | Timer, not per-print |

300s is **enough to stop the firehose**. It is **not enough to hunt**.
That verdict from the Friday audit still holds. The missing piece was a
plane that rate-limits **candidates** without muting the tape and without
widening consume age.

Shortlist + Continual15 is that plane. `SIT_MATCH_WEBHOOK` default **off**
for hunt; optional rare alert only. `MIN_INTERVAL` stays a bandage on
that optional path. Do not “fix” emptiness by widening `MAX_AGE`.

Until the ranker file is live on the host, Monday = Continual15-only
(same instruction as Friday audit D). The shortlist is an additive
sensor, not a gate that blocks Continual15 from running.

---

## E) Fail-closed gaps (stale shortlist, empty shortlist, in_position race)

| Gap | Encoded now? | Residual |
| --- | --- | --- |
| **Stale shortlist** | `evaluate_shortlist_document` refuses `ranked_at` older than `SHORTLIST_STALE_SEC` (default 30s / `2 × cadence`). Reason `shortlist_stale`. Candidates are dropped | Bot must call the helper. A Bot that ignores `ranked_at` and hunts the last OCC names anyway reopens Friday’s lying-fresh class of bug. Do not raise this limit to 300s |
| **Empty shortlist** | Valid write (`empty_reason` `no_input` / `no_fresh_prints` / `all_filtered`). Consume `shortlist_empty` → no hunt from this file | Correct idle. Danger is treating empty as “load the whole tape” or waking Grok anyway |
| **Race with `in_position`** | Ranker skips held OCCs/underlyings **when the lists are passed in**. Consume drops them again (`shortlist_in_position_cleared` if none remain) | Lists are optional inputs. Account-events is still off. **Continual15 must re-read Tradier positions before BTO.** Package `evaluate_gate` `IN_POSITION` is still the last lock — only if the Bot calls it |
| Missing / bad schema | `shortlist_schema` | Fail closed. Do not parse a random tape file as a shortlist |
| Invalid max-age env | CLI exit 2; does not overwrite | Good. A running timer that starts failing closed leaves the previous file to go stale — consume then refuses. That is the intended dead-ranker behavior |
| Undetectable already-run | No skip invented | Bot/session facts must be wired or the hard-coded META/NET/MU/AMD + SPCX + INTC-put list is all plane 2 sees |

**Do not** paper over these by POSTing sit_match again or by widening
print age.

---

## F) Timezone residuals

| Clock | Where | Risk into Monday |
| --- | --- | --- |
| 12:30 **PT** new-entry cutoff | `timeutil.py`, `policy.py`, `evaluate_gate`, `live_order_gate` | Authoritative for **new BTO**. 12:30 PT = 15:30 ET. Continual15 already stops hunt at 15:00 ET |
| Host trading routines | `CRON_TZ=America/New_York` 09:00 / 9–15 / 16:00 / 16:06 | Keep. Do not copy repo example crons (`America/Los_Angeles`) onto those routines |
| Ranker timer | `OnUnitActiveSec=10s` — no timezone | Fine. RTH vs weekend is a **Bot** mute. Ranker may keep writing empty/stale-eligible files on the weekend; Continual15 must not hunt them |
| Repo / installer docs | `CRON_TZ=America/Los_Angeles` in DEPLOY / REBUILD / `hot-retain.cron` | **Docs ≠ host.** A **12:30** job with `CRON_TZ=America/New_York` fires at 12:30 ET = 09:30 PT (open), not cutoff |
| `RTH_CLOSE_HINT_PT = 13:00` | `timeutil.py` | 13:00 PT = 16:00 ET. Friday bug was **13:00 America/Toronto** = 13:00 ET mid-RTH |
| CHANGELOG / journal “PT” | docs | Session labels stay PT. Routines stay ET. Write both on cards |
| Open stand-down | Bot process | 09:00 ET routine ≠ hunt. First lift window 09:45 ET |

**Monday refuse:** any new cron, Grok routine, close card, or ranker
enable that does not state `CRON_TZ` and city when it is calendar-based.
Default host TZ (Toronto) is how Friday’s close fired mid-RTH.

The shortlist timer is interval-based (10s), not calendar-based. The
**unmute / Continual15 start** is calendar-based and must stay NY.

---

## invented=false checklist

| Claim | Verified | Operator-stated |
| --- | --- | --- |
| PR #34 freshness + mute + interval 60 | git + `sit_match.py` | Host producer gate already applied |
| PR #35 `live_order_gate` STC | `tools/live_order_gate` | Box hot-patch preceded git |
| PR #36 README Continual15 | `e9ecd50` | — |
| I1 / package `MAX_AGE` 60; do not raise | `sit_match.py`, this ranker | Host consume 60 |
| Package `MIN_INTERVAL` 60 vs host 300 | README + sit_match default | Host Mon prep 300; weekend-muted |
| Finnhub restarted | — | Yes |
| Friday QQQ 1.06→1.45 / +$39 / 421.74→460.56 | — | **Yes** (not journaled here) |
| Take-gain TRIAL n=1 | Friday audit + README | Yes |
| `live_tape.json` schema in this repo | **Absent** (by search) | Host-owned loose JSON |
| Shortlist live on Helsinki | **No** — examples only | Not claimed |
| Merge restarts Helsinki | Installer + docs say no | Operator SSH only |

**Not verified:** live unit state after this merge, Tradier balances, Box
archive, host crontab, Bot import of `evaluate_shortlist_document`.
