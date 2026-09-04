# Observed deployment (Helsinki)

This file records **operator-observed** host facts. It is **not** a claim that **this git repository** is deployed, and it is not a license for the cloud agent to SSH, restart units, or ship credentials.

A portable installer now lives in-repo (`scripts/install_helsinki.sh`, [DEPLOY.md](DEPLOY.md)). Different-provider full rebuild (secrets by key name, legacy scripts, two crons, cutover): [REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md). That is rebuild tooling only. **This commit is still not the live Helsinki tree** until an operator cutover is recorded here. The observed host remains hand-built under `/opt/trading-desk` with no `.git`, loose scripts (`ws_tape.py`, `finnhub_adapter.py`, `tape_poller.py`, `nightly_print_bt.py`), and `trading-desk-*.service` names. Running the installer with defaults must not overwrite that tree or those units.

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

## Accounts (non-secret identifiers only)

- Tradier live cash is on the order of **$600** (operator context; not a live feed).
- Tradier sandbox paper account id **VA75691022** (identifier, not a token).
- Milestones: **$1,000** then **$10,000** — goals only.

Examples that **are** in git live under `deploy/examples/` and use placeholders only.
