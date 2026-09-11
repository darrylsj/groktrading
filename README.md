# GrokTrading

**Public reference package** intended for **external audit** (including OpenAI review under `darrylsj`). This is **not financial advice**. Secret-free **reference and deployment package** for a Helsinki-hosted, Grok-assisted options desk. Default mode is **signals-only**. Paper is explicit. **Live orders are never placed by default.** Live trading is **operator-gated**.

This git repository is **not deployed** by being merged; see [docs/OBSERVED_DEPLOYMENT.md](docs/OBSERVED_DEPLOYMENT.md) for host observations kept separate from [deploy/examples](deploy/examples).

This software does **not** promise trading success. It must **not** invent prices or P&L.

**Auditor pack:** [docs/OPENAI_AUDIT_BRIEF.md](docs/OPENAI_AUDIT_BRIEF.md) · [docs/CLAUDE_AUDIT.md](docs/CLAUDE_AUDIT.md) · **WebSockets:** [docs/WEBSOCKETS.md](docs/WEBSOCKETS.md) · **Safety:** [docs/SAFETY.md](docs/SAFETY.md) · **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Opening15 experiment (paper research, Codex CLI)

A separate, discretionary **first-15-minute / ten-stock** experiment is available for Tuesday,
September 8, 2026. Tuesday is a **clean baseline paper pilot** (`research.cli run`), not
`--allow-degraded` and not expanded-strategy readiness. Post-Tue expanded select feeds the
LLM a **hygiene shortlist** after deterministic gates (judgment only; no computable refuse
rules in the selector prompt). The recommend step runs through
**OpenAI Codex CLI** using the operator's **ChatGPT Pro** login (not `OPENAI_API_KEY` /
Responses API). Capture/monitor/report stay quote-only. There is **no broker order path**.
Protocol: **[Opening15 decision protocol](docs/OPENING15_DECISION_PROTOCOL.md)**. Launch:
**[Tuesday execution readiness](docs/TUESDAY_EXECUTION_READINESS.md)** and
**[Opening15 runbook](docs/OPENING15_EXPERIMENT.md)**.

## Operator mandate (YOLO — capital expansion)

This is Darryl’s **YOLO account**. The goal is **capital expansion**, not capital preservation. Do **not** frame the desk as a “don’t lose” or preservation book.

| Frame | Meaning |
| --- | --- |
| **Planning / selection / multi-lift sizing** | **$25,000** desk capital |
| **Live Tradier fills** | May still be **cash-constrained** on a **smaller funded balance** until the $25k is deposited |
| **Do not confuse** | Planning capital ≠ current broker equity. Auditors must not assume the live book already holds $25k. |

**Milestone spirit:** grow aggressively within the live-card risk rails (cash/equity ≥20% / max deploy 80%, overnight OK, 12:30 PT = new-entry cutoff only). Encoded gate math stays **one-lot** (`qty == 1`); $25k is the planning frame, not a claim that the funded account is already $25k.

**Historical note (not the primary frame):** the live funded book started small (early operator notes used on the order of hundreds of dollars; first milestone $1,000, then $10,000). Planning capital is **$25k**.

## Live card (authoritative)

Any older ≥50% cash floor, flatten-at-12:30, or no-overnight policy in this tree is stale. Use this card:

- **Overnight long options: ALLOWED**
- **12:30 PT = NEW-ENTRY CUTOFF ONLY** (not a forced flatten). Fail-closed = no new risk; continue monitoring existing positions
- **Cash/equity ≥20%** at all times as a pre-entry reserve / **max deploy 80%**
- **One-lot preference (~$200)** — no hard concurrent-position caps, no daily-loser circuit breaker
- **Live orders must NEVER be triggered by WebSocket alone**; final gates recheck fresh Tradier **production** quotes
- **Grok/LLM is outside the broker execution boundary**: approve/skip on frozen facts only; never set OCC, qty, limit, account, or order action

