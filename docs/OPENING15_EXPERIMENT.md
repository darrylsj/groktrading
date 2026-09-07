# Opening15: discretionary Codex CLI options experiment

## What this tests

Can an authorized Codex CLI session (requested model `gpt-6-astra`; access must be
verified by a real host probe) examine the first
15 minutes of options prints across ten stocks and select up to three contracts whose
subsequent same-day paper outcomes outperform the available set? There is **no predefined
alpha filter**: no minimum premium, ask-side requirement, sit-2, breakout recipe, or
mandatory trade. The model assesses all ten stocks and may enter none.

**Naming:** the runner is **Codex CLI**, authenticated with the operator's **ChatGPT Pro**
login. `gpt-6-astra` is the requested underlying model string. Do not call this an Astra
chat session or a separate API-key Responses call. The optional
`recommend_backend: "openai_responses"` path remains in code for comparison; it is **not**
the documented Tuesday default.

This is an **isolated research path**, not the existing Grok approve/skip executor. It cannot
place, preview, cancel, or modify broker orders. Model-generated contract/price suggestions
never become `Candidate` objects and never reach the live gate. The existing overnight,
entry-cutoff, cash-reserve and quantity policies are unchanged. Schwab is not required for
this first trial; it remains a separate integration. No Helsinki deployment/restart is done.

## Tuesday, September 8, 2026

| Stage | Eastern | Pacific | UTC |
| --- | --- | --- | --- |
| Start the dedicated research process | 09:25 | 06:25 | 13:25 |
| Observation window starts | 09:30 | 06:30 | 13:30 |
| Market-event cutoff | 09:45 | 06:45 | 13:45 |
| Packet freeze | Actual collection completion, within 3 minutes of cutoff | Same instant | Same instant |
| Recommendations | After the model response arrives; measured, not promised at 09:45 | | |
| Fixed paper exit benchmark | 15:55 | 12:55 | 19:55 |
| Final collection deadline | 15:56:30 | 12:56:30 | 19:56:30 |

The live Tradier calendar must confirm a regular 09:30–16:00 session. Holidays and early
closes fail closed. Launching late or for a different date fails; a historical run cannot be
misrepresented as prospective. Example config: AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA,
AMD, AVGO, PLTR; context SPY, QQQ, XLK, XLY. Change the example **before** the open if needed.

## Setup on the machine holding the existing keys

Use a dedicated checkout, e.g. `/opt/groktrading-research`, or a separate local Mac checkout.
Do not copy this over `/opt/trading-desk`, modify its units, or restart Helsinki services.
A Mac must remain awake and connected until collection ends. An existing always-on host
is preferable. No extra paid data provider is required for the first trial.

```bash
git clone --branch main https://github.com/darrylsj/groktrading.git groktrading-research
cd groktrading-research
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest tests/test_opening15.py
python -m groktrading.research.cli demo --output research-runs/offline-demo
```

Install Codex CLI **≥ 0.153.0** on the same host and keep `codex` on `PATH`. Use the official
package name `@openai/codex` (not the unrelated npm package `codex`):

```bash
npm install -g @openai/codex
# or: brew install --cask codex
# or: curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
codex login
codex login status
```

`codex login` must use the **ChatGPT Pro** account (the $200 plan allowance). Do **not**
pass `--with-api-key` / stdin API key for this experiment. `OPENAI_API_KEY` is **not**
required when `recommend_backend` is `codex_cli` (the example default). The recommend
subprocess strips API/broker tokens from its environment so Codex uses the CLI session.

Existing **capture** credentials must be available in the **process environment**:

- `UW_API_TOKEN`, or the Helsinki-compatible alias `UW_API_KEY`.
- `TRADIER_ACCESS_TOKEN` for production market data; `TRADIER_ENV=production` if set.
- No broker account ID is needed. No key is embedded in config, CLI arguments, Git, or model input.
- `OPENAI_API_KEY` is required only if the operator explicitly sets
  `recommend_backend` to `openai_responses`.

Use the host's existing secret-loading mechanism. The program does not search for secrets,
copy env files, alter them, or echo credentials. Its URLs are fixed to the official providers.
A proxy-enabled host may need `pip install 'httpx[socks]'` if its proxy uses SOCKS.

### Before Tuesday: host acceptance checks

```bash
codex --version
codex login status
python -m groktrading.research.cli preflight --session 2026-09-08 --output research-runs/preflight
python -m groktrading.research.cli model-probe --output research-runs/model-probe
```

