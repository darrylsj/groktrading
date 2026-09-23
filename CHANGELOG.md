# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Package version is `0.1.0` in `pyproject.toml`. Dated sections are **America/Los_Angeles** operator and session history. Do **not** invent extra dates, prices, fills, or P&L. Live fills belong in [logs/trades.jsonl](logs/trades.jsonl). See [docs/LOGS.md](docs/LOGS.md).

## [Unreleased]

### Fixed

- Helsinki shortlist ranker no longer drops the whole print pool as
  `missing_executed_at`. The 200-row ledger window now keeps rows that
  stored UW `executed_at` (ISO or websocket epoch milliseconds on that
  field). `LIVE_TAPE_PATH` is read even when `FLOW_LEDGER_PATH` is set,
  and a tape list that carries `executed_at` is preferred over an earlier
  clock-less list. `created_at` / `timestamp` are still not substitutes.
  `sit_match` stays off. No orders.

### Added

- Aria source-audit yellows from **2026-09-21** (`docs/ARIA_SOURCE_AUDIT_20260921.md`), observability and docs only. Live defaults stay fail-closed (`live_explicitly_enabled` remains false; no live-order path change).
  - `TradierClient` logs one line at init: the REST base from `rest_base(env)` (the host the client already uses) and the account source (`TRADIER_ACCOUNT_ID` when that env value is the constructed id, otherwise `constructor`) plus an `acct-` sha256 alias. Tokens and raw account ids are not logged.
  - [docs/SAFETY.md](docs/SAFETY.md) records `live_explicitly_enabled` provenance: default false, no in-repo env/config sets it true, WebSocket events cannot trigger live, and `evaluate_gate` plus `OrderMachine.final_gate` both re-check.
  - [scripts/deployed_head_drift.py](scripts/deployed_head_drift.py) and [docs/DEPLOYED_HEAD_DRIFT.md](docs/DEPLOYED_HEAD_DRIFT.md): local `git rev-parse HEAD` versus an operator-supplied deployed SHA. No SSH and no deploy.

### Changed

- Public docs aligned to **operator-deployed desk as of 2026-09-17 PT**
  (README live card, [docs/OBSERVED_DEPLOYMENT.md](docs/OBSERVED_DEPLOYMENT.md),
  current-policy pages). **Not** a claim this commit is running on
  Helsinki. **No SSH. No secrets. No invented fills/P&L.**
  Current card: cash/equity **≥20%** / max deploy 80%; overnight longs
  **ALLOWED**; **12:30 PT = new-entry cutoff only** (not flatten /
  not cash-flat-by-close); Continual15 hunt on
  `CRON_TZ=America/New_York */5 9-15 * * 1-5` (5-minute floor, not a
  literal 15-minute-only loop); opportunity / `sit_match` /
  `shortlist_opportunity` **KEEP_PAUSED**; ask band **HARD ±$0.02**
  (`ask_drift`); I1 **SOFT 180s** (hard stale only >180; package
  `SIT_MATCH_MAX_AGE_SEC` default still 60s until copied); live orders
  **`live_order_gate` only**; take-gain **TRIAL** arm ×**1.25** /
  protect 50% of peak gain (Darryl 2026-09-17 after operator-stated
  INTC miss — **not** ×1.40); live STO **still refused** pending
  **Fri 2026-09-19 I4 review** (Wed 2026-09-16 did not unlock); hard
  skips **META/NET/MU/AMD**; **UW MCP DEFERRED** (box-only research if
  ever; never Helsinki; never Continual15 submit); Continual15 Friday+
  shadow tags **SCORE-ONLY**
  (`stale_event>30s`, `stale_quote>2s`, `duplicate_event`,
  `spread_or_size`, `multileg_unresolved`, `catalyst_unknown`); UW GUI
  Flow Alerts / Screener gated delayed, 0DTE / Interval / Tide / dark
  pool / multi-leg / news / calendars live on plan. Older ≥50% cash,
  flatten-by-close, opportunity-as-hunt, take-gain ×1.40, UW-MCP-for-live,
  and STO-unlocked-after-Wed-9/16 claims are marked historical.

### Added

- **2026-09-21 product-use landing:** [docs/IDEA_PRODUCT_USE.md](docs/IDEA_PRODUCT_USE.md)
  (Options AI Compare metrics and Expected Move = 92.5% ATM straddle, not a
  probability; Trade Machine Active-only, alerts/ProScan),
  [docs/UNDERUSE_GAP_20260921.md](docs/UNDERUSE_GAP_20260921.md), and the
  planning-only [$25k stack consult](docs/STACK_25K_YOLO_CONSULT_20260921.md).
  README Idea Funnel B states the sandbox paper prove-it, the Friday
  2026-09-25 PT prove/kill, and a Monday 2026-09-28 hard cancel if unproven.
  No profitability claim.
- `tools/tradier_paper/`: sandbox one-lots at `https://sandbox.tradier.com/v1`
  only. Credentials stay in host env. Default dry-run; `--submit` is required
  to POST. Near Active is not lifted. Options AI needs DOM max risk, max gain,
  and PoP. Buy-to-open puts on IWM/SPY/QQQ stay refused.
- `tools/idea_shadow_rank/`: shadow-only open slate. Active outranks Near
  Active. Missing Compare metrics stay null.
- Trade Machine normalize lists Active first and marks empty Near Active legs
  as expected. Options AI DOM validation copies max risk / max gain / PoP when
  present and does not invent them from chain data.