OpenAI P0.4 flatten-everything / no-overnight is **rejected**. Full checklist: [docs/SAFETY.md](docs/SAFETY.md).

## Helsinki vs this package

Verified 2026-09-05 SSH map (authoritative ops context, not a claim this commit is deployed):

| | Live Helsinki | This package |
| --- | --- | --- |
| Tree | Hand-built `/opt/trading-desk` (no `.git`) | Git repo; installer default `/opt/groktrading` |
| Units | `trading-desk-tape.service` (`ws_tape.py`) + `trading-desk-finnhub.service` | Example `groktrading-*.service` |
| Orders | **No** preview→submit. Webhooks: `sit_match`, `in_position`, `cash_up` (`entry_cutoff_only_no_flatten`), `day_win_target` (`auto_flatten: false`) | Stub-safe `OrderMachine` on the Grok consumer side |
| Webhooks | In-memory debounce ~90s (weekend same-digest spam) | SQLite WAL inbox/outbox + AH/weekend digest coalesce |

GitHub `main` was `e297a0af…` at map time. Package hardening ships here first. Copy debounce/idempotency onto Helsinki only after an **operator-authorized** restart.

## Helsinki sensor farm

Helsinki is an **exchange-grade sensor farm + append-only research DB**. It is
**always-on listen** with API keys on the host. It is **not** a decision engine
and it is **not** an order router.

| Role | Who |
| --- | --- |
| Listen / normalize / freshness / filter / signed webhook | **Helsinki** (no LLM) |
| Decide / place orders | **Grok Bot only** |
| Hot research window | SQLite / day packs on limited disk (**7–14 days**) |
| Cold history | **Box Trading Desk Archive** (`daily/YYYY-MM-DD/…`, no secrets) |

