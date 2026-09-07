# Grok implementation handoff: opening-window discretion and daily feedback

Status: reviewed reference code and implementation specification, not a connected expanded-data service. Builds on PR #8 and Grok's PR #9 Codex CLI integration. No live orders or Helsinki restart. Tuesday 2026-09-08 is an operational paper pilot only if host preflight passes; it is not a promised profitability demonstration.

## Entry points

- `src/groktrading/research/cycle.py`: typed evidence manifest, archived retrieval, selection, resolver, bounded next-day memory.
- `src/groktrading/research/cycle_cli.py`: file-based commands below; all model stages use Codex CLI. No API fallback.
- `src/groktrading/research/prompts/selector_v2.md`: complete discretionary selection prompt.
- `src/groktrading/research/prompts/retrieval_v1.md`: bounded archived-data requests.
- `src/groktrading/research/prompts/resolver_v1.md`: outcome review and tentative lessons.
- `docs/ARXIV_RESEARCH_PROTOCOL.md`: related papers, comparative experiment and publication route.

Existing capture, quote monitoring and deterministic paper evaluation remain in the PR #8 modules. The original backend retains its legacy API option; this new cycle rejects non-CLI packets. Do not use that legacy option for this experiment.

## Data contract and adapter work to implement

Provider collectors produce a `Context` JSON alongside the existing `Packet`. Every record needs a stable evidence ID, category, symbols, source, source URI, information-as-of timestamp, actual receipt timestamp, concise summary, and complete normalized payload. `Context.model_json_schema()` is the authoritative input schema. Supply a coverage entry for every category, including missing/delayed feeds. Availability is declared by adapters and must be checked against entitlements, freshness, symbol coverage and pagination; a nonempty record is not proof of a complete feed.

| Category | Required content and timing | Integration task |
| --- | --- | --- |
| Opening flow | Every accessible UW print in the ten-stock opening window; timestamps, exchange/conditions, aggressor inference, price/size, quote, contract. | Extend existing collector with corrections/cancellations and documented entitlement/row-cap/reconnect reconciliation. Do not call it all market traffic. |
| Company news | Timestamped headlines and licensed text, earnings, filings, guidance, corporate actions. | Existing stock-news collector plus archived detail adapter; deduplicate by story/version without deleting revisions. |
| World news | Overnight/current geopolitical, policy, commodity and broad-market events, not just ticker-tagged stories. | Add entitled broad-news collector; preserve publication and receipt time, relevance attribution and source provenance. No unfrozen browsing during selection. |
| Macro | SPY/QQQ/sector tape, volatility, rates, USD and relevant commodities; release results only after public receipt. | Quote/history adapters; explicitly mark missing instruments, delayed data and stale values. |
| Calendar | Known earnings, releases, central bank events and expiration/corporate-action schedules. | Archive schedule publication/version separately from future occurrence time. |
| Option chain | Contemporaneous bid/ask and sizes, expirations, strikes, IV/Greeks, previous-session OI, skew/term structure. | Broker/data adapter with exact observation time; label estimates and prior-day fields. Do not infer today's opening OI from a later snapshot. |
| History | Prior-session price/volume, opening-volume seasonality, realized vol and comparable contexts. | Build reproducible as-of history features; exclude target day's later bars. |
| Portfolio | Actual cash/buying power, open positions, working orders, exposure and account restrictions. | Read-only Schwab snapshot when authorized host OAuth is ready; use opaque research aliases, no account numbers/tokens. Missing portfolio blocks normal expanded mode. |
| Depth | Entitled exchange depth with venue/level/time, if available. | Optional. NBBO is not depth and holdings are not an order book. Explicit missing status is acceptable. |

Use existing UW/news/broker credentials only in collectors on the authorized host. This workspace has not connected those feeds or enabled Schwab OAuth. Do not print credentials. Provider access, OAuth permissions and rate limits must be verified against current official documentation before implementing adapters; do not invent endpoints or assume Schwab entitlements include depth. Schwab connection work includes developer-app approval, exact registered redirect, user browser consent, protected refresh-token lifecycle and a read-only account/quote smoke test. No order submission is needed for this pilot.

Selection validates context chronology and demands all categories except depth be available. `--allow-degraded` explicitly marks an incomplete research run; it does not qualify the run for the full-context experiment. Collectors must redact credentials in every field, including URLs and text. The payload key filter is only defense in depth, not a universal secret detector.

## Daily lifecycle

1. Before open, lock config, model settings and memory. Read up to five recent eligible daily summaries, capped at 14 KB; retain omitted dates explicitly. First day has empty memory.
2. Capture the ten-stock tape from 09:30 to 09:45 ET. Freeze expanded context by 09:45; retain the existing explicitly bounded late retrieval of opening UW events. Persist raw records privately.
3. Start `select` within three minutes of packet freeze. It presents the complete compact opening packet and all context summaries, and permits at most two requests of 40 archived detail IDs each. It never silently truncates an oversized request. This is bounded context access, not a claim every raw record was read in full.
4. Selector emits up to three eligible printed contracts or abstains, with explanations for all ten stocks, context citations, portfolio assessment and memory use. It applies no fixed alpha ranking. Deterministic evidence/format checks do apply.
5. Run existing quote monitor and evaluation against the new `packet.json` and `decision.json`. Enter only on a fresh post-response eligible ask. Fixed 15:55 ET exit at an eligible bid; fees/slippage are deterministic. One-lot research scoring is distinct from live sizing or verified buying-power enforcement.
6. After the full session, archive outcome news, chain/underlying paths and observed execution data, then call `resolve`. Outcome context may contain post-opening data; never feed it into the original selector. Resolver reviews every ranked pick and all ten stocks, citing source IDs. It cannot rewrite numerical PnL.
7. Build next-session memory before open. Proposed lessons remain tentative with counterevidence and disconfirmation. Detailed daily records stay in storage while small summaries enter the next prompt.

