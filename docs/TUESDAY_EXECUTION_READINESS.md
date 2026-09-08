# Tuesday execution readiness — 2026-09-08

**Day-1 vs day-2+ default (paper only; no live orders):**

| Session | Default | Not a claim of |
| --- | --- | --- |
| **Tue 2026-09-08** (session 1) | Clean baseline `python -m groktrading.research.cli run` only | Expanded-strategy readiness. Do **not** add `--allow-degraded`. |
| **Wed 2026-09-09 onward** (session 2+) | **Expanded select** (`context.json` + hygiene `candidates.json` + `cycle_cli select`) | Live orders, or expanded readiness if required coverage is incomplete. Fall back to baseline or explicit `--allow-degraded` only then. |

**Tuesday 2026-09-08 is an operational paper pilot on the clean baseline
(`python -m groktrading.research.cli run`). It is not `--allow-degraded`. It is not a
claim of full expanded-strategy readiness.** Passing unit tests is not live entitlement
proof. Schwab is still unconnected. The dedicated earnings calendar is still
print-fields only. UW economic calendar, dark pool (per 10 names), option screener,
market tide, and political slices reach the LLM only through expanded
`context.json` + pre-LLM hygiene shortlist + `cycle_cli select` — that is the
**default after Tuesday**, not Tuesday's launch path. Architecture: **deterministic
gates, then LLM judgment** (thesis / cite-or-abstain). Finnhub `/calendar/economic` still returns 403 on this plan
and is unused. Host credentials, requested-model access and scheduling have not
been tested from this workspace. There is no live-order execution path in this
experiment.

Decision protocol (five **distinct real** paper sessions →
`insufficient | rejected | kill | continue | inconclusive`;
duplicate/synthetic copies are `rejected`; `continue` means more paper only):
[OPENING15_DECISION_PROTOCOL.md](OPENING15_DECISION_PROTOCOL.md).
Registry prompts used for selection must match the recorded hash, be
`accepted` or `shadow`, and be frozen before session open — rejected or
wrong-hash versions do not run. Seeded **selector_v3** is **shadow only**;
it is not the active version and is not Tuesday's selector. Post-Tue
expanded `cycle_cli select` still defaults to active **selector_v2** plus
the hygiene shortlist. Optional `--shadow-v3 --registry` writes
`selection-shadow-v3.json` alongside `decision.json` for later comparison
to v2 and to `evaluation.json` `baselines.abstain` (always-flat). Do not
promote v3.

Tuesday should ship from **main**. Do not enable systemd timers. No Helsinki restart. No live orders.

## Exactly where the model's information comes from

The Python collectors call data APIs using existing host credentials. Codex CLI receives the frozen packet and context summaries via stdin. The model does not possess UW/Tradier/Finnhub credentials or browse for fresh information during its decision. Archived detail retrieval is a local ID lookup, not a new provider request.