- **2026-09-21 Astra fail-closed on the idea path:** `redact_har.py` and
  `cdp_har_capture.js` scrub API-key headers, Referer/Location/redirectURL,
  form bodies, `postData.params`, page titles, and base64 utf-8 bodies.
  Unsupported encodings fail closed. Raw HAR names are refused, and no
  `.har` is tracked.
- Options AI HAR→ideas is disabled. DOM QuickStrike / Strategy Builder
  boards only. Chain/quote XHR is not mapped. ClickOptions is rejected.
- Trade Machine accepts only host + GET + exact action + HTTP 200, uses
  the latest response, stamps source observation time, and refuses the
  fixed default HAR plus stale captures. HTTP 401 is not AUTHENTICATED.
  Open_ legs from `attach_live_option_quotes` are kept; closing marks are
  not. `idea_card` mapping carries provenance. `--source both` merges one
  board per product into the shadow pointer only after both succeed.
- Paper one-lot stub (`tools/idea_board_scrape/paper_lift.py`) is
  `https://sandbox.tradier.com/v1` only and does not submit. Shadow
  metadata is not a live-order boundary.
- **2026-09-21 desk sync** (Helsinki / Grok Bot box → this repo):
  - `tools/idea_board_scrape/`: HAR capture helper, `redact_har.py`, and
    `get_ideas.py` building `idea_board.v0_1` for Trade Machine and
    Options AI. Shadow/paper only; does not submit.
  - `tools/shared_intel/`: append closed trades to the Helsinki
    shared-intel ledger (`SHARED_INTEL_LOCAL_TRADES` for offline use).
    Live account id is not in git.
  - `tools/live_order_gate`: `refuse_long_put_on_broad_etf` at BTO submit
    for IWM/SPY/QQQ puts, and `emit_shared_intel_close` on an allowed
    flatten (dry-run unless explicitly appended).
  - Idea Funnel B + idea_card v0.1 docs
    ([docs/IDEA_FUNNEL_B.md](docs/IDEA_FUNNEL_B.md),
    [docs/IDEA_CARD_V0_1.md](docs/IDEA_CARD_V0_1.md)). UW idea-card
    normalizer and schema file remain out of tree.
  - Flow-alerts and tide companions skip HTTP outside RTH
    (`FLOW_ALERTS_RTH_ONLY` / `TIDE_RTH_ONLY`, default on).
- Helsinki **zero-LLM weekday RTH live-board refresh** (2026-09-15)
  [`scripts/live_board_refresh.py`](scripts/live_board_refresh.py) +
  `trading-desk-live-board-refresh.service` / `.timer`. Reads host
  `live_tape.json` / `finnhub_tape.json` / `shortlist.json` and an
  optional local refuse JSONL. Writes
  `/opt/trading-desk/state/live_board/{index.html,live.json}` (book,
  open orders if known, shortlist, `ws_stats`, funnel). Deploys to
  Vercel project `trading-desk-live-board` only when
  `/etc/trading-desk/vercel.env` has `VERCEL_TOKEN` (missing token:
  local write, exit 0). **No LLM. No Cursor / Grok wake.** `sit_match`
  stays OFF. Opportunity webhook stays paused. Continual15 still writes
  pack evidence cards separately; board may lag refuse ledger until that
  file is on the host. Operator-wired only — installer does not enable
  the timer. Doc: [docs/LIVE_BOARD_REFRESH.md](docs/LIVE_BOARD_REFRESH.md).

### Added

