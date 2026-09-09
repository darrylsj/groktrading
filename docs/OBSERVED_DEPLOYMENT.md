# Observed deployment (Helsinki)

This file records **operator-observed** host facts. It is **not** a claim that **this git repository** is deployed, and it is not a license for the cloud agent to SSH, restart units, or ship credentials.

A portable installer now lives in-repo (`scripts/install_helsinki.sh`, [DEPLOY.md](DEPLOY.md)). Different-provider full rebuild (secrets by key name, legacy scripts, two crons, cutover): [REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md). That is rebuild tooling only. **This commit is still not the live Helsinki tree** until an operator cutover is recorded here.

## Authoritative topology (2026-09-05 SSH map)

Treat this as ops context. Do not invent a preview→submit path on the host.

| Fact | Reality |
| --- | --- |
| Live runtime | Hand-built **`/opt/trading-desk`** — **not** `/opt/groktrading` package units |
| Units | `trading-desk-tape.service` (`ws_tape.py`) + `trading-desk-finnhub.service` |
| Git on host | **No** `.git` under `/opt/trading-desk` |
| GitHub `main` at map time | `e297a0af…` |
| Order path | Helsinki has **no** preview→submit. It webhooks candidates |
| Webhook events | `sit_match`, `in_position`, `cash_up` with `entry_cutoff_only_no_flatten`, `day_win_target` with `auto_flatten: false` |
| Webhook idempotency | In-memory debounce **~90s** only — causes weekend same-digest spam |
| Live card on the host | Overnight longs allowed; 12:30 PT = new-entry cutoff only; cash/equity ≥20% |

Package hardening (quote gate, final gate, order FSM, durable idempotency, `sit_match` `executed_at` freshness) is the correct **first ship**. Copy `ws_tape` debounce/idempotency and the sit_match age gate later. **An operator must authorize any Helsinki restart** of `trading-desk-tape`. This repository must not perform that restart. Without that host patch, UW `option-trades` rows can linger for hours and re-fire `sit_match` after live Tradier ask has moved (90s OCC debounce is not freshness).

The installer default remains `/opt/groktrading` + `groktrading-*.service`. Running it with defaults must not overwrite `/opt/trading-desk` or `trading-desk-*.service`.

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

## Accounts (non-secret identifiers only)

- **Planning capital:** **$25,000** desk frame for selection / multi-lift sizing. Goal is **capital expansion** (YOLO), not preservation.
- **Live funded balance:** may still be **smaller / cash-constrained** until the $25k is deposited. Do not treat planning capital as current broker equity. This file does **not** publish a live cash figure or invent P&L.
- **Historical note:** the live funded book started small (early operator notes used on the order of hundreds of dollars; first milestone $1,000 then $10,000). Not the primary frame.
- Tradier live and sandbox **account IDs** are **not** committed. Use `YOUR_PRODUCTION_ACCOUNT_ID` / `YOUR_SANDBOX_ACCOUNT_ID` / `ACCOUNT_ID_REDACTED` in public docs. Identifiers are not tokens; tokens never belong in git.

Examples that **are** in git live under `deploy/examples/` and use placeholders only.