| API used | Data delivered / purpose | Timing and limitation |
| --- | --- | --- |
| `GET https://api.unusualwhales.com/api/option-trades` | Opening-window prints for the ten stocks, including UW tags/trade codes when present (kept as print / correction / cancellation). | 09:30–09:45 ET with capped-window bisection and one bounded last-minute recheck. UW-accessible tape, not independently reconciled OPRA. Empty tape fails closed. |
| `GET https://api.unusualwhales.com/api/news/headlines` | Company headlines; revisions kept by story/version. Archive detail is the stored payload. | Preopen sample, up to 100 per stock. Official UW skill has **no** article-body endpoint. |
| `GET https://api.unusualwhales.com/api/market/economic-calendar` | Macro/economic-release rows (`event`, `forecast`, `prev`, `reported_period`, `time`, `type`). | **Expanded context only.** Empty `data` (quiet weekend) is coverage **available** with 0 events. HTTP/auth failure is **missing** and does not abort baseline tape. Finnhub `/calendar/economic` unused (403 on this plan). |
| `GET https://api.unusualwhales.com/api/darkpool/{ticker}` | Recent dark-pool prints for each of the 10 configured symbols (capped). | **Expanded/optional.** Missing names → `dark_pool` **partial**. Provider prices copied as-is; none invented. |
| `GET https://api.unusualwhales.com/api/darkpool/recent` | Small market-wide recent summary; universe hits kept, other tickers counted only. | **Expanded/optional.** Failure of this extra call does not drop per-symbol prints. |
| `GET https://api.unusualwhales.com/api/screener/option-contracts` | Hottest-contract slice filtered to the 10 names; payload capped per symbol. | **Expanded/optional.** Market-wide fetch + local filter. |
| `GET https://api.unusualwhales.com/api/market/market-tide` | Session-level net call/put premium ticks (one call, last N ticks). | **Expanded/optional.** Not per-symbol. |
| `GET https://api.unusualwhales.com/api/congress/recent-trades` | Politician trades touching the 10 symbols only. | **Expanded/optional.** No-universe-hits stay available, not fabricated. |
| `GET https://api.unusualwhales.com/api/insider/transactions` | Official insider feed, filtered to the 10 names. | **Expanded/optional.** Empty universe slice is skipped quietly with a coverage note (`/api/insider/recent` is not used). |
| `GET https://finnhub.io/api/v1/news?category=general` | World / broad-market headlines when `FINNHUB_API_KEY` is present and entitled. | Entitlement-gated. Unused, 401/403, or empty feed → `world_news` coverage **missing** (not fabricated). UW has no world-news path. |
| `GET https://api.tradier.com/v1/markets/quotes` | Underlying, context, and macro snapshots (SPY/QQQ/sectors/VIX). VIX is requested as `VIX`, then `I:VIX`, then `$VIX.X`. | Delayed quotes are labeled. VIX is `available` only when Tradier returns a candidate. If every candidate is absent, `missing=['VIX']` and macro is `partial`. |
| `GET https://api.tradier.com/v1/markets/calendar` | Regular-session gate plus versioned schedule archive. Publication/version is separate from session occurrence time. | Operational calendar, not a macro-release or central-bank feed. |
| `GET https://api.tradier.com/v1/markets/history` | Prior-session daily bars and as-of features (prior close/volume, daily-bar realized vol). | `end` is the prior open session; target-day and later bars are excluded. `as_of` is the last returned bar’s 16:00 ET, clamped to receipt so a mid-session rehearsal cannot stamp a close that has not occurred. |
| `GET https://api.tradier.com/v1/markets/options/expirations` | Near-term expirations per underlying. | Bounded to three expirations on or after the session. |
| `GET https://api.tradier.com/v1/markets/options/chains` | Bid/ask/sizes, provider Greeks only if returned, `open_interest` labeled **prior-day**. | Observation timestamp stored. Greeks are never invented. Today's opening OI is not inferred. |
| `GET https://api.tradier.com/v1/accounts/{id}/balances` | Read-only cash / buying power / restrictions. | **Tradier-backed interim portfolio** until Schwab OAuth lands. Account numbers replaced with opaque `acct-` aliases. |
| `GET https://api.tradier.com/v1/accounts/{id}/positions` | Read-only open positions. | Same Tradier interim source; no Schwab. |
| `GET https://api.tradier.com/v1/accounts/{id}/orders` | Read-only working orders. | GET only. No preview/submit. |
| `codex exec` | Model inference on the archived packet/context. | No OpenAI API key on the CLI path. A real host model probe is still required. |

Source of truth: `src/groktrading/research/capture.py`, `collectors.py`, `codex_cli.py`, `opening15.py`, `evaluation.py`. Credential **names** only: `UW_API_TOKEN` / `UW_API_KEY`, `TRADIER_ACCESS_TOKEN`, optional `TRADIER_ACCOUNT_ID`, optional `FINNHUB_API_KEY`. Existing keys stay on the trading host.

**Still missing / not claimed:** Schwab account OAuth, exchange depth, dedicated earnings calendar (print-fields only), UW article bodies, independently reconciled OPRA, live broker orders. Finnhub `/calendar/economic` remains 403 on this plan.

## What can actually run

| Path | Code status | When to run |
| --- | --- | --- |
| Baseline 15-minute selection + fixed-exit paper evaluation | Implemented | **Tuesday 2026-09-08 launch path** and the fallback if post-Tue required coverage is incomplete. Host preflight, real CLI model probe, UW/quote entitlement check, dedicated process launch. Clean `research.cli run` only. `--allow-degraded` is not Tuesday's command. |
| Expanded context + resolver + next-day memory | Collectors + CLI + failure records + prompt registry + **pre-LLM hygiene shortlist** + **selector_v3 shadow** implemented | **Default after Tuesday** (session 2+ / Wed 2026-09-09 onward). `cycle_cli select` writes `candidates.json` (logged gates, budget-derived premium, DTE on every row) and feeds that shortlist to Codex with UW economic calendar, dark pool (per 10 names), option screener, market tide, and political slices via `context.json`. Active selector remains **v2**. Optional `--shadow-v3 --registry` also records a v3 Decision (`selection-shadow-v3.json`) on the same packet/shortlist; it does not replace v2. Required categories must be `available` (depth / dark pool / screener / tide / political may be `missing`). Fall back to baseline or explicit `--allow-degraded` only if required coverage is incomplete. Do not present a degraded run as expanded readiness. Tuesday `research.cli run` is still the packet baseline and does not shortlist. |
| Existing systemd Tuesday template | Present, inactive; runs baseline `research.cli run` | Do **not** enable the timer. It does not invoke `cycle_cli`. |
| Schwab-backed or actual broker order execution | Not part of this path | Paper selections do not become orders. |

Exact command sequences (baseline vs expanded) are written by:

```bash
python -m groktrading.research.cycle_cli day-plan --session 2026-09-08 --out research-runs/2026-09-08/day-plan.json
```

## Tests

