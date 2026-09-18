# Observed deployment (Helsinki)

This file records **operator-observed** host facts. It is **not** a claim that **this git repository** is deployed, and it is not a license for the cloud agent to SSH, restart units, or ship credentials.

A portable installer now lives in-repo (`scripts/install_helsinki.sh`, [DEPLOY.md](DEPLOY.md)). Different-provider full rebuild (secrets by key name, legacy scripts, two crons, cutover): [REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md). That is rebuild tooling only. **This commit is still not the live Helsinki tree** until an operator cutover is recorded here.

Dated operator policy: [CURRENT_POLICY.md](CURRENT_POLICY.md), including unresolved calendar/schedule labels. Introduction: [README.md](../README.md). Safety checklist: [SAFETY.md](SAFETY.md).

## Operator-locked desk (2026-09-17 PT)

Authoritative for **current** public docs. Not a claim this commit is running on Helsinki. **No SSH from this update.** Do not invent fills or P&L.

### Capital / session

| Fact | Reality |
| --- | --- |
| Planning frame | **~$25k** (may not be fully deposited). Live fills still respect actual Tradier cash/BP |
| Cash / equity floor | **≥20%** at all times (max deploy **80%**) |
| Overnight long options | **ALLOWED** |
| 12:30 PT | **NEW-ENTRY CUTOFF ONLY** — not a forced flatten / not cash-flat-by-close |
| Open stand-down | New entries **9:30–9:45 ET only**, then hunt |
| Size | Small size / one-lot preference; no extra house loss caps / PDT caps |

Older ≥50% cash, flatten-at-12:30, cash-flat-by-close, or no-overnight text is **historical / stale**.

### Hunt loop

| Fact | Reality |
| --- | --- |
| Live hunt | **Continual15** on `CRON_TZ=America/New_York */5 9-15 * * 1-5` (5-minute floor, **not** a literal 15-minute-only loop) |
| Opportunity / `sit_match` / `shortlist_opportunity` | **KEEP_PAUSED** (latency / I1_stale history). Not an active hunt bus |
| Helsinki | Sensors / webhooks only |
| Grok Bot | Sole decision + order path |
| Live orders | **`live_order_gate` write-thesis first only** — raw POST forbidden |
| Ask band | **HARD ±$0.02** at decision **and** submit recheck (`ask_drift`); never chase |
| I1 freshness | **SOFT 180s** (hard stale only **>180**). Package `SIT_MATCH_MAX_AGE_SEC` default is still 60s until copied |
| Disagreement | OPTIONAL on fresh OCCs; hard exception for same-OCC reentry after `dead_thesis` exit |
| Hard skips | **META / NET / MU / AMD**; no SPCX; no INTC puts |
| Live STO / credit | **Still refused** pending **Fri 2026-09-19 I4 review**. Wed 2026-09-16 did **not** unlock. Naked STO stays refused |

### Take-gain (TRIAL — Darryl 2026-09-17)

| Knob | Current |
| --- | --- |
| Arm | bid ≥ entry × **1.25** (was ×1.40; operator-stated INTC miss: peak 2.02 vs old arm 2.03 missed green) |
| Protect | entry + **0.50** × (peak_bid − entry); ratchet with peak |
| Overrides | Dead thesis / operator flatten can override; no first-red stop as a house rule |
| Lock? | **No.** Do not treat ×1.40 as current |

### UW usage (2026-09-17)

| Item | Status |
| --- | --- |
| Live path | Mainly UW option-trades / flow → Tradier ask match |
| GUI live on plan | 0DTE Flow, Interval Flow, Market Tide, Dark Pool/Large Trades, Multi-leg, News, Catalyst/Earnings calendars |
| GUI delayed / gated | Flow Alerts (**2-day**), Options Screener (**2-day**), Custom Alerts (**30m**) |
| UW MCP | **DEFERRED** — do not install; if ever, box-only research toy, **never Helsinki**, **never Continual15 submit** |
| Continual15 Friday+ shadow tags | **SCORE-ONLY**: `stale_event>30s`, `stale_quote>2s`, `duplicate_event`, `spread_or_size`, `multileg_unresolved`, `catalyst_unknown` (+ latency ages) |

## Authoritative topology (2026-09-05 SSH map)

Treat this as ops context. Do not invent a preview→submit path on the host.

