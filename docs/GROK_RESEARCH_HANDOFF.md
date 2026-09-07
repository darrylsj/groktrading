# Grok implementation handoff: opening-window discretion and daily feedback

Status: expanded Context collectors are wired to documented UW + Tradier production APIs, with an entitlement-gated Finnhub world-news path. Portfolio is **Tradier read-only** until Schwab OAuth lands. Depth is explicitly missing. No live orders or Helsinki restart. Tuesday 2026-09-08 is an operational paper pilot only if host preflight passes; it is not a promised profitability demonstration.

See [Tuesday execution readiness](TUESDAY_EXECUTION_READINESS.md) for the exact current APIs, command sequences, and host launch checks.

## Entry points

- `src/groktrading/research/cycle.py`: typed evidence manifest, archived retrieval, selection, resolver, bounded next-day memory, **typed `FailureRecord`**.
- `src/groktrading/research/collectors.py`: Context adapters (UW / Tradier / optional Finnhub).
- `src/groktrading/research/registry.py`: file-based prompt version registry (hash + proposed/shadow/accepted/rejected).
- `src/groktrading/research/cycle_cli.py`: `memory`, `collect-context`, `select`, `resolve`, `fail`, `day-plan`, `registry`.
- `src/groktrading/research/prompts/`: selector / retrieval / resolver prompts.
- `docs/ARXIV_RESEARCH_PROTOCOL.md`: related papers and publication route.

Existing capture, quote monitoring and deterministic paper evaluation remain in the Opening15 modules. The new cycle rejects non-CLI packets.

## Data contract — connected vs still missing

`Context.model_json_schema()` is the input schema. Every category has a coverage row. Selection fails closed unless every required category (all except optional `depth`, `dark_pool`, `option_screener`, `market_tide`, `political`) is `available`, or `--allow-degraded` is set.

| Category | Required content | Implementation now | Remaining gap |
| --- | --- | --- | --- |
| Opening flow | UW opening-window prints, conditions, provider side tags, corrections/cancellations | Packet capture extended: no `trade_codes[]` filter; revisions classified from UW tags/codes; entitlement, 500-row cap/bisection, and late recheck documented; empty tape fails closed | Not all-OPRA traffic. No separate UW cancel endpoint (none in official skill). |
| Company news | Timestamped headlines + archive detail | UW `/api/news/headlines`; revisions kept (`story:vN`); `archived_news_detail()` is a local payload lookup | Official UW skill has no article-body endpoint. |
| World news | Broad geopolitical/policy/commodity feed | Finnhub `GET /news?category=general` when `FINNHUB_API_KEY` is set and HTTP 200 | Unused key, 401/403, or empty list → **missing, not fabricated**. UW has ticker headlines only. |
| Macro | SPY/QQQ/sector/VIX-like tape | Tradier `/markets/quotes` for config context symbols plus `IWM` and `$VIX.X` | Missing/delayed tickers listed (`$VIX.X` often absent). No rates/USD/commodities beyond those symbols. |
| Calendar | Session schedule versioned separately from occurrence | Tradier `/markets/calendar` with `schedule_version` + `occurrence_time`; UW `GET /api/market/economic-calendar` (empty `data` = available, 0 events); earnings **fields already on prints** when present | Dedicated earnings calendar still print-fields only. Finnhub `/calendar/economic` unused (403 on this plan). |
| Dark pool (optional) | Recent off-exchange prints for the 10 names | UW `GET /api/darkpool/{ticker}` (capped) + small `/api/darkpool/recent` summary | Optional. HTTP failure is `missing`/`partial` and cannot abort baseline tape. |
| Option screener (optional) | Hottest-contract slice for the 10 names | UW `GET /api/screener/option-contracts` then local filter; per-name cap | Optional. Payload kept small for Codex budget. |
| Market tide (optional) | Session-level options breadth | UW `GET /api/market/market-tide` once | Optional. Not per-symbol. |
| Political (optional) | Congress/insider rows touching the 10 names | UW `GET /api/congress/recent-trades`; official `/api/insider/transactions` skipped quietly if 0 universe rows | Optional. No invented fills. |
| Option chain | Bid/ask/sizes, expirations, prior-day OI, provider Greeks | Tradier `/markets/options/expirations` + `/markets/options/chains` (3 near expirations); OI labeled prior-day; observation timestamps | Greeks only if Tradier/ORATS returned them. Not a full all-expiry dump. |
| History | Prior-session bars / as-of features | Tradier `/markets/history` through the prior open session; target-day bars excluded | Opening-print volume seasonality is a **daily volume proxy**, labeled as such. |
| Portfolio | Cash, positions, working orders | **Tradier** `/accounts/{id}/balances|positions|orders` read-only; account numbers → opaque `acct-` aliases | **Schwab OAuth is not ready.** This is an interim Tradier-backed portfolio. Missing `TRADIER_ACCOUNT_ID` → coverage missing. |
| Depth | Entitled exchange book | Explicit `missing` | No depth API is wired. NBBO is not depth. Optional. |