`preflight` makes read-only UW/Tradier calls, checks the target market calendar, records
`codex --version`, and verifies `codex login status` (ChatGPT CLI session). It does **not**
call the OpenAI model catalog with an API key when the backend is `codex_cli`.
`model-probe` makes **one small Codex CLI `exec`**, using the configured model, reasoning
effort and `--output-schema` JSON. That is a ChatGPT-plan / connectivity / schema check,
never a trading-performance observation. It records the CLI version, returned model and
usage. Neither command sends orders. Each output path is exclusive: preserve failed
attempts and use a separately named directory for a new check.

Before the first prospective run, the operator must verify:

1. Codex CLI is ≥ 0.153.0, on `PATH`, and `codex login status` succeeds for the ChatGPT
   Pro account. `model-probe` must complete against the requested model (`gpt-6-astra`).
   No automatic fallback model. Record the returned model string if present; absence is
   unknown. Do not treat a catalog listing as a successful probe.
2. UW access includes current individual option trades. An alerts-only or 15-minute-delayed
   entitlement does not satisfy this experiment. Capture rejects an empty opening tape.
3. Tradier production option quotes are entitled and current. The weekend preflight does
   not establish Tuesday's data freshness. Paper marks require provider timestamps and sizes.
4. UW and Tradier quotas have room **in addition to the existing trading desk's usage**.
   Each research feed defaults to at most 90 requests/minute; lower the config to the spare
   quota. These local limits do not coordinate with other processes using the same token.
5. The host can fit the actual packet into the model's context and account token-rate limit.
   The 4 MB request cap is a byte/spend guard, **not a guaranteed token count**. The model
   must accept the whole packet; oversized input fails visibly without dropping stocks/prints.
6. Replace example commission/slippage assumptions with the intended evaluation assumptions.
   Defaults are **$0.65 per contract per side + $0.01/share slippage per side**, not fee quotes.
   API pricing defaults to unknown (zeros); set both per-million fields to appropriate rates
   if an approximate API-cost deduction is desired. Hosting/data costs remain separately owed.

No credentials were accessible in the build environment. Only mocked API and synthetic
end-to-end tests have been run there. These host checks remain necessary before calling the
experiment ready for unattended use.

### Day-1 vs day-2+ default

| Session | Default | Fallback |
| --- | --- | --- |
| **Tue 2026-09-08** (session 1) | Clean baseline `research.cli run` (packet recommend) | Do **not** use `--allow-degraded`. Do **not** claim expanded readiness. |
| **Wed 2026-09-09 onward** (session 2+) | **Expanded select** (`context.json` + `cycle_cli select`) so the LLM gets a **hygiene shortlist** (deterministic gates, then judgment) plus UW economic calendar, dark pool (per 10 names), option screener, market tide, and political slices | Baseline `research.cli run`, or explicit `--allow-degraded`, only if required coverage is incomplete |

### Tuesday launch

Tuesday 2026-09-08 is an **operational paper pilot on the clean baseline**. It is **not**
`--allow-degraded` and is **not** a claim of full expanded-strategy readiness. Passing
unit tests is not live entitlement proof.

