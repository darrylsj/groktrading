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

Package hardening (quote gate, final gate, order FSM, durable idempotency) is the correct **first ship**. Copy `ws_tape` debounce/idempotency later. **An operator must authorize any Helsinki restart.** This repository must not perform that restart.

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

- Tradier live cash is on the order of **$600** (operator context; not a live feed).
- Tradier sandbox paper account id **VA75691022** (identifier, not a token).
- Milestones: **$1,000** then **$10,000** — goals only.

Examples that **are** in git live under `deploy/examples/` and use placeholders only.
