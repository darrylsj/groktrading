# Tuesday execution readiness — 2026-09-08

**Verdict: baseline paper-run code is present; the full expanded-data strategy is not execution-ready.** Host credentials, entitlements, requested-model access and scheduling have not been tested from this workspace. There is no live-order execution path in this experiment.

PR #8 supplies baseline capture/recommend/monitor/evaluate and inactive deployment templates. PR #9's Codex CLI work is merged into that branch. PR #10 is stacked on PR #8 and includes the daily cycle, prompts, integration handoff, this readiness checklist and execution tests. Use the latest PR #10 branch for the combined code. Review/merge #10 into #8, then #8 into main when accepted; do not accidentally deploy main before those changes land.

## Exactly where the model's information comes from

The Python collectors call data APIs using existing host credentials. Codex CLI receives the frozen packet via stdin. The model does not possess UW/Tradier credentials or browse for fresh information during its decision. Archived detail retrieval in the expanded cycle is a local ID lookup, not a new provider request.

| API used in current executable baseline | Data delivered / purpose | Timing and limitation |
| --- | --- | --- |
| `GET https://api.unusualwhales.com/api/option-trades` | Options prints for the ten stocks: contracts, execution prices/sizes, provider-supplied conditions/quote fields. | 09:30–09:45 ET events, polling with capped-window bisection and bounded late retrieval. UW-accessible traffic, not independently reconciled all-OPRA data. |
| `GET https://api.unusualwhales.com/api/news/headlines` | Company headlines supplied to the model. | Preopen sample, up to 100 per stock. Does not continuously capture opening-window news or provide comprehensive world news. |
| `GET https://api.tradier.com/v1/markets/quotes` | Underlying and SPY/QQQ/XLK/XLY context quotes; after the decision, option bid/ask observations for paper PnL. | Underlying snapshots approximately every 30 seconds. Requests `greeks=true`; actual provider fields/entitlements must be checked. This does not fetch a complete option chain or exchange depth. |
| `GET https://api.tradier.com/v1/markets/calendar` | Confirms a full 09:30–16:00 ET session; blocks holidays/early closes. | Operational gate, not an alpha signal. |
| `codex exec` through the operator's authorized CLI login | Model inference using the archived evidence and explicit JSON output schema. | No direct OpenAI API call or OpenAI API key is required for this configured path. A successful real model probe is still required. |

Source of truth: `src/groktrading/research/capture.py`, `codex_cli.py`, `opening15.py` and `evaluation.py`. UW credential aliases: `UW_API_TOKEN` or `UW_API_KEY`; Tradier: `TRADIER_ACCESS_TOKEN`. These names are configuration references, not credentials. Existing keys remain on the trading host.

**Not connected:** Schwab account/positions/orders, full option chains, historical context, broad world news, macro-release/calendar providers and depth. PR #10 defines their `Context` contract and missing-data gates, but does not implement their collectors. Finnhub and other modules elsewhere in the repository are not automatically wired into this decision. The model cannot infer missing connections from a prompt.

## What can actually run

| Path | Code status | Before Tuesday |
| --- | --- | --- |
| Baseline 15-minute selection + fixed-exit paper evaluation | Implemented | Host preflight, real CLI model probe, fresh feed/quote entitlement verification, dedicated process launch. |
| Expanded context + resolver + next-day memory | CLI/reference core and tests implemented | Implement and validate context collectors; connect capture/selection/monitor/resolver scheduling; preserve failure records. Full-context mode rejects missing required categories. |
| Existing systemd Tuesday template | Present, inactive; runs baseline `research.cli run` | Configure research user, checkout, existing secret loading and Codex PATH/login. It does not invoke `cycle_cli` or schedule the resolver. |
| Schwab-backed or actual broker order execution | Not part of this executable research path | Separate integration and execution work; paper selections do not become orders. |

## Test included in PR #10

`tests/test_research_cycle.py::test_cli_boundary_through_evaluation_and_next_day_memory` exercises the real orchestration and schema/archive code across:

1. Codex version/login checks and a frozen archive retrieval request.
2. Schema-constrained selection with broker credentials excluded from subprocess environment and prompt.
3. Post-response simulated ask entry, bid exit and deterministic fee/slippage accounting.
4. Decision/evaluation hash linkage to the resolver.
5. Persisted resolver output and its inclusion in next-session memory.

External Codex and market observations are fixtures. This proves software plumbing, not model profitability or live provider availability. Negative tests reject observed tool calls, malformed JSON and failed CLI processes without producing a decision. A baseline regression test checks relative output paths resolve correctly after changing directories and unknown returned-model identity stays unknown.

```bash
python -m pytest tests/test_research_cycle.py tests/test_opening15.py
python -m pytest
python -m ruff check src tests scripts
python -m mypy src/groktrading
python scripts/scan_secrets.py
```

GitHub CI now triggers for `codex/**` pushes and the PR #8 base branch as well as main, so the stacked PR is tested. Confirm the latest commit's actual CI result on GitHub; local passing tests alone are not a hosted check result.

## Concrete host checks and Tuesday baseline launch

Run in the dedicated research checkout using its virtualenv and the host's existing secret-loading mechanism. Keep the host awake/online through 12:56:30 Pacific. No Helsinki service restart is needed.

```bash
codex --version
codex login status
python -m groktrading.research.cli preflight --session 2026-09-08 --output research-runs/preflight-tuesday
python -m groktrading.research.cli model-probe --output research-runs/model-probe-tuesday
```

The installed CLI must support the invoked flags and the requested model. Login status alone does not establish model access, plan headroom or a particular authentication mode. Inspect the real probe artifacts. Do not replace an unavailable model silently. A missing returned-model field remains unknown, not proof of the requested identity.

Preflight confirms connectivity and calendar but does not prove UW realtime entitlement, ten-stock completeness or fresh option NBBO. Verify those against actual entitled data before labeling the pilot usable; never relabel delayed data as realtime.

At **06:25 Pacific / 09:25 Eastern on Tuesday September 8**:

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output research-runs/2026-09-08
```

That command performs baseline collection → CLI recommendation → quote monitoring → paper evaluation. It does not run the expanded-context selector or nightly resolver. Output directories are exclusive; do not overwrite an earlier attempt. Archive `packet.json`, `request.json`, `response.json`, `decision.json`, `observations.jsonl`, `evaluation.json` and any failure file.

For the full requested strategy, Grok must finish the outstanding collectors and daily orchestration in `GROK_RESEARCH_HANDOFF.md`. If they are not ready, label Tuesday a baseline operational pilot explicitly. Do not present it as testing world-news/portfolio-aware selection or an already operating recursive learning loop.