```bash
python -m groktrading.research.cycle_cli memory --session 2026-09-08 --out /private/research/2026-09-08/memory.json
python -m groktrading.research.cycle_cli select --packet /private/capture/2026-09-08/packet.json --context /private/capture/2026-09-08/context.json --memory /private/research/2026-09-08/memory.json --out /private/research/2026-09-08/selection
python -m groktrading.research.cycle_cli resolve --packet /private/research/2026-09-08/selection/packet.json --decision /private/research/2026-09-08/selection/decision.json --evaluation /private/research/2026-09-08/evaluation.json --context /private/research/2026-09-08/outcome-context.json --out /private/research/2026-09-08/resolution
python -m groktrading.research.cycle_cli memory --session 2026-09-09 --records /private/research/2026-09-08/resolution/daily-resolution.json --out /private/research/2026-09-09/memory.json
```

Paths are examples. Input provider files must exist; these commands do not manufacture live context. Schema errors, missing categories and time guards fail closed. Commands create immutable attempt files and do not overwrite/retry a decision. Fix operational problems on a new explicitly labeled attempt; never cherry-pick a better rerun for the primary result.

## CLI runtime and infrastructure

Use a dedicated research OS user and isolated workspace with its own authorized Codex CLI login. Verify installed version/flags and requested model availability in preflight. Record observed model identity if supplied by CLI; absence is unknown. Login status alone does not establish subscription entitlement. Check CLI usage limits against the planned daily stages and shadow arms.

Collectors write sanitized evidence into the research workspace; the CLI process must have no broker credentials or broker token files available. Environment filtering is insufficient if a shared HOME exposes credentials. Use host filesystem isolation and egress restrictions appropriate to the authenticated Codex runtime. Read-only sandbox prevents writes, not all reads or network access. Prompts prohibit tools and the reference implementation rejects observed tool calls, but that audit is not a complete security boundary. Honor installed rules; do not bypass permission controls.

For the pilot, use existing host scheduling, append-only private JSON/JSONL and SQLite for run status if needed. Add encrypted backups and NTP/clock-health checks. A vector database, Kafka cluster or extra broker is not necessary for five-day memory. Only buy additional feeds after identifying a concrete coverage/latency gap and confirming historical/redistribution entitlements. Add per-stage timeout, disk-space, capture-gap and authentication health alerts to the operator's existing dashboard; do not send external messages without authorization.

## Recursive improvement and remaining production work

This reference implements context-based adaptation, not weight training or guaranteed improvement. A resolver's explanation is a hypothesis, not a verified causal label. It writes prompt-change proposals but cannot promote them.

Grok should implement a version registry with immutable prompt hash, parent version, supporting session IDs, hypothesis, proposed difference, forward-test plan and status (`proposed`, `shadow`, `accepted`, `rejected`). Freeze the active version before each evaluation block. Compare candidate and incumbent on the same future sessions with equal evidence/compute; no retrospective optimization on the test set. Promotion requires a recorded experiment review under the preregistered rule. New candidate lessons may inform a separate shadow arm; never silently modify the confirmatory arm.

Outstanding integration work: actual expanded-context collectors; host isolation and model entitlement probe; exchange-calendar scheduling; persisted failure records for stages that never produced a decision; observer dashboard; version registry and forward comparison runner; portfolio eligibility enforcement if moving beyond one-lot standalone scoring. `DailyRecord.status` reserves `failed`, but this reference resolver needs valid decision/evaluation artifacts—Grok must create a separate typed failure record path rather than invent a decision or PnL. No automatic schedules have been enabled here.

## Acceptance gates

- Local unit checks cover evidence chronology, archive identity, memory cutoff/cap, selector/resolver shape and outcome linkage; synthetic results are not model performance.
- Before Tuesday: authenticated CLI schema probe in the isolated host, UW completeness/rate-limit probe, correct market calendar, empty-memory first-day check, and a full synthetic replay including timeout and unavailable quote paths.
- Expanded mode requires fresh context for all required categories across the actual universe. If incomplete, run the already available baseline or a declared degraded pilot and report exactly what was absent.
- Test malformed outputs, invented contracts/IDs, duplicate records, future-news/memory injection, tool calls, excessive context, failed refresh, capture gaps and missing exit quotes. Every failure must remain visible in the session ledger.
- The reference rejects responses after 09:55 ET, including excessive retrieval latency. Preflight measured latency must fit that total deadline; a timed-out call may finish later but cannot produce an accepted decision. No model fallback or replay substitution.
- End-to-end operator signoff requires one archived decision, post-response quotes, deterministic evaluation, daily resolution and next-day memory, with no broker order call and no exposed credentials.
