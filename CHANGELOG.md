# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Package version is `0.1.0` in `pyproject.toml`. Dated sections are **America/Los_Angeles** operator and session history. Do **not** invent extra dates, prices, fills, or P&L. Live fills belong in [logs/trades.jsonl](logs/trades.jsonl). See [docs/LOGS.md](docs/LOGS.md).

## [Unreleased]

### Added

- Opening15 expanded/select **universe hygiene shortlist** (pre-LLM): `cycle.select` builds `candidates.json` from the frozen packet and context chains, logs every reject (`gate`, symbol, contract, DTE, why), and caps premium from a dollar risk budget (`hygiene.planning_equity_usd` × `hygiene.premium_budget_pct`, or account equity/cash when present) — not a hard-coded $1–3 range. DTE is logged on every keep and reject so shadow data can split 0–2 vs longer; the default window is 0–45 and is not an overnight-horizon policy. Spread / volume / OI / ask-side tags apply only when those fields exist. Architecture = **gates then judgment**. Tuesday clean baseline `research.cli run` is unchanged (`Packet.compact()` strips `hygiene`; `recommend()` does not shortlist). Selector_v3 prompt is not in this change. Paper research path only; no Helsinki/live orders.
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