- **No LLM on Helsinki.** No 10k-universe spray. **WebSocket → orders is forbidden.**
- **P0 (merged):** append-only `flow_ledger`, Tradier **account-events**
  position-truth helper, Box cold-rotate, `sit_match` freshness (#24/#25).
- **P1/P2 (this package):** helpers only — UW **flow-alerts** poller (emit on
  **new alert id**), tide + optional net-prem `tide_state.json`, bounded Tradier quote
  interest, thin RTH screener snapshot, shadow minute-marks, `UW_WS_URL`
  probe stub, Finnhub watch widen + overnight news, replay scorecard
  skeleton. Package CLIs stay **offline skeletons**.
- **Host companions (repo artifacts, operator-wired):** live **urllib**
  pollers matching Helsinki 2026-09-08 under `scripts/` (`helsinki_http.py`
  `UrllibHttp` — not httpx; `flow_ledger_companion.py`,
  `flow_alerts_companion.py`, `tide_companion.py`, `screener_companion.py`,
  `quote_interest_companion.py`) plus example units in
  `deploy/examples/systemd/host-companions/`. Example units use
  **`User=tradingdesk`** (not root) and omit webhook env on units that
  never emit webhooks. urllib GETs do not follow redirects (Authorization
  is not re-sent). **`install_helsinki.sh` does not copy, enable, or start
  them.** **emit_sit_match=False.** Flow-alerts material is local JSONL
  only (no Grok webhook). Authorization Bearer is runtime env only. Not a
  claim these processes are live on Helsinki.
- **`sit_match` freshness + producer rate (live Helsinki 2026-09-11):**
  **Root cause:** ~20+/min POSTs queued Cursor wakes (p50 ~16m) while HTTP
  itself was always ~0.5–0.7s. UW `option-trades` `executed_at` age ≤
  `SIT_MATCH_MAX_AGE_SEC` (default **60s**). Missing/unparseable/stale → do not
  emit. `created_at` / `timestamp` / inbound `print_age_sec` are **not** the
  execution clock. `print_age_sec` is overwritten from `executed_at` at POST
  and cannot claim “fresh” against a minutes-old print. Re-check immediately
  before HTTP (`sit_match_stale_at_post`); stamp `emitted_at`. **OCC-only**
  debounce (not per OCC|`executed_at` print) plus `SIT_MATCH_MIN_INTERVAL_SEC`
  default **60** (15 still outran Cursor ~22s wakes) → POSTs ≤1/min. Mute:
  `SIT_MATCH_WEBHOOK=0` and/or mute file
  `/opt/trading-desk/state/sit_match_webhook_muted` → `sit_match_webhook_muted`.
  Call `prepare_sit_match_outbound` on the host tape (`ws_tape.py`) at POST,
  not at detect. Host contract: `deploy/examples/helsinki/ws_tape_sit_match.py`.
  Simulate: `scripts/simulate_sit_match_webhook.py` (local 127.0.0.1 only; does
  not read `grok-webhook.env`). Non-finite limits (`inf` / `NaN`) fail closed.
  Package: `groktrading.sit_match`. Ledger may still **store** stale or
  clock-less prints for research (`groktrading.flow_ledger`); freshness-sensitive
  use (sit_match, quote interest) fail-closes. Flow-alerts reuse the same gate
  when a row is sit_match-shaped.

  **Unmute checklist (operator):** remove the mute file; set `SIT_MATCH_WEBHOOK=1`
  or unset it; restart `trading-desk-tape` only with authorization; journal
  must not log `sit_match_webhook_muted`; POST rate ≤1/min.

  **Verify:** sim POST RTT ≪1s (`post_ms` ~0.5s on the desk, ~17ms local);
  live POST rate ≤1/min; wake lag should fall after the old Cursor queue
  drains (residual ~6m was backlog, not HTTP).
- **Account-events WS** (`wss://ws.tradier.com`): **position truth** only —
  fills/cancels keep `in_position` honest after flatten. Never a submit path.
  Package helper: `groktrading.feeds.account_events`. Example unit
  `groktrading-account-events.service` is **files only** (not enabled by
  `install_helsinki.sh`). Do **not** auto-start it.
- **Box cold-rotate:** `scripts/box_cold_rotate.py` + [docs/BOX_ARCHIVE.md](docs/BOX_ARCHIVE.md).
  Deny-list blocks `.env` / tokens / credentials, **symlinks**, paths
  outside the archive root, and non-export suffixes. Delete only after
  verified upload or `--confirm-delete`.
- **Hot retention:** `scripts/hot_ledger_retain.py` purges `uw_flow.sqlite`
  after a verified Box export (7–14 day window) and bounds companion JSONL.
  Example timer/cron under `deploy/examples/systemd/hot-retention/` — do
  **not** enable from this repo. Replay scorecard counts are **not**
  performance evidence.
- **Recovery:** SSH + systemd on the host. **Merging this repo does not
  deploy Helsinki** and does **not** restart live units. **Grok Update Computer does not rebuild Helsinki.** After merge, an operator must copy
  helpers into the live tape if needed and **wire companion units
  separately** (copy `deploy/examples/systemd/host-companions/` yourself).
  `ws_tape.py` stays host-owned. Account-events stays **files-only /
  disabled**. **Merge ≠ Helsinki restart.**

## Architecture

![GrokTrading architecture](docs/groktrading-architecture.png)

**Outside APIs** supply Unusual Whales options flow, Finnhub stock trades and news, and Tradier production quotes, balances, positions, orders, and account events; Tradier sandbox is paper-lifecycle only (15-minute delayed data). **Helsinki** is always-on and non-LLM: `trading-desk-tape` and `trading-desk-finnhub` write tape JSON, deterministic filters apply sit-2 / matching ask / skip already-run / 20% cash reserve, a signed webhook outbox emits material events only, and a nightly cron precomputes print scores. The **Grok Bot** writes thesis / approve-skip on **frozen facts**, then a deterministic final gate (fresh Tradier OCC quote TTL, quantity 1, duplicates, 12:30 new-entry cutoff) before preview → submit; routines and the audit pack (`LESSONS`, `trades.jsonl`, `CHANGELOG`) stay local. The **Passive Reviewer** reads that audit pack **outside** the active loop and has no control or order permissions.

**Hard rules**

- **Finnhub ≠ option NBBO.** Do not gate option limit prices on Finnhub ticks.
- **WebSocket never places orders.**
- Matching ask uses a **Tradier production** quote.
- Maintain **≥20% cash/equity** (max deploy 80%). Overnight longs allowed.
- **12:30 PT** new-entry cutoff only (America/Los_Angeles). Not a flatten.
- **Sandbox ≠ live fill evidence.** Production NBBO is pricing truth.

Legend and the same chart: [docs/ARCHITECTURE_DIAGRAM.md](docs/ARCHITECTURE_DIAGRAM.md). Longer write-up: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). WebSocket / webhook sequence (print → filter → webhook → Grok → gate → preview→submit): [docs/WEBSOCKETS.md](docs/WEBSOCKETS.md).