- Observational **desk live board** builder (2026-09-15)
  [`dashboard/`](dashboard/) so GitHub has the pack board that was a
  404 here. Opportunity-process funnel from
  `uw_opportunity_refuses.jsonl` (refuse reasons, last evidence OCCs,
  optional shortlist + shadow-summary hooks). Optional READ-ONLY
  `ws_stats` from Helsinki *health* files (`finnhub_tape.json`
  connection/freshness/symbols; `live_tape` `flow_n`/`flow_http`/
  `errors`/`candidates`). **No new WebSocket subscriptions. sit_match
  stays OFF. No `shortlist_opportunity` resume.** Static `board.json` +
  `index.html` for sibling [`darrylsj/trading-desk-live-board`](https://github.com/darrylsj/trading-desk-live-board)
  (Vercel). CI fixtures/tests prove funnel + `ws_stats` schema without
  live Helsinki. Never invents prices/P&L/OCCs. Does **not** change
  `live_order_gate`. Doc: [docs/DASHBOARD.md](docs/DASHBOARD.md).

### Added

- Observational **shadow bets** RSI ledger (2026-09-14)
  [`tools/shadow_bets`](tools/shadow_bets) (ported from the Trading Desk
  pack at `/home/box/agent-data/projects/trading-desk/tools/shadow_bets/`).
  Refuse ledger → Tradier-cited shadow outcomes. CLI: `run-session
  --session YYYY-MM-DD`, `open-from-refuses`, `mark-session`,
  `summarize`. Pack paths under `SHADOW_BETS_PACK`:
  `evidence/shadow_bets_events.jsonl`, `evidence/shadow_bets_ledger.jsonl`,
  `state/shadow_bets_session.json`. Never invents NBBO, never places
  orders, never calls Tradier/UW. Labels such as `yes_latency_fix_wake`
  are observational only and do **not** unlock I1 > 60s. Does **not**
  re-enable `sit_match` or change `MUST_TRADE_SMALL_ASK_CAP`. Doc:
  [docs/SHADOW_BETS.md](docs/SHADOW_BETS.md).

### Changed

- Opportunity **wake-latency** posture (2026-09-14): `sit_match` stays
  **OFF**. `shortlist_opportunity` emit (host
  `/opt/trading-desk/bin/shortlist_opportunity_webhook.py`; in-repo
  contract `deploy/examples/helsinki/shortlist_opportunity_webhook.py`)
  is TOP1_ONLY, wall-clock `executed_at` freshness,
  `SHORTLIST_OPP_MAX_AGE_SEC=45`, OCC debounce 600s, global min interval
  300s. Re-enable the opportunity timer only if a wake completes the
  refuse-or-lift path in <30s. Hunt bus default while paused:
  Continual15 + `shortlist.json`. Does **not** widen live I1 beyond 60s
  and does **not** change `MUST_TRADE_SMALL_ASK_CAP`.

### Changed

- Shortlist hunt premium band widened to **$0.50–$2.00**
  (`PREMIUM_BAND_LO` / `PREMIUM_BAND_HI`). Independent of
  `MUST_TRADE_SMALL_ASK_CAP` (stays $1.50). Filter constants only;
  no orders, no live STO ban / sit_match / must-trade cap changes.

### Fixed

- UW option-trades companion `_query()` now urlencodes both
  `issue_types[]=Common Stock` and `issue_types[]=ETF`. Common-Stock-only
  polls excluded SPY/QQQ from the flow ledger (0 SPY/QQQ rows 2026-09-10
  through most of 2026-09-14; last SPY 2026-09-09). Helsinki live hosts
  were patched mid-session 2026-09-14; this ports the companion. Host
  `ws_tape.py` remains host-owned. Does **not** re-enable `sit_match`
  webhooks.

### Added

- Observational **strategy-factory** hypothesis ledger
  [`tools/strategy_factory`](tools/strategy_factory) (ported from the
  Trading Desk pack). Stage machine
  `candidate → paper → validated → live_allow → killed|retired` plus
  `reject` from earlier stages. Desk defaults in
  [`config/strategy_factory.json`](config/strategy_factory.json)
  (`max_active_per_category_per_session=3`, 2 confirmations for
  validated / 3 for `live_allow`, mechanism + falsifier required,
  confirmation allowlist). Pack paths under `STRATEGY_FACTORY_PACK`:
  `evidence/strategy_factory_events.jsonl`,
  `evidence/strategy_factory_ledger.jsonl`,
  `state/strategy_factory_active.json`. CLI: `propose`, `confirm`,
  `advance`, `reject`, `kill`, `retire`, `list`, `status`, `score-day`.
  **`live_gate=false` forced** — never calls Tradier/UW, never invents
  prices, does **not** replace `live_order_gate`, does **not** unlock
  STO/I4. Doc: [docs/STRATEGY_FACTORY.md](docs/STRATEGY_FACTORY.md).

### Added

- STO / I4 **dated hold** contract (operator intent 2026-09-12):
  [docs/STO_UNLOCK_PLAN.md](docs/STO_UNLOCK_PLAN.md). Live credit/STO
  held through **Tue 2026-09-15 RTH**; paper I4 Mon–Tue (SPY/QQQ $1
  defined-risk vertical); **Wed 2026-09-16 open card** unlock review
  (default bias = allowlist defined-risk I4 through `live_order_gate`;
  **naked STO stays refused**). Local Codex gpt-6-astra:
  **PASS-WITH-FIXES** (not forever-ban). README + audit page carry
  Codex’s pre-Wed bullets (audited spread path, OCC/width/direction,
  cash budget vs ≥20% floor, fill-not-ack exits, SPY/QQQ
  American/physical settlement, lifecycle test if no paper trade, one
  Trading Bot unlock authority + controlled flag; pause blocks new
  entries / preserves exits). Stub
  [`tools/i4_credit_paper`](tools/i4_credit_paper). Gate refuse strings
  say dated hold, not forever. Does **not** flip the allowlist, change
  the cash floor, or allow WS→orders / raw POST. Do **not** keep a
  forever ban.

### Added

- Optional overnight-carry fields on `tools/live_order_gate` `write-thesis`
  (`overnight_carry`, `carry_dte`, `carry_event_risk`, `carry_rationale`).
  Soft notes only: same-day entries may omit them; `--overnight-carry`
  requires the three carry notes. `how_it_dies` / `falsifier` required on
  every written thesis. Stamped on receipt JSON, evidence markdown, and a
  `thinking.jsonl` `gates/carry` row. Does **not** auto-flatten, change the
  cash floor, or lift the credit/STO ban.
- Shadow GEX 60-minute paired scorer `tools/gex_shadow` (`live_gate=false`).
  One-lot ask→bid $ for baseline vs agree-only; missing marks unscored;
  OCC deduped; marks never invented. Kill criteria in the tool README.
- [docs/GREEN_WEEK_OPTIONAL_20260912.md](docs/GREEN_WEEK_OPTIONAL_20260912.md)
  — pointer to both optional tools; Helsinki shortlist deploy remains
  operator-side.

### Added

- Three-plane realtime desk: hot sensor (Helsinki, no LLM) → thin ranker
  (`groktrading.shortlist` / `scripts/shortlist_ranker.py`, 5–15s,
  `shortlist.json` ≤1–3 OCCs) → Continual15 + `live_order_gate`.
  `sit_match` POSTs deprecated as hunt bus. Prefer `SIT_MATCH_WEBHOOK`
  off. `SIT_MATCH_MIN_INTERVAL_SEC` (host 300) is a Cursor bandage, **not**
  the trading latency target; do not raise `SIT_MATCH_MAX_AGE_SEC` (60).
  Example timer under `deploy/examples/systemd/shortlist-ranker/` is
  **not auto-enabled**. Docs: [REALTIME_PLANES.md](docs/REALTIME_PLANES.md),
  [astra_realtime_planes_audit_20260912.md](docs/astra_realtime_planes_audit_20260912.md).
  Ranker contract is testable without secrets. No host auto-deploy.
  **Merge ≠ Helsinki restart.** No invented prices.

### Changed

- README current-desk refresh (Mon 2026-09-14 readers): live hunt is
  **Continual15**; Opening15 demoted to paper/research. Live card cites
  `live_order_gate` BTO/STC (PR #35) and Friday operator-stated book
  (open $421.74 → flat $460.56; `QQQ260911P00717000` 1.06→1.45;
  `close_pl` +$39; take-gain TRIAL n=1 — not locked). Document package
  `SIT_MATCH_MIN_INTERVAL_SEC` default **60** vs host Mon prep **300s**
  unmuted / consume 60s; hunt is Continual15-only (300s producer vs
  60s consume is near-empty).
  Host trading routines `CRON_TZ=America/New_York`; close card 16:00 ET.
  Helsinki map is "as of PR #35 on main" — no old SHA, no deploy claim.
  **Merge ≠ Helsinki restart.** No secrets; no invented prices.

### Added

- In-repo `tools/live_order_gate` (dry-run only; never POSTs). Grok box
  had a hot-patch so Friday STC could close; GitHub `main` was still
  BTO-only at submit. Entry stays fail-closed (`buy_to_open`, 12:30 PT
  cutoff, cash debit, exact-side credit/STO ban, alphanumeric tag,
  thesis TTL). Named exits (`take_gain_exit`, …) may `sell_to_close` /
  `buy_to_close`; skip cutoff + cash debit; thesis required; no
  credit-ban false positive on STC or thesis prose. `close --form-json`
  is optional and must match the thesis-built form. Audit:
  [docs/astra_friday_desk_audit_20260911.md](docs/astra_friday_desk_audit_20260911.md),
  [docs/LIVE_ORDER_GATE.md](docs/LIVE_ORDER_GATE.md). Take-gain remains
  TRIAL n=1 — not locked. No live fills invented; no secrets.

### Fixed

- `sit_match` POST-time hop chase (2026-09-11 Helsinki → Grok Bot latency):
  inbound `print_age_sec` can claim 1–10s while `executed_at` is 600–1900s
  old. Desk evidence: ~20+/min POSTs queued Cursor wakes (p50 ~16m) while
  HTTP was always ~0.5–0.7s. `prepare_sit_match_outbound` is the single
  POST gate — freshness is `executed_at` only; `print_age_sec` is overwritten
  from that clock; `emitted_at` + hop timestamps are stamped. Sender
  re-checks immediately before HTTP (`sit_match_stale_at_post`). A
  lying-fresh `print_age_sec` on a stale print is
  `sit_match_print_age_contradicts`. Live producer (already on
  `/opt/trading-desk/ws_tape.py`): **OCC-only** debounce (not
  OCC+`executed_at`) plus `SIT_MATCH_MIN_INTERVAL_SEC` default **60**
  (15 outran Cursor ~22s wakes) → POSTs ≤1/min. Mute:
  `SIT_MATCH_WEBHOOK=0` and/or `/opt/trading-desk/state/sit_match_webhook_muted`
  (`sit_match_webhook_muted`). Inbox + live I1 still refuse stale
  `executed_at` at wake. Residual ~6m wake lag after the 60s gate was the
  old queue draining. Contract:
  `deploy/examples/helsinki/ws_tape_sit_match.py`. Local proof:
  `scripts/simulate_sit_match_webhook.py`. `ws_tape.py` remains host-owned.
  No prices invented; no secrets.

- Claude P0 CHANGE 1: live `evaluate_gate` requires `candidate.executed_at`
  age ≤ `SIT_MATCH_MAX_AGE_SEC` (default 60s). Missing/unparseable/stale
  fails closed (`missing_executed_at` / `stale_print`); no `created_at` /
  `timestamp` substitute (C2 already on emit). `OrderMachine` stores
  `gate_passed_ts` and refuses FINAL_GATE→SUBMIT when older than
  `max_quote_age_seconds` (policy default 5s, same as quote_gate).
- Claude P0 CHANGE 2: Tradier `feeds/tradier.py` balances use nested
  `cash.cash_available` (cash) or `margin`/`pdt.option_buying_power`
  (margin/PDT). Do not use `total_cash` (includes unsettled) as buying
  power — closes executor GFV inflation. Missing nested fields raise
  `BalancesParseError`. `must_trade_small` is unchanged.

### Added

- Encoded I1 `must_trade_small` on `Candidate` / `evaluate_gate` (Astra
  profitability audit 2026-09-09 CHANGE + 48h Continual15 experiment). Sit-2
  remains the I2 lean bar and still hard-rejects when the flag is false. When
  true, skip only `SIT2_INCOMPLETE` and record `must_trade_small_exception`.
  Freshness, matching ask, ≥20% cash, qty=1, BTO-only, entry cutoff, and
  already-run stay hard. Optional `committed_i2` waives the $1.50 ask/limit
  cap on that path only. The ~11:00 PT clock is Continual15 (not encoded).
  Does not change `PREFERRED_ONE_LOT_NOTIONAL`; live Bot cheap band on funded
  cash is ~$0.80–$1.50. No account-events, WS→orders, spray, credits, or
  Opening15→live.

### Fixed

- **C2** Execution-time freshness: `flow_ledger` / `sit_match` no longer treat
  `created_at` or `timestamp` as `executed_at`. Missing execution clock
  fail-closes freshness-sensitive use (sit_match age gate, quote interest).
  Non-finite `SIT_MATCH_MAX_AGE_SEC` / explicit `max_age_sec` (`inf` / `NaN`)
  fail closed. Codex Astra review 2026-09-08.
- **C4** `UW_WS_URL` probe `public_url` publishes only validated
  `wss` scheme/host/path; query, userinfo, and fragment (including
  `access_token`) are discarded.
- **C5** Box rotate rejects symlinks, resolved paths outside the archive
  root, and case-tricks (`.ENV`, `.env.staging`); only controlled
  `.sqlite` / `.json` / `.jsonl` exports are eligible.

### Added

- **H3** Operational retention: `groktrading.retention` +
  `scripts/hot_ledger_retain.py` (verified purge of `uw_flow.sqlite`, bound
  companion JSONL). Example systemd timer/cron under
  `deploy/examples/systemd/hot-retention/` and `deploy/examples/cron/` —
  files only; do not enable from this repo.
- **H5** Host companion example units run as `User=tradingdesk` (not root),
  drop `grok-webhook.env` from units that never emit webhooks, and document
  scoped writable dirs (`/var/lib/trading-desk/ledger`, `state`).
- Flow-alerts **H1**: append to the ledger before marking an alert id seen;
  failed store/delivery is retried (not silently dropped).
- Shared OCC aliases include live UW `option_chain` for sit_match-shaped
  detection; conflict-safe flow_ledger insert on `(source, raw_digest)`.
- Helsinki **host companions** as first-class repo artifacts (secret-free): live **urllib** pollers matching Helsinki 2026-09-08 (`scripts/helsinki_http.py` `UrllibHttp`, not httpx; `flow_ledger_companion.py`, `flow_alerts_companion.py`, `tide_companion.py`, `screener_companion.py`, `quote_interest_companion.py`). urllib GETs **do not follow redirects** so `Authorization` is never re-sent. Example units under `deploy/examples/systemd/host-companions/` (flow-ledger, flow-alerts, tide, screener, quote-interest, replay-scorecard service + timer). **`install_helsinki.sh` does not copy, enable, or start them.** Operator-wired only. **Merge ≠ Helsinki restart.** Account-events stays files-only / disabled. **`emit_sit_match=False`.** Flow-alerts material is local JSONL only (no Grok webhook). Authorization Bearer is runtime env only. Never-orders comments preserved. No live UW in CI; no credentials.

### Fixed

- Flow ledger maps live UW **flow-alerts** OCC from `option_chain` (e.g. `SPXW260930P07500000`) in addition to `occ` / `option_symbol` / `option_chain_id`. Companion polls no longer store `0` with `FlowLedgerError: missing_occ`. sit_match emit is unchanged; account-events stays off. No live network in CI.

### Added

- Helsinki **sensor farm** P1 + P2 (package helpers; **not** a host deploy or auto-restart): UW **flow-alerts** poller (`feeds/flow_alerts.py`, 15–30s) appends `source=flow-alerts` and emits material only on a **new alert id**; sit_match-shaped rows reuse `sit_match` freshness. Slow **tide + optional net-prem** writer (`feeds/tide_state.py`, 1–5 min) → `tide_state.json`. Bounded **Tradier quote interest** (`feeds/quote_subscribe.py`, max 40, drop idle) — live `ws_tape.py` stays host-owned. Thin **RTH screener snapshot** (`feeds/screener_snapshot.py`, 5–15 min) does **not** spray `sit_match`. **Shadow minute-marks** (`feeds/shadow_marks.py`) poll Tradier quotes for an OCC book; no orders. **`UW_WS_URL` probe stub** (`feeds/uw_ws.py`) fail-closes if unset and does not invent a subscribe protocol. **Finnhub watch widen** (cap 16–40) + overnight `/company-news` for those symbols only (Finnhub ≠ option NBBO). **Replay scorecard** (`replay_scorecard.py`) counts first-print / already-run / stale-filtered; `pnl` is always null. CLIs are offline skeletons. README / WEBSOCKETS / DEPLOY / env knobs: merge ≠ Helsinki restart; wire companion units separately; do not auto-start account-events. No live network in CI; no credentials.

### Added

- Helsinki **sensor farm** P0 (package helpers; not a host deploy): append-only UW **flow ledger** (`groktrading.flow_ledger`, SQLite WAL) with `append_row` / `iter_recent` / `purge_older_than`; `sit_match` emit stays fail-closed on `executed_at` ≤ `SIT_MATCH_MAX_AGE_SEC` (default 60s). Tradier **account-events** parse/reconnect/backoff (`feeds/account_events.py`) records fills/cancels as **position truth** (stale `in_position` after flatten) and never places orders; example unit `groktrading-account-events.service` is files-only. **Box** cold-rotate deny-list + 7–14 day keep-hot + delete guard (`groktrading.box_rotate`, `scripts/box_cold_rotate.py`) — never upload `.env`/tokens; delete only after `--verified` or `--confirm-delete`. README / WEBSOCKETS / DEPLOY / OBSERVED_DEPLOYMENT / `install_helsinki.sh` notes: always-on listen vs Grok decide; hot ledger vs Box `daily/YYYY-MM-DD/`; Grok Update Computer does not rebuild Helsinki. After merge, deploy/restart Helsinki units separately. No live Tradier in CI; no credentials.

### Fixed

- `sit_match` webhooks now fail closed on Unusual Whales print age: `executed_at` must parse (ISO-8601 `Z` or offset) and be ≤ `SIT_MATCH_MAX_AGE_SEC` (default **60s**). Missing/unparseable `executed_at` does not ping. Stale UW `option-trades` rows that linger in the rolling feed (debounce is still ~90s per OCC) no longer re-wake the desk after live Tradier ask has moved. Payload and candidates carry `executed_at`. Package emitter (`SignedWebhookSender`) and Grok inbox (`WebhookInbox`) share the gate. `ws_tape.py` is **not** in this tree and is **not** copied by `install_helsinki.sh` — after merge, an operator must apply the same check in the live Helsinki sit_match branch and **restart `trading-desk-tape`**. Tradier quote/order gates are unchanged. No live orders; no credentials.

### Added

- Dual-broker Phase B-prep: Schwab OAuth helper (`groktrading.brokers.schwab_oauth`, `groktrading-schwab-oauth`) documents Ready For Use → env (`SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` / optional `SCHWAB_TOKEN_PATH`) → browser login at callback `https://127.0.0.1:8182` (no trailing slash) → local refresh token (`~/.config/groktrading/schwab_token.json`, never git). Missing credentials dry-run with an actionable stub (no browser hang, no invented token). Optional `schwab-py` wrap for `client_from_login_flow` / token refresh; 7-day re-auth reminder when the token file is absent. `SchwabBroker` still fails closed and cannot preview/submit. Note: [docs/DUAL_BROKER.md](docs/DUAL_BROKER.md), [`.env.example`](.env.example).

### Fixed

- Daily-sequence resolve test freezes collect-context `now_utc` before the resolver clock so a session-evening wall clock cannot make `frozen_at` newer than `end+7h`.
- Opening15 macro collector requests Tradier VIX as `VIX`, then `I:VIX`, then `$VIX.X`, and marks VIX **available** only when `/markets/quotes` actually returns one of those tickers. Missing stays listed; no invented index print. History `as_of` is the last returned bar’s 16:00 ET, clamped to receipt, so a mid-session rehearsal for the next session no longer ValidationError-fails the whole history category. True Wednesday pre-open still uses the prior regular close.

### Added

- Dual-broker Phase A: venue-aware `Broker` protocol (`venue_id: Literal["tradier"]`), `TradierBroker` thin wrap of the existing Tradier client, `RecordingBroker` for tests, and a `SchwabBroker` placeholder that raises `NotImplementedError` (`Schwab OAuth not ready`) with no credentials and no network. Live/paper `OrderMachine` / `Executor` (`BrokerSink`) go through the protocol; Tradier preview/submit form bodies are unchanged. Rules: no dual-fire of the same print; exits follow the holding venue. Tuesday Opening15 `research.cli run` / packet path is untouched (no `groktrading.brokers` import). Note: [docs/DUAL_BROKER.md](docs/DUAL_BROKER.md).
- Opening15 **selector_v3** as a **shadow** prompt + registry entry (`selector_v3.md`, seeded status `shadow`, parent `selector_v2`). Active default remains **selector_v2**. Deterministic refuses stay in hygiene pre-gates; the v3 prompt is judgment-only (thesis coherence, cite-or-abstain / hallucination detector). Expanded `cycle_cli select --shadow-v3 --registry` runs v3 on the same packet, hygiene shortlist, and retrieved IDs and writes `selection-shadow-v3.json` plus `selection-shadow-compare.json` without swapping active. Later score both artifacts vs `evaluation.json` `baselines.abstain` (always-flat, net 0). Tuesday clean baseline `research.cli run` is unchanged. v3 is not accepted/active and is not promoted. Paper research path only; no Helsinki/live orders.
- Opening15 expanded/select **universe hygiene shortlist** (pre-LLM): `cycle.select` builds `candidates.json` from the frozen packet and context chains, logs every reject (`gate`, symbol, contract, DTE, why), and caps premium from a dollar risk budget (`hygiene.planning_equity_usd` × `hygiene.premium_budget_pct`, or account equity/cash when present) — not a hard-coded $1–3 range. DTE is logged on every keep and reject so shadow data can split 0–2 vs longer; the default window is 0–45 and is not an overnight-horizon policy. Spread / volume / OI / ask-side tags apply only when those fields exist. Architecture = **gates then judgment**. Tuesday clean baseline `research.cli run` is unchanged (`Packet.compact()` strips `hygiene`; `recommend()` does not shortlist). Paper research path only; no Helsinki/live orders.
- Opening15 expanded/optional collectors now archive Unusual Whales economic calendar (`GET /api/market/economic-calendar`), per-symbol dark pool (`GET /api/darkpool/{ticker}` plus a small `/api/darkpool/recent` summary), one options-screener slice (`GET /api/screener/option-contracts` filtered to the 10 configured names), session-level market tide (`GET /api/market/market-tide` once), and congress trades touching those names (`GET /api/congress/recent-trades`). Insider uses official `GET /api/insider/transactions` and is skipped quietly when it returns no universe rows. Empty UW `data` is coverage `available` (0 events), not missing; HTTP/auth failure is `missing`/`partial` and cannot abort the baseline tape (`isolate_optional_collectors`). Finnhub `/calendar/economic` is unused (403 on this plan). Paper research path only.

### Fixed

- Opening15 capture: `isolate_optional_collectors` no longer blocks past its pre-open budget. The previous `with ThreadPoolExecutor` form called `shutdown(wait=True)` on exit, so a hung expanded collector (slow Finnhub/UW call) held the process until it finished, delaying stock capture past 09:30 and failing the 90 s coverage-gap check (lost session). Now `shutdown(wait=False)`; budget overrun is detected via `future.done()` (on 3.11+ `concurrent.futures.TimeoutError` is the builtin `TimeoutError`, so type alone cannot distinguish a slow collector from one that raised). Regression test with a real hang asserts return at the budget. Paper research path only; no Helsinki/live change.
- Opening15 five-session protocol now rejects duplicate or synthetic evaluation copies and mixed experiment identity (no kill/continue from five copies of one day). Kill/continue also require five known random-K percentiles and five mechanical nets; a single known percentile is `insufficient`.
- Registry-backed `select` validates prompt hash, permitted status (`accepted`/`shadow`), and pre-session freeze before any CLI inference. Rejected or wrong-hash versions raise with no fallback.

### Added

- Opening15 `evaluation.json` additive `baselines` (1,000 seeded random-K percentile, mechanical top-K-by-ask-side-premium, abstain, decision/entry latency) on the same frozen packet and 15:55 ET exit. Original evaluate keys stay byte-identical.
- Pre-registered paper decision protocol: `python -m groktrading.research.cli protocol` reads up to five sessions and returns `insufficient | rejected | kill | continue | inconclusive`. `continue` means more paper only. [docs/OPENING15_DECISION_PROTOCOL.md](docs/OPENING15_DECISION_PROTOCOL.md).
- Daily expanded sequence now **creates** post-session `outcome-context.json` before resolve. Prompt registry active version is what `select` actually loads. Failed session records are included in next-day memory.

### Changed

- Opening15 day-plan / runbook default: **Tue 2026-09-08** stays clean baseline `research.cli run` (no `--allow-degraded`, no expanded-readiness claim). **Post-Tue paper days** (session 2+ / Wed 2026-09-09 onward) **default to expanded select** (`context.json` + `cycle_cli select`) so the LLM gets UW economic calendar, dark pool (per 10 names), option screener, market tide, and political slices. Fall back to baseline or explicit `--allow-degraded` only if required coverage is incomplete. Baseline `research.cli run` behavior is unchanged. Unit tests ≠ live entitlement.
- Tuesday 2026-09-08 posture: operational paper pilot on clean baseline (`research.cli run`), not `--allow-degraded`, not expanded-strategy readiness. Unit tests ≠ live entitlement. Schwab still unconnected. UW economic calendar / dark pool / screener / tide are expanded LLM context only; Finnhub `/calendar/economic` still 403 on this plan.

### Fixed

- Option-chain coverage is per-symbol: a subset (e.g. AAPL only) is `partial`, never universe-`available`. Portfolio coverage requires known cash and buying-power fields.
- Collector receipt timestamps are stamped after the HTTP response. Chain rows keep provider quote timestamps and ages when present.
- Optional/expanded collector timeouts no longer abort baseline opening-tape capture.
- Opening15 expanded Context portfolio collector: Tradier `/accounts/{id}/orders` (and balances/positions) payloads no longer assume every wrapper or row is a dict. `"null"` strings, empty lists, and nested shapes fail closed to coverage `missing` or an empty working-orders list with a reason. `collect_context` also fail-closes `TypeError`/`AttributeError` so a bad snapshot cannot abort the cycle. Account numbers stay opaque `acct-` aliases. Missing `$VIX.X` remains macro `partial`.

### Added

- External Claude audit brief: [docs/CLAUDE_AUDIT.md](docs/CLAUDE_AUDIT.md) (linked from README). Same $25k YOLO / capital-expansion mandate as the OpenAI pack, plus Opening15 paper path, connected APIs (names only), and local test commands.
- Opening15 / research-cycle expanded Context collectors on `main`: UW option-trades + headlines, Tradier quotes/calendar/history/chains and read-only account snapshot, entitlement-gated Finnhub general news. Portfolio is Tradier-backed until Schwab OAuth. Typed `FailureRecord`, file-based prompt registry, and `cycle_cli day-plan`. Runbook: [docs/TUESDAY_EXECUTION_READINESS.md](docs/TUESDAY_EXECUTION_READINESS.md).
- Opening15 recommend backend selection: `recommend_backend` is `codex_cli` (default) or `openai_responses`. Codex CLI path uses `codex exec` with the ChatGPT Pro CLI session, `--output-schema` Decision JSON, read-only/ephemeral flags, and recorded `codex --version`. `OPENAI_API_KEY` is not required when the backend is `codex_cli`. Responses API remains behind the flag. Runbook: [docs/OPENING15_EXPERIMENT.md](docs/OPENING15_EXPERIMENT.md).
- Public OpenAI audit pack: `docs/OPENAI_AUDIT_BRIEF.md` (what to review / what not to change / $25k YOLO expansion ask) and `docs/WEBSOCKETS.md` (Finnhub stock-trade WS vs option NBBO, Helsinki `trading-desk-tape` vs package `feeds/`, WS-never-orders, webhook events, reconnect/TTL/HMAC/AH-weekend coalesce, print→filter→webhook→Grok→gate→preview→submit sequence).
- README / operating-model / safety / architecture lead: **public reference package** for external audit; not financial advice; live is operator-gated; **$25,000 planning capital** + YOLO **capital expansion** mandate; live fills may still be cash-constrained on a smaller funded balance.

### Changed

- Softened outdated “~$600 / first milestone $1000 / $10,000” as the **primary** capital frame. Those remain a historical note only. Planning / selection / multi-lift is **$25k**.
- Redacted previously committed sandbox account identifier from public docs (`ACCOUNT_ID_REDACTED` / `YOUR_*` placeholders). Live production account IDs are not published.
- Extended `scripts/scan_secrets.py` (known live-account-id block, common token shapes, working-tree walk excluding `.git`) so CI still fails closed on credentials.

### Previously added (still unreleased)

- Scoped live-desk hardening (package-first; no Helsinki deploy): P0.1 Tradier production quote gate (OCC, delayed, provider bid/ask dates, spread, no-chase); P0.2 broker-authoritative final gate (session facts + fresh account/positions/orders/clock; qty=1; cash/equity ≥20%); P0.3 stub-safe preview→submit order FSM with immutable payload and no blind retry; durable SQLite WAL inbox/outbox idempotency with AH/weekend digest coalesce; cutoff-cancel alert path.
- Live card encoded in `policy.py`: overnight long options allowed; 12:30 PT new-entry cutoff only; max deploy 80%. OpenAI P0.4 flatten-everything / no-overnight is rejected.

### Changed

- README, SAFETY, architecture, operating model, deploy/rebuild docs, and installer comments: replace any ≥50% cash floor with ≥20% reserve. Helsinki vs package topology recorded from the 2026-09-05 SSH map (`/opt/trading-desk`, `trading-desk-*.service`, webhook-only, in-memory ~90s debounce).
- `evaluate_cash_up` now delegates to entry-cutoff and never flattens.

### Notes

- Helsinki deploy of debounce/idempotency onto `ws_tape.py` is a **follow-up**. Operator must authorize any restart. This changelog does not invent fills or PnL.
- n=3 live days ≠ edge. Strategy knobs (sit-2, already-run, matching-ask) are frozen except safety.

### Previously added (still unreleased)

- Operator runbook `docs/REBUILD_NEW_PROVIDER.md` for a full Helsinki rebuild on a different cloud provider (secret copy matrix by key name and dest path only; trading-desk crons only; package skeleton ≠ `ws_tape.py`).
- Example `deploy/examples/env/trading-desk.env.example` matching observed `/opt/trading-desk/.env` key names (`YOUR_*` placeholders).
- Portable Helsinki/new-VPS installer (`scripts/install_helsinki.sh`) plus `docs/DEPLOY.md`: package root `/opt/groktrading`, package-named systemd units, no enable/start/secrets/live by default.
- Example `groktrading-tape.service` and `groktrading-tape` skeleton CLI (not a port of legacy `ws_tape.py`).
- Architecture diagram (PNG + Mermaid) for the Outside APIs / Helsinki / Grok Bot / Passive Reviewer split.
- Dedicated `logs/trades.jsonl`.
- FABLE 5.1 hardening recorded as research; live card frozen n=3.
- After-hours / overnight reflection.
- Helsinki Finnhub WS adapter live-validated SPY/QQQ + REST quote HTTP 200.
- Grok webhook first fire 2026-09-03 09:14 PT; no duplicate SPCX action.
- GitHub groktrading PR #1 with P0 gate/quote gaps so this repo is not the live executor.

### Previously changed (still unreleased)

- README / architecture docs (superseded): earlier live-card text used ≥50% cash; this hardening replaces that floor with ≥20%. Overnight longs allowed; 12:30 PT new-entry cutoff only; LLM must not call Tradier, gate/executor does.
- 2026-09-02: spend sit-2 on matching-ask skip-passers; print is thesis.

### Fixed

- Helsinki nightly cron `CRON_TZ=America/Los_Angeles`.

## [2026-09-03]

- Live sit-1 SPCX 9/04 145p BTO 0.86 order 144472104 ~07:41 PT; still open 09:42 PT; hold to 12:30.
- Infra: Finnhub env 0600; webhook env present; tape `EnvironmentFiles` still `/opt/trading-desk/.env` only.

## [2026-09-02]

- Flat $0.
- Do not drop already-run off MU hyp +$390.
- Do not chase walks off TSLA hyp +$127.

## [2026-09-01]

- Flat $0.
- Helsinki `trading-desk-tape.service` deployed.

## [2026-08-28]

- Flat $0.

## [2026-08-27]

- AAPL 8/28 312.5c 1.33→2.34 realized +$101 n=1; do not size up.

## [2026-08-26]

- NVDA 8/28 225c 2.06→1.75 realized -$31.

## [2026-08-25]

- AMZN 8/26 265c 1.12→0.84 -$28.
- DRAM 8/28 57c 0.98→0.95 -$3.