| Fact | Reality |
| --- | --- |
| Live runtime | Hand-built **`/opt/trading-desk`** — **not** `/opt/groktrading` package units |
| Units | `trading-desk-tape.service` (`ws_tape.py`) + `trading-desk-finnhub.service` |
| Git on host | **No** `.git` under `/opt/trading-desk` |
| GitHub `main` at map time | `e297a0af…` |
| Order path | Helsinki has **no** preview→submit. It webhooks candidates |
| Webhook events | `sit_match` (deprecated as hunt bus; **KEEP_PAUSED**), `in_position`, `cash_up` with `entry_cutoff_only_no_flatten`, `day_win_target` with `auto_flatten: false` |
| Webhook idempotency | In-memory debounce **~90s** only — causes weekend same-digest spam |
| Live card on the host | Overnight longs allowed; 12:30 PT = new-entry cutoff only; cash/equity ≥20% (see 2026-09-17 card above) |

Package hardening (quote gate, final gate, order FSM, durable idempotency, `sit_match` `executed_at` freshness + POST-time `print_age_sec` overwrite / `emitted_at` / OCC-only 60s min interval / mute file) is the correct **first ship**. Live Helsinki `ws_tape.py` already applies this producer gate (2026-09-11). **An operator must authorize any Helsinki restart** of `trading-desk-tape`. This repository must not perform that restart. Without that host patch, UW `option-trades` rows can linger for hours and re-fire `sit_match` after live Tradier ask has moved (~20+/min POSTs queued Cursor wakes; inbound `print_age_sec` can lie fresh).

The installer default remains `/opt/groktrading` + `groktrading-*.service`. Running it with defaults must not overwrite `/opt/trading-desk` or `trading-desk-*.service`.

**Sensor farm intent (package, not observed as already deployed):** Helsinki
listens; Grok decides. **P0** (flow ledger, account-events, Box rotate,
sit_match freshness) and **P1/P2** (flow-alerts, tide/net-prem, quote
interest, screener snapshot, shadow marks, UW_WS probe, Finnhub widen,
replay scorecard) ship as helpers here. Observed host still has no `.git`
under `/opt/trading-desk` and still does not run this commit until an
operator cutover. **Merging this repo does not restart Helsinki.** Wire
companion units separately (`deploy/examples/systemd/host-companions/` —
not auto-enabled). Account-events stays files-only / disabled.
`emit_sit_match=False`. Flow-alerts material is local JSONL only (no Grok webhook).
Hunt is three planes ([REALTIME_PLANES.md](REALTIME_PLANES.md)); the shortlist
timer is an example only and is **not** observed as deployed. **Grok Update
Computer does not rebuild Helsinki.** **UW MCP is DEFERRED** (never Helsinki).

## What was observed

- Always-on **Helsinki** server (no IP or hostname recorded here).
- Separate unit `trading-desk-finnhub.service` loads `/etc/trading-desk/finnhub.env` with mode **0600**.
- Finnhub WebSocket **SPY/QQQ** ticks were live-validated.
- Finnhub REST **SPY quote** returned **HTTP 200**.
- Existing `trading-desk-tape.service` uses **Tradier** and **Unusual Whales** and writes `live_tape.json`.
- `/etc/trading-desk/grok-webhook.env` exists with mode **0600**.
- A webhook **test fire succeeded**.
- **Integrating the Finnhub tape into the existing tape remains an explicit deployment step** and has not been performed by this repository.

## What this repo must not do

- Claim “deployed to Helsinki”
- Restart `trading-desk-*.service`
- Commit `finnhub.env`, `grok-webhook.env`, or Tradier tokens
- Treat sandbox delayed quotes as NBBO truth
- Flatten the overnight-allowed book at 12:30 PT
- Install UW MCP on Helsinki or on the Continual15 submit path
- Claim this commit is the live host tree

## Accounts (non-secret identifiers only)

- **Planning capital:** **$25,000** desk frame for selection / multi-lift sizing. Goal is **capital expansion** (YOLO), not preservation.
- **Live funded balance:** may still be **smaller / cash-constrained** until the $25k is deposited. Do not treat planning capital as current broker equity. This file does **not** publish a live cash figure or invent P&L.
- **Historical note:** the live funded book started small (early operator notes used on the order of hundreds of dollars; first milestone $1,000 then $10,000). Not the primary frame.
- Tradier live and sandbox **account IDs** are **not** committed. Use `YOUR_PRODUCTION_ACCOUNT_ID` / `YOUR_SANDBOX_ACCOUNT_ID` / `ACCOUNT_ID_REDACTED` in public docs. Identifiers are not tokens; tokens never belong in git.

Examples that **are** in git live under `deploy/examples/` and use placeholders only.