```mermaid
flowchart LR
  subgraph Outside["Outside World APIs"]
    UW["Unusual Whales\nREST options flow\nask-side prints"]
    FH["Finnhub\nWS stock trades\nREST news / earnings"]
    TP["Tradier Production\nquotes · balances\npositions · orders\naccount events"]
    TS["Tradier Sandbox\npaper lifecycle only\n15-min delayed data"]
  end
  subgraph Helsinki["Helsinki — always-on, non-LLM"]
    TAPE["trading-desk-tape\nUW + Tradier → live_tape.json"]
    FHSVC["trading-desk-finnhub\nWS → finnhub_tape.json"]
    FILT["Deterministic filters\nsit-2 · matching ask\nskip already-run · 20% cash"]
    HOOK["Signed webhook outbox\nmaterial events only"]
    NIGHT["Nightly print scorer cron"]
  end
  subgraph Grok["Grok Bot computer — LLM"]
    LLM["Thesis / approve-skip\non frozen facts only"]
    GATE["Final gate\nfresh Tradier OCC quote TTL\nqty=1 · duplicates\n12:30 new-entry cutoff"]
    EXEC["Preview → submit\nlive orders"]
    AUDIT["Audit pack\nLESSONS · trades.jsonl\nCHANGELOG"]
    ROUT["Routines\nopen · 15-min · close\nafter-hours · overnight"]
  end
  REV["Passive Trade Reviewer\noutside active loop"]
  UW --> TAPE
  FH --> FHSVC
  TP --> TAPE
  TP --> GATE
  TAPE --> FILT
  FHSVC --> FILT
  FILT --> HOOK
  HOOK -->|"sit_match / cash_up"| LLM
  LLM --> GATE
  GATE --> EXEC
  EXEC -->|"live"| TP
  EXEC -.->|"paper verify"| TS
  GATE --> AUDIT
  ROUT --> AUDIT
  NIGHT --> AUDIT
  AUDIT --> REV
```

Helsinki **ingests**, **normalizes**, enforces **freshness**, **filters**, **pushes a signed webhook**, and keeps **paper/live env files separate**. Units are **systemd** with **0600** env files. There is **no LLM polling**. The **LLM thesis / approve-skip** path works on **frozen facts only** and must not call Tradier. The **deterministic final gate / preview→submit executor** on the Grok Bot computer **does** use Tradier production for fresh OCC quotes and live orders. The **passive reviewer** is outside the runtime loop ([docs/REVIEWER.md](docs/REVIEWER.md)).

## What this is

A typed Python package under `src/groktrading` with:

