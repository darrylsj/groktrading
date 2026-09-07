# Tuesday execution readiness — 2026-09-08

**Verdict: baseline paper-run is executable; expanded Tuesday is executable only when collectors report `available` coverage (except optional depth).** Host credentials, entitlements, requested-model access and scheduling have not been tested from this workspace. There is no live-order execution path in this experiment.

This branch rebases the Opening15 + Codex CLI + research-cycle work onto `main` (PR #9 was merged only into the old stacked base; PR #8/#10 were stacked on `codex/opening15-astra-experiment`). Tuesday should ship from **main**. Do not enable systemd timers. No Helsinki restart. No live orders.

## Exactly where the model's information comes from

The Python collectors call data APIs using existing host credentials. Codex CLI receives the frozen packet and context summaries via stdin. The model does not possess UW/Tradier/Finnhub credentials or browse for fresh information during its decision. Archived detail retrieval is a local ID lookup, not a new provider request.

| API used | Data delivered / purpose | Timing and limitation |
| --- | --- | --- |
| `GET https://api.unusualwhales.com/api/option-trades` | Opening-window prints for the ten stocks, including UW tags/trade codes when present (kept as print / correction / cancellation). | 09:30–09:45 ET with capped-window bisection and one bounded last-minute recheck. UW-accessible tape, not independently reconciled OPRA. Empty tape fails closed. |
| `GET https://api.unusualwhales.com/api/news/headlines` | Company headlines; revisions kept by story/version. Archive detail is the stored payload. | Preopen sample, up to 100 per stock. Official UW skill has **no** article-body endpoint. |
| `GET https://finnhub.io/api/v1/news?category=general` | World / broad-market headlines when `FINNHUB_API_KEY` is present and entitled. | Entitlement-gated. Unused, 401/403, or empty feed → `world_news` coverage **missing** (not fabricated). UW has no world-news path. |
| `GET https://api.tradier.com/v1/markets/quotes` | Underlying, context, and macro snapshots (SPY/QQQ/sectors/`$VIX.X` when the production index is entitled). | Delayed quotes are labeled. Missing instruments (often `$VIX.X`) are listed; that makes macro `partial`. |
| `GET https://api.tradier.com/v1/markets/calendar` | Regular-session gate plus versioned schedule archive. Publication/version is separate from session occurrence time. | Operational calendar, not a macro-release or central-bank feed. |
| `GET https://api.tradier.com/v1/markets/history` | Prior-session daily bars and as-of features (prior close/volume, daily-bar realized vol). | `end` is the prior open session; target-day and later bars are excluded. |
| `GET https://api.tradier.com/v1/markets/options/expirations` | Near-term expirations per underlying. | Bounded to three expirations on or after the session. |
| `GET https://api.tradier.com/v1/markets/options/chains` | Bid/ask/sizes, provider Greeks only if returned, `open_interest` labeled **prior-day**. | Observation timestamp stored. Greeks are never invented. Today's opening OI is not inferred. |
| `GET https://api.tradier.com/v1/accounts/{id}/balances` | Read-only cash / buying power / restrictions. | **Tradier-backed interim portfolio** until Schwab OAuth lands. Account numbers replaced with opaque `acct-` aliases. |
| `GET https://api.tradier.com/v1/accounts/{id}/positions` | Read-only open positions. | Same Tradier interim source; no Schwab. |
| `GET https://api.tradier.com/v1/accounts/{id}/orders` | Read-only working orders. | GET only. No preview/submit. |
| `codex exec` | Model inference on the archived packet/context. | No OpenAI API key on the CLI path. A real host model probe is still required. |

Source of truth: `src/groktrading/research/capture.py`, `collectors.py`, `codex_cli.py`, `opening15.py`, `evaluation.py`. Credential **names** only: `UW_API_TOKEN` / `UW_API_KEY`, `TRADIER_ACCESS_TOKEN`, optional `TRADIER_ACCOUNT_ID`, optional `FINNHUB_API_KEY`. Existing keys stay on the trading host.

**Still missing / not claimed:** Schwab account OAuth, exchange depth, dedicated macro-release calendars, UW article bodies, independently reconciled OPRA, live broker orders.

## What can actually run

| Path | Code status | Before Tuesday |
| --- | --- | --- |
| Baseline 15-minute selection + fixed-exit paper evaluation | Implemented | Host preflight, real CLI model probe, UW/quote entitlement check, dedicated process launch. |
| Expanded context + resolver + next-day memory | Collectors + CLI + failure records + prompt registry stub implemented | Run only if required categories are `available` (depth may be `missing`). Otherwise use baseline `research.cli run` or `cycle_cli select --allow-degraded` and label the gaps. |
| Existing systemd Tuesday template | Present, inactive; runs baseline `research.cli run` | Do **not** enable the timer. It does not invoke `cycle_cli`. |
| Schwab-backed or actual broker order execution | Not part of this path | Paper selections do not become orders. |

Exact command sequences (baseline vs expanded) are written by:

```bash
python -m groktrading.research.cycle_cli day-plan --session 2026-09-08 --out research-runs/2026-09-08/day-plan.json
```

## Tests

`tests/test_research_collectors.py` mocks UW/Tradier/Finnhub HTTP (no live network). Existing opening15 + research_cycle tests remain the plumbing/schema suite.

```bash
python -m pytest tests/test_research_cycle.py tests/test_opening15.py tests/test_research_collectors.py
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

### Baseline (default if expanded coverage is incomplete)

At **06:25 Pacific / 09:25 Eastern on Tuesday September 8**:

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output research-runs/2026-09-08
```

That command is capture → CLI recommendation → quote monitor → paper evaluation. Archive `packet.json`, `request.json`, `response.json`, `decision.json`, `observations.jsonl`, `evaluation.json` and any `failure-record.json`.

### Expanded (only if coverage is available)

`research.cli capture` also writes preopen `context.json` from the collectors above. Inspect coverage before select:

```bash
python -m groktrading.research.cycle_cli memory --session 2026-09-08 --out research-runs/2026-09-08/memory.json
python -m groktrading.research.cli capture --session 2026-09-08 --output research-runs/2026-09-08
# Read context.json coverage. If any required category is not available:
#   - stay on baseline recommend, or
#   - python -m groktrading.research.cycle_cli select ... --allow-degraded
python -m groktrading.research.cycle_cli select --packet research-runs/2026-09-08/packet.json --context research-runs/2026-09-08/context.json --memory research-runs/2026-09-08/memory.json --out research-runs/2026-09-08/selection
```

Typical first-day gaps that force baseline or `--allow-degraded`: unused Finnhub (`world_news` missing), unused `TRADIER_ACCOUNT_ID` (`portfolio` missing), missing `$VIX.X` (macro `partial`). Depth is optional and stays `missing`.

Do not present Tuesday as a world-news/portfolio-aware full-context experiment unless those categories are actually `available`. Do not claim a recursive learning loop is already operating. Stages that never produce a decision write `failure-record.json` (no invented PnL).