`tests/test_research_collectors.py` mocks UW/Tradier/Finnhub HTTP (no live network). Existing opening15 + research_cycle tests remain the plumbing/schema suite. Protocol input gates (distinct real sessions, no synthetic copies, complete baselines) live in `tests/test_opening15_protocol.py`. Registry hash/status/freeze checks live in `tests/test_research_cycle.py`.

```bash
python -m pytest tests/test_research_cycle.py tests/test_opening15.py tests/test_opening15_hygiene.py tests/test_opening15_protocol.py tests/test_research_collectors.py
python -m pytest
python -m ruff check src tests scripts
python -m mypy src/groktrading
python scripts/scan_secrets.py
```

## Concrete host checks and Tuesday launch

Run in the dedicated research checkout using its virtualenv and the host's existing secret-loading mechanism. Keep the host awake/online through 12:56:30 Pacific. No Helsinki service restart is needed.

```bash
codex --version
codex login status
python -m groktrading.research.cli preflight --session 2026-09-08 --output research-runs/preflight-tuesday
python -m groktrading.research.cli model-probe --output research-runs/model-probe-tuesday
```

Preflight confirms connectivity and calendar. It does not prove UW realtime entitlement, ten-stock completeness, Finnhub news entitlement, Tradier index quotes, or fresh option NBBO. Never relabel delayed data as realtime.

### Tuesday launch — clean baseline only

At **06:25 Pacific / 09:25 Eastern on Tuesday September 8**, this is the only authorized
Tuesday command. Do **not** add `--allow-degraded`. Do **not** start the expanded cycle.

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output research-runs/2026-09-08
```

That command is capture → CLI recommendation → quote monitor → paper evaluation (now with
an additive `baselines` block). Archive `packet.json`, `request.json`, `response.json`,
`decision.json`, `observations.jsonl`, `evaluation.json` and any `failure-*.json`.

Passing this repo's unit tests does **not** prove UW realtime entitlement, ten-stock
completeness, Codex model access, or live broker connectivity. Schwab OAuth is not
connected. UW economic calendar / dark pool / screener / tide are expanded LLM
features only; they do not change clean `research.cli run` baseline tape.

### Post-Tuesday default — expanded select (session 2+ / Wed 2026-09-09 onward)

After Tuesday, **default to this expanded sequence** so the LLM sees a hygiene
shortlist (`candidates.json`, gates then judgment) plus UW economic
calendar, dark pool (per 10 names), option screener, market tide, and political
slices through `context.json` + `cycle_cli select`. `research.cli capture` may
write preopen `context.json` from isolated optional collectors (timeouts cannot
abort the baseline tape). Inspect coverage before select. Tuesday itself stays on
clean baseline even if that file exists.

If any **required** category is not `available`, fall back to baseline
`research.cli run` or add explicit `--allow-degraded` and label the gaps. Do not
treat that fallback as expanded readiness.

```bash
python -m groktrading.research.cycle_cli memory --session 2026-09-09 --out research-runs/2026-09-09/memory.json
python -m groktrading.research.cli capture --session 2026-09-09 --output research-runs/2026-09-09
# Read context.json coverage. If any required category is not available:
#   - fall back to: python -m groktrading.research.cli run --session 2026-09-09 --output research-runs/2026-09-09
#   - or: python -m groktrading.research.cycle_cli select ... --allow-degraded
python -m groktrading.research.cycle_cli select --packet research-runs/2026-09-09/packet.json --context research-runs/2026-09-09/context.json --memory research-runs/2026-09-09/memory.json --out research-runs/2026-09-09/selection
python -m groktrading.research.cli monitor --session 2026-09-09 --output research-runs/2026-09-09/selection
python -m groktrading.research.cli report --session 2026-09-09 --output research-runs/2026-09-09/selection
```

Optional shadow compare (does **not** change the active selector or Tuesday
baseline). Seed `prompt-registry.json` first; v2 stays accepted/active, v3 is
shadow. Then score `decision.json` and `selection-shadow-v3.json` on the same
packet and 15:55 ET marks against `evaluation.json` `baselines.abstain`
(always-flat, net 0). Do not promote v3.

```bash
python -m groktrading.research.cycle_cli registry --path research-runs/2026-09-09/prompt-registry.json --seed
python -m groktrading.research.cycle_cli select --packet research-runs/2026-09-09/packet.json --context research-runs/2026-09-09/context.json --memory research-runs/2026-09-09/memory.json --registry research-runs/2026-09-09/prompt-registry.json --out research-runs/2026-09-09/selection --shadow-v3
```

Typical gaps that force baseline or `--allow-degraded`: unused Finnhub (`world_news` missing), unused `TRADIER_ACCOUNT_ID` (`portfolio` missing), VIX still absent after `VIX` / `I:VIX` / `$VIX.X` (macro `partial`). Depth, dark pool, option screener, market tide, and political slices are **optional** and may stay `missing` without `--allow-degraded`.

Do not present Tuesday as a world-news/portfolio-aware full-context experiment. Do not claim a recursive learning loop is already operating. Stages that never produce a decision write `failure-record.json` (no invented PnL). After five paper sessions, run `research.cli protocol` — `continue` is more paper, never live.