- Finnhub stock-trade WebSocket helpers (reconnect/backoff, bounded watchlist, atomic redacted JSON, freshness/health, REST probe)
- Generic Unusual Whales and Tradier clients (timeouts and stale data **fail closed**, dependency injection)
- Candidate + deterministic gate (sit-2, matching ask, already-run, no first-red, TTL, ≥20% cash reserve, quantity 1, broker-authoritative duplicates, clock, 12:30 PT entry-cutoff)
- Production quote gate (OCC, delayed, provider bid/ask dates, spread, no-chase; sandbox/synthetic cannot pass live)
- Preview→submit order state machine (immutable payload, no blind retry; stub-safe)
- Signed webhook sender plus durable SQLite WAL inbox/outbox idempotency (AH/weekend digest coalesce)
- LLM interface: **approve/skip + thesis** from assembled facts only; **no broker access**; never sets OCC/qty/limit/account/order action
- Signals-only executor stub and explicit live gating (WebSocket cannot submit live)
- Paper recorder/reconciler (production NBBO truth vs sandbox delayed fills, `signal_id`, preview-before-order, same-session paper file)
- 12:30 PT new-entry cutoff policy (not a forced flatten; overnight long options allowed; alert if cutoff cancel fails)
- systemd/env **examples**, portable host installer (`scripts/install_helsinki.sh`), JSON Schema, CI, tests

## Persistent logs

Secret-free, append-only records. Rules: [docs/LOGS.md](docs/LOGS.md).

| Path | Role |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | Development log (Keep a Changelog; America/Los_Angeles dates) |
| [logs/trades.jsonl](logs/trades.jsonl) | Live trade journal (one JSON object per round-trip; open lot allowed) |

`thinking.jsonl` is the mixed decision tape on the host. It is **not** committed and is **not** a substitute for either file above. n=3 is not an edge. Never commit secrets.

## What this is not

- A claim that Helsinki already runs **this** commit
- A Backtrader/LEAN/Lumibot application (see research notes below)
- A place for API tokens, webhook secrets, or host IPs

## Operating modes

| Mode | Default | Orders |
| --- | --- | --- |
| `signals_only` | Yes | Never |
| `paper` | No | Tradier sandbox after preview + gate |
| `live` | No | Requires explicit enablement; **still blocked** from WebSocket callbacks |

Live policy encoded in the gate: **one-lot options**, **sit-2**, **matching ask**, **skip already-run**, **no first-red**, **no spray**, cash/equity **≥20%** at all times (max deploy 80%), **overnight long options allowed**, **12:30 PT new-entry cutoff only** (not a forced flatten). The final gate rechecks a **fresh Tradier production option quote** (provider timestamps, OCC, delayed flag), TTL, matching ask, buying power/cash/reserve, quantity **exactly 1**, duplicate/working/in-position from the broker snapshot, market hours, and the 12:30 new-entry cutoff. Candidate booleans cannot pass live alone.

## API roles and limitations

### Finnhub

- **REST** (plan-entitled): quote, news, earnings, fundamentals, sentiment — `https://finnhub.io/api/v1`.
- **WebSocket**: `wss://ws.finnhub.io` for **stock trades / last prints**.
- **Finnhub does not provide option NBBO.** Do not gate option limit prices on Finnhub ticks.
- **Plan limits vary.** Missing entitlements fail closed; do not fabricate series.

Docs: https://finnhub.io/docs/api

### Unusual Whales

- Live **options flow / option-trades** and published **ask-side, premium, volume, OI** fields.
- **Configurable base URL** (default `https://api.unusualwhales.com`).
- Docs: https://api.unusualwhales.com/ and https://unusualwhales.com/skill.md
- This repo does **not** invent extra endpoint paths. Operators pass documented paths into the generic client.

### Tradier

| | Production | Sandbox |
| --- | --- | --- |
| REST | `https://api.tradier.com/v1/` | `https://sandbox.tradier.com/v1/` |
| Market stream | `https://stream.tradier.com/v1/` | **None** (no delayed MD stream) |
| Account events | `wss://ws.tradier.com` | `wss://sandbox-ws.tradier.com` |

Surfaces used conceptually: **quotes, chains, balances, positions, orders, preview, clock, account events**.