At **09:25 Eastern / 06:25 Pacific**, from the dedicated checkout with credentials loaded:

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output research-runs/2026-09-08
```

This one process captures, freezes, requests the Codex CLI decision, and monitors paper
outcomes. `codex` must remain on `PATH` and logged in for the whole recommend step.
Keep it running until 15:56:30 ET. It does not install cron, enable units, schedule itself,
or restart anything. The included `deploy/examples/groktrading-opening15.*` files are optional
**inactive templates** for an operator to adapt on a dedicated research host. Approval to
build this package does not claim those templates have been installed or enabled.

Separate commands are available for troubleshooting: `capture`, `recommend`, `monitor`,
`report`. `recommend` accepts only a prospective packet frozen within the previous 3 minutes.
A model timeout/refusal/invalid decision is recorded as a failed attempt; there is no automatic
second opinion or retry. A monitor failure keeps its partial observations. Use `report` on
those observations; missing exits produce null, not a fabricated zero or a win.

```bash
python -m groktrading.research.cli report --output research-runs/2026-09-08
```

### Post-Tuesday default (session 2+ / Wed 2026-09-09 onward)

After Tuesday, **default to expanded select**. `research.cli capture` still writes the
baseline packet (and may write preopen `context.json`); selection then goes through
`cycle_cli select`. That path runs **universe hygiene first** (logged gates, budget-derived
premium cap, DTE recorded on every row) and writes `candidates.json`; Codex sees that
curated shortlist, not the whole chain. The selector prompt is not given computable refuse
rules — architecture is **gates then judgment**. Context still includes UW economic
calendar, dark pool (per 10 names), option screener, market tide, and political slices.
Inspect `context.json` coverage first. Fall back to baseline `research.cli run` or add
`--allow-degraded` only if a **required** category is not `available`.
Tuesday itself stays on clean `research.cli run` (packet baseline; no shortlist).

```bash
python -m groktrading.research.cycle_cli memory --session 2026-09-09 --out research-runs/2026-09-09/memory.json
python -m groktrading.research.cli capture --session 2026-09-09 --output research-runs/2026-09-09
python -m groktrading.research.cycle_cli select --packet research-runs/2026-09-09/packet.json --context research-runs/2026-09-09/context.json --memory research-runs/2026-09-09/memory.json --out research-runs/2026-09-09/selection
python -m groktrading.research.cli monitor --session 2026-09-09 --output research-runs/2026-09-09/selection
python -m groktrading.research.cli report --session 2026-09-09 --output research-runs/2026-09-09/selection
```

Exact sequences (baseline vs expanded) also come from
`python -m groktrading.research.cycle_cli day-plan --session 2026-09-09 --out research-runs/2026-09-09/day-plan.json`.
See [Tuesday execution readiness](TUESDAY_EXECUTION_READINESS.md).

## Evidence and coverage

- `/api/option-trades`: all UW-returned individual prints for the frozen stock universe,
  every strike/expiry, no directional or size filters. Requests set `include_agg_trades=false`.
  Capped 500-row ranges are recursively split by time with overlapping boundaries and ID
  deduplication. A saturated timestamp, request cap, or deadline causes a visible failure.
- UW raw response pages are archived with receive times. Packet records the actual knowledge
  cutoff. Final-minute requery catches some late reports; this is **not an OPRA reconciliation**
  or a guarantee of every correction across the full window. Cancellations are retained.
- Tradier stock snapshots every 30 seconds during the window, including market/sector context.
  These are sampled prints/quotes, not tick-complete equity data or reconstructed minute OHLC.
  Mandatory ten-stock coverage cannot contain a gap over 90 seconds. No post-cutoff stock
  snapshot enters the packet even if its last trade timestamp predates the cutoff.
- Up to 100 preopen UW headlines per stock. This is bounded context, not exhaustive news or
  a complete earnings calendar. Earnings/date fields in print metadata remain available.
  Expanded/optional collectors may also archive UW economic calendar, dark-pool prints
  for the ten names, a small option-screener slice, and session-level market tide.
  Those files are not part of the baseline tape. Finnhub `/calendar/economic` is unused
  (403 on this plan). Empty UW `data` is recorded as available with 0 events.
- Option NBBO, sizes, Greeks, IV, conditions, and underlying price are included where UW
  supplies them at each print. Missing fields remain unknown. There is no claim of every
  option quote update or full chains for contracts that never printed.
- Model input dictionary-encodes columns without selecting or dropping events. Potentially
  retrieval-time cumulative fields (`volume`, side-volume totals) are quarantined from model
  input to avoid contamination after 09:45. Raw archive retains them. Opening totals can be
  derived from each print's size and price. News/provider text is treated as untrusted data.

## Recommendations and evaluation

The response includes ten stock assessments and at most three ranked contracts, each with
enter/watch, max entry price, validity duration, thesis, alternative explanation, invalidation,
proposed exit, qualitative confidence, and real evidence IDs. Output validation rejects
invented contracts, unknown evidence, duplicate picks and missing stock assessments.

**Architecture (locked):** deterministic filters run **before** the LLM and are logged
(which gate fired). The LLM only makes judgment calls (thesis coherence, cite-or-abstain).
Computable refuse rules are not put into the selector prompt. Tuesday `research.cli run`
stays the packet baseline. Post-Tue expanded `cycle_cli select` feeds Codex the hygiene
shortlist in `candidates.json` after those gates.

The strategy prompt is versioned. Packet, request and response timestamps/hashes are recorded.
Codex CLI `exec` is invoked once per run directory: prompt on stdin (`-`),
`--output-schema` for the Decision JSON, `--output-last-message`, `--json` events,
`--sandbox read-only`, `--ephemeral` (no session rollout files; `store=false` spirit),
`--ignore-user-config` (no user MCP / tools config), no `--search`, no `--yolo`.
No broker credentials in the prompt. No automatic retry or fallback model.
Request metadata records `codex --version`, argv, prompt hash and schema. Returned
model, response events and usage are kept. The Responses API backend is unused unless
`recommend_backend` is set to `openai_responses`.

Paper entries require the first eligible **post-response** Tradier production ask, a post-response
ask timestamp, fresh bid/ask, displayed sizes >=1, and price plus assumed slippage <= model limit.
No mid-price fills. Validity expires 15–300 seconds after response receipt, as the model specifies.
One hypothetical contract per enter recommendation; watch/unselected contracts are tracked only
as counterfactual observations. They do not spend account cash and are not an executable portfolio.
Ranked quotes are polled ahead of the comparison universe each cycle; a large universe can slow
sampling and miss entries. Missing fills remain explicit. There is no option-order submission.

Fixed-exit paper P&L is `(exit bid - exit slippage - entry ask - entry slippage) * 100 - 2 * fee`.
The exit must have a provider bid update at/after 15:55 ET and be received within 90 seconds.
Missing exits leave aggregate selected P&L null. Best/worst observed bids are **sampled**, not
continuous MFE/MAE or guaranteed stop/target touches. Model-proposed prose exits are recorded
for a separate experiment and **not automatically executed or scored in this first version**.

API cost estimates are optional, exclude caching adjustments, and do not include data/hosting.
Do not describe quote-based simulated outcomes as broker-verified fills or realized profits.
Preserve every no-trade, failed, missed and losing day. Multiple prints on one move are not
independent experiments. This first Tuesday is an operational trial, not proof of an edge.

## Output files (private, ignored)

| File | Purpose |
| --- | --- |
| `config.json` | Universe and assumptions frozen before open |
| `raw/flow-*.json`, `raw/stocks-*.json` | Provider response pages, stock snapshots and receive times |
| `packet.json` | Frozen validated evidence, coverage and limitations |
| `candidates.json` | Expanded/select only: pre-LLM hygiene shortlist + structured rejects (not written by Tuesday `research.cli run`) |
| `request.json` | Exact prompt/config/input plus hashes, start time, backend, and `codex --version` |
| `opening15-schema.json` | Decision JSON Schema passed to `codex exec --output-schema` |
| `response.json` | Raw Codex JSONL/stderr or Responses body, plus receipt time |
| `decision.json` | Validated recommendations; never an order instruction |
| `observations.jsonl` | Subsequent quotes for selected and unselected contracts |
| `evaluation.json` | Paper outcomes and unresolved/missing states |
| `failure-*.json` | Failed attempts, safe diagnostic, stage and time |

Do not commit licensed provider data or private run artifacts. Outputs under `research-runs/`
are ignored. File permissions are private. Do not enable automatic retry/restart of the daily
run: duplicate attempts compromise the frozen first decision.

## Sources used for integration

- [Codex CLI reference](https://developers.openai.com/codex/cli/reference) (`codex exec`,
  `--output-schema`, `--output-last-message`, `--json`, `--ephemeral`, `codex login status`)
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) (requested
  model string; Codex may report a GPT-6 Pro / Astra variant)
- [Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  (optional `openai_responses` backend only)
- [UW individual option trades](https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.index)
- [UW news](https://api.unusualwhales.com/docs/operations/PublicApi.NewsController.headlines)
- [UW skill / endpoint index](https://unusualwhales.com/skill.md) (dark pool, screener, market tide, congress)
- [Tradier quotes](https://docs.tradier.com/reference/brokerage-api-markets-get-quotes)
- [Tradier calendar](https://docs.tradier.com/reference/brokerage-api-markets-get-calendar)

## Expanded context, daily memory and publication experiment

The CLI-only reference extension and remaining provider integration work are described in
[Grok research handoff](GROK_RESEARCH_HANDOFF.md). The selection, archived retrieval and
resolver prompts live in `src/groktrading/research/prompts/`.
[Related work and prospective protocol](ARXIV_RESEARCH_PROTOCOL.md) identifies relevant
arXiv papers and specifies how to test whether feedback improves next-day decisions.
The expanded extension is not a claim of connected feeds, completed deployment or profit.

For exact connected APIs, current gaps and the execution test, see
[Tuesday execution readiness](TUESDAY_EXECUTION_READINESS.md).
After five distinct real paper sessions, apply [Opening15 decision protocol](OPENING15_DECISION_PROTOCOL.md)
(`insufficient | rejected | kill | continue | inconclusive`). Duplicate or synthetic
copies are `rejected`. `continue` means more paper only.
