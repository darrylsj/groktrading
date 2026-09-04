# Safety

## Defaults

- `OperatingMode.SIGNALS_ONLY`
- `live_explicitly_enabled=False`
- Executor WebSocket path raises `LiveGatingError` if live mode is requested
- On-disk JSON is redacted
- HTTP timeouts fail closed

## Forbidden

- Credentials in git, unit files, tape JSON, or README examples beyond `YOUR_*` placeholders
- First-class live orders from Finnhub/UW/Tradier WS ticks
- Cash/equity below **50%**
- Multi-lot options in this policy
- Invented quotes, fills, or P&L
- GPL/AGPL runtime dependencies (Backtrader, Lumibot, Optopsy). See README research notes.

## Gate checklist (final)

1. Fresh Tradier option quote (production for truth)
2. Quote and candidate TTL
3. Matching ask
4. Buying power / cash vs ask × 100 × qty
5. Quantity exactly 1
6. No duplicate / working order on the OCC symbol
7. Market clock open
8. Before 12:30 PT new-entry cutoff (not a forced flatten; overnight long options allowed)
9. Sit-2, not already-run, not first-red
10. Preview-before-order for paper/live paths
11. Not a WebSocket-direct live submit

## Secrets handling

Env files on a host: **root-owned, mode 0600**. Examples under `deploy/examples/env/`. Never copy real env files into this repo.

## This cloud agent

Must not deploy to, SSH to, or restart Helsinki systemd units.