Opening15 macro VIX is requested as **`VIX`**, then **`I:VIX`**, then **`$VIX.X`**. Coverage is available only when Tradier returns one of those; the collector does not invent an index print. Sandbox has **no indices**.

Sandbox (official market-data / FAQ docs): **~15-minute delayed** data, **no market-data stream**, **no Greeks**, **no indices**, **no tick timesales**; **account-event streaming is available**. **Production NBBO is pricing truth.**

Docs: https://docs.tradier.com/docs/endpoints

### Grok

Thesis and **approve/skip** from assembled facts only. Never invent market data. The LLM must not hold broker credentials or call Tradier. Fresh OCC quotes and live orders go through the **deterministic gate / executor**, which **does** call Tradier production.

## Install and test

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest
mypy src/groktrading
python scripts/scan_secrets.py
```

## Rebuild / new host

Portable, secret-free host install (new VPS or parallel rebuild next to live Helsinki): **[docs/DEPLOY.md](docs/DEPLOY.md)**. Different-provider full rebuild (copy secrets by key name, recreate units/crons, cutover): **[docs/REBUILD_NEW_PROVIDER.md](docs/REBUILD_NEW_PROVIDER.md)**.

```bash
# files only — no enable, no start, no secrets, no live trading
sudo ./scripts/install_helsinki.sh --dry-run
sudo ./scripts/install_helsinki.sh
```

Defaults: `INSTALL_ROOT=/opt/groktrading` (not legacy `/opt/trading-desk`), package-named units `groktrading-*.service` (not `trading-desk-*.service`), `signals_only`. Merging this repo still does **not** mean Helsinki runs this commit.

## Deployment examples vs observed host

- Copy-paste units and env **templates**: [deploy/examples](deploy/examples) (placeholders only; **root-only 0600** — see `PERMISSIONS.md`).
- **Observed** Helsinki units (`trading-desk-finnhub.service`, `trading-desk-tape.service`, env paths, validated Finnhub WS/REST, successful webhook test): [docs/OBSERVED_DEPLOYMENT.md](docs/OBSERVED_DEPLOYMENT.md).
- Merging Finnhub tape into the existing Tradier/UW `live_tape.json` is an **explicit remaining deployment step**.
- **Do not** restart Helsinki from a cloud agent.

## Package layout

| Path | Role |
| --- | --- |
| `src/groktrading/feeds/finnhub.py` | WS parse, backoff, watchlist, health, REST probe |
| `src/groktrading/feeds/unusual_whales.py` | Generic UW GET |
| `src/groktrading/feeds/tradier.py` | Generic Tradier quotes/balances/clock/preview |
| `src/groktrading/brokers/` | Venue-aware `Broker` protocol; `TradierBroker`; Schwab OAuth helper + fail-closed stub |
| `docs/DUAL_BROKER.md` | Dual-broker plan (OAuth helper; no dual-fire; exits follow holding venue; Tue Opening15 untouched) |
| `src/groktrading/gate.py` | Deterministic final gate |
| `src/groktrading/quote_gate.py` | P0.1 production quote validation |
| `src/groktrading/order_fsm.py` | P0.3 preview→submit lifecycle |
| `src/groktrading/idempotency.py` | Durable inbox/outbox (SQLite WAL) |
| `src/groktrading/flow_ledger.py` | Append-only UW flow ledger (SQLite); sit_match emit stays fail-closed |
| `src/groktrading/feeds/flow_alerts.py` | P1 UW flow-alerts poller; emit on new alert id only |
| `src/groktrading/feeds/tide_state.py` | P1 market-tide + optional net-prem → `tide_state.json` |
| `src/groktrading/feeds/quote_subscribe.py` | P1 bounded Tradier quote interest; `ws_tape.py` is host-owned |
| `src/groktrading/feeds/screener_snapshot.py` | P1 thin RTH screener snapshot; no sit_match spray |
| `src/groktrading/feeds/shadow_marks.py` | P2 shadow minute-marks (quotes only; no orders) |
| `src/groktrading/feeds/uw_ws.py` | P2 `UW_WS_URL` probe stub; fail-closed if unset; no invented protocol |
| `src/groktrading/replay_scorecard.py` | P2 ledger replay counts (first-print / already-run / stale); no PnL |
| `scripts/*_companion.py` | Host live pollers (secret-free). Operator-wired; not auto-enabled |
| `deploy/examples/systemd/host-companions/` | Example companion units + replay-scorecard timer (not installer-managed) |
| `src/groktrading/feeds/account_events.py` | Tradier account-events parse/backoff; position truth; never orders |
| `src/groktrading/box_rotate.py` | Box cold-rotate deny-list + 7–14d keep-hot + delete guard |
| `src/groktrading/retention.py` | Verified hot-ledger purge + companion JSONL bound |
| `scripts/hot_ledger_retain.py` | Operator retain CLI (examples only; no live timer enable) |
| `src/groktrading/webhook.py` | HMAC + durable or in-memory idempotency |
| `docs/WEBSOCKETS.md` | Auditor WS/webhook map (Finnhub ≠ option NBBO; WS never orders) |
| `docs/BOX_ARCHIVE.md` | Hot ledger vs Box `daily/YYYY-MM-DD/` cold archive |
| `docs/OPENAI_AUDIT_BRIEF.md` | What to review / what not to change / $25k YOLO ask |
| `docs/CLAUDE_AUDIT.md` | External Claude audit: live card, Opening15 paper path, APIs, local tests |
| `src/groktrading/llm.py` | Decision protocol (approve/skip only) |
| `src/groktrading/executor.py` | Signals-only stub + live guards |
| `src/groktrading/paper.py` | Paper ledger |
| `src/groktrading/policy.py` | Live card + 12:30 PT entry-cutoff |
| `schemas/` | JSON Schema for tape/gate/LLM artifacts |

## Hardening (package-first)

Safety details: [docs/SAFETY.md](docs/SAFETY.md).

- **P0.1** Quote freshness: OCC after normalize; `delayed==false`; ask>0; bid≥0; bid≤ask; provider `bid_date`/`ask_date` age; reject future timestamps; max spread; no-chase; sandbox/synthetic cannot pass live.
- **P0.2** Final gate: sit / already-run / duplicate / position from durable session facts + fresh broker account/positions/orders/clock. Qty=1. Cash floor ≥20%. No WS-direct submit.
- **P0.3** Order FSM: `RECEIVED → … → PREVIEW → FINAL_GATE → SUBMIT → ACK → FILLED/REJECTED → FLAT_RECONCILED`. Immutable payload; never blind-retry (query Tradier by `tag=signal_id` first). Paper/stub modes need no credentials.
- **P0.4 rewritten** Entry-cutoff only. **Reject** flatten-everything / no-overnight.
- **Idempotency** Durable SQLite WAL inbox/outbox; weekend/AH digest coalesce.

**Measurement:** freeze strategy params except safety; keep selection / execution / risk separate; **n=3 live days ≠ edge**. Do not invent fills or claim profitability.

## Optional research references (not dependencies)

Do **not** add these to `pyproject.toml`. Licensing and product fit are the operator’s problem:

- **LEAN** (QuantConnect) — official Tradier plugin, **Apache-2.0**; preview/submit shape is a **design reference only**.
- **NautilusTrader** — reconciliation / lifecycle concepts; design reference only. Not the runtime.
- **Lumibot** — Tradier support; **GPL** — do not vendor into this tree.
- **Optopsy** — useful options studies if isolated; **AGPL** — do not import.
- **QuantLib / vollib** — pricing research; optional, not required here.
- **Backtrader** — **not used** (avoid GPL entanglement and the wrong execution model).

This package is **not** a LEAN/C#/Nautilus/Lumibot/Optopsy migration.

## License

MIT — appropriate for a **public** GitHub reference package. Still: no warranty, no performance claims, no financial advice, no live trading by default.
