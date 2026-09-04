# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Package version is `0.1.0` in `pyproject.toml`. Dated sections are **America/Los_Angeles** operator and session history. Do **not** invent extra dates, prices, fills, or P&L. Live fills belong in [logs/trades.jsonl](logs/trades.jsonl). See [docs/LOGS.md](docs/LOGS.md).

## [Unreleased]

### Added

- Architecture diagram (PNG + Mermaid) for the Outside APIs / Helsinki / Grok Bot / Passive Reviewer split.
- Dedicated `logs/trades.jsonl`.
- FABLE 5.1 hardening recorded as research; live card frozen n=3.
- After-hours / overnight reflection.
- Helsinki Finnhub WS adapter live-validated SPY/QQQ + REST quote HTTP 200.
- Grok webhook first fire 2026-09-03 09:14 PT; no duplicate SPCX action.
- GitHub groktrading PR #1 with P0 gate/quote gaps so this repo is not the live executor.

### Changed

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