Collectors redact credential-shaped keys. The payload key filter is defense in depth, not a universal secret detector.

## Daily lifecycle and Tuesday commands

```bash
python -m groktrading.research.cycle_cli day-plan --session 2026-09-08 --out /private/research/2026-09-08/day-plan.json
```

Baseline (use when expanded coverage is incomplete):

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output /private/research/2026-09-08
```

Expanded (only if coverage is available, else add `--allow-degraded` and label gaps):

```bash
python -m groktrading.research.cycle_cli memory --session 2026-09-08 --out /private/research/2026-09-08/memory.json
python -m groktrading.research.cli capture --session 2026-09-08 --output /private/research/2026-09-08
python -m groktrading.research.cycle_cli select --packet /private/research/2026-09-08/packet.json --context /private/research/2026-09-08/context.json --memory /private/research/2026-09-08/memory.json --out /private/research/2026-09-08/selection
python -m groktrading.research.cli monitor --session 2026-09-08 --output /private/research/2026-09-08/selection
python -m groktrading.research.cli report --session 2026-09-08 --output /private/research/2026-09-08/selection
python -m groktrading.research.cycle_cli collect-context --session 2026-09-08 --packet /private/research/2026-09-08/packet.json --out /private/research/2026-09-08/outcome-context.json
python -m groktrading.research.cycle_cli resolve --packet /private/research/2026-09-08/selection/packet.json --decision /private/research/2026-09-08/selection/decision.json --evaluation /private/research/2026-09-08/selection/evaluation.json --context /private/research/2026-09-08/outcome-context.json --out /private/research/2026-09-08/resolution
```

Schema errors, missing required categories and time guards fail closed. Commands create immutable attempt files. A stage that never produces a decision writes `failure-record.json` via `cycle_cli fail` or the CLI exception path — never a fake `DailyRecord` or invented PnL.

## Prompt version registry

`python -m groktrading.research.cycle_cli registry --path /private/research/prompt-registry.json --seed` writes accepted hashes for `selector_v2`, `retrieval_v1`, and `resolver_v1`. New candidates are `proposed` then `shadow`; only a recorded review may mark `accepted`. Freeze the active version before an evaluation block. `cycle_cli select --registry` uses that active selector prompt (activating a version changes the selection prompt; it is not hardcoded to `selector_v2.md`). Before inference, `select` checks the recorded hash, permitted status (`accepted` or `shadow`), and pre-session freeze. A rejected or wrong-hash version raises; there is no silent fallback. Do not silently edit the confirmatory arm.

`cycle_cli memory --records` accepts both `daily-resolution.json` and `failure-record.json`. Failed sessions appear in the next-day memory brief.

Tuesday 2026-09-08 remains the clean baseline (`research.cli run`), not this expanded sequence. See [OPENING15_DECISION_PROTOCOL.md](OPENING15_DECISION_PROTOCOL.md).

## Remaining production work

Host isolation and real model entitlement probe; exchange-calendar scheduling (templates stay inactive); observer dashboard; forward comparison runner; Schwab OAuth portfolio; portfolio eligibility if moving beyond one-lot paper scoring. No automatic schedules have been enabled here.

## Acceptance gates

- Local unit checks cover collectors (mocked HTTP), chronology, archive identity, memory cutoff/cap, selector/resolver shape, failure records and registry transitions.
- Expanded mode requires fresh `available` coverage for all required categories (optional: `depth`, `dark_pool`, `option_screener`, `market_tide`, `political`). If incomplete, run baseline or a declared degraded pilot and report exactly what was absent.
- End-to-end operator signoff still requires one archived decision, post-response quotes, deterministic evaluation, daily resolution and next-day memory, with no broker order call and no exposed credentials.
