# Claude audit brief

Public review pack for an **external Claude audit** of [`darrylsj/groktrading`](https://github.com/darrylsj/groktrading). You do not need the Helsinki host. Do **not** invent live prices or P&L. A git merge is **not** a deploy.

**Not financial advice.** This is a **public reference package**. Default mode is **signals-only**. Paper research is explicit. Live Tradier trading is **operator-gated** and is never the default. The goal is **capital expansion**, not capital preservation.

A sibling OpenAI-facing brief lives at [OPENAI_AUDIT_BRIEF.md](OPENAI_AUDIT_BRIEF.md). The operator mandate is the same.

## What this repo is / is not

| Is | Is not |
| --- | --- |
| Secret-free **public reference** for a Helsinki-hosted, Grok-assisted options desk | A claim that GitHub `main` is what Helsinki runs |
| **Signals-only** by default; **paper** research (Opening15) is isolated | A live-order bot, a broker, or a profitability demonstration |
| **YOLO $25,000 planning capital** for selection / multi-lift discussion | A statement that the funded Tradier book already holds $25k |
| **Capital expansion** within the live-card rails | A preservation / “don’t lose” book |
| **Live Tradier** (quotes, balances, positions, orders, preview→submit) is a **separate**, operator-gated path | Automatic live fills from research, WebSocket ticks, or this audit |

Planning capital ≠ current broker equity. Live fills may still be **cash-constrained** on a **smaller funded balance** until the $25k is deposited. Encoded gate math stays **one-lot** (`quantity == 1`, preference ~$200 notional). Do not size recommendations as if the live book already holds $25k **today**.

Historical note only: the funded book started small (early operator notes used ~$600 / first milestone $1,000 / $10,000). That is **not** the primary planning frame.

## Architecture (three paths)

```
Unusual Whales / Finnhub / Tradier production
        │
        ▼
Helsinki tape (always-on, non-LLM)
  trading-desk-tape + trading-desk-finnhub
  sit-2 / matching ask / skip already-run / ≥20% cash
  signed webhook outbox — WebSocket never places orders
        │
        ▼
Grok Bot computer
  LLM thesis / approve-skip on frozen facts only
  Grok is outside the broker boundary
  deterministic final gate → preview → submit (Tradier production)
        │
        └── Passive reviewer (outside the loop; no order permissions)

Opening15 research (this package; paper only)
  UW + Tradier capture → freeze packet → Codex CLI recommend
  ChatGPT Pro CLI session (not OPENAI_API_KEY / Responses by default)
  fixed 15:55 ET paper exit — never Candidate / never live gate
```

- **Helsinki** ingests and filters. No LLM polling. No preview→submit on the host units.
- **Grok Bot** consumes frozen facts, then a **deterministic** gate rechecks a fresh Tradier **production** OCC quote. Matching ask uses production NBBO. Finnhub is **not** option NBBO.
- **Opening15** is a separate discretionary paper experiment. Codex CLI (`codex exec`) is the default recommend backend. Model output never becomes a live order.
- **Hard rule:** WebSocket events never place live orders. See [WEBSOCKETS.md](WEBSOCKETS.md).

## Live card (authoritative)

Any older ≥50% cash floor, flatten-at-12:30, or no-overnight policy is stale.

- **Overnight long options: ALLOWED**
- **12:30 PT = NEW-ENTRY CUTOFF ONLY** (not a forced flatten). Fail-closed = no new risk; keep monitoring the book
- **Cash/equity ≥20%** / **max deploy 80%**
- **Matching ask** on a fresh Tradier **production** quote
- **One-lot preference**; no hard concurrent-position caps; no daily-loser circuit breaker
- **Grok / any LLM is outside the broker execution boundary**: approve/skip only; never set OCC, qty, limit, account, or order action

OpenAI P0.4 flatten-everything / no-overnight is **rejected**. Full checklist: [SAFETY.md](SAFETY.md).

## Opening15 experiment (paper research)

Discretionary **first 15 minutes** (09:30–09:45 ET) across a ten-stock universe. The model may select up to three contracts or none. **No** sit-2 / ask-side / premium filter is required on this path.

| Item | Rule |
| --- | --- |
| Mode | **Paper only.** No preview, submit, cancel, or modify |
| Recommend | **Codex CLI** + operator **ChatGPT Pro** login; requested model `gpt-6-astra` (host probe required) |
| Exit | Fixed **15:55 ET** paper mark; missing exits stay null (not a fabricated zero) |
| Baseline | Opening-window UW prints + Tradier quotes → Codex decision → paper monitor. **Tuesday 2026-09-08 launch path.** |
| Expanded | Same plus Context collectors. Not Tuesday's claim. Required categories must be `available` (depth may be `missing`) or a later paper day is `--allow-degraded` and labeled. `--allow-degraded` is not a live entitlement. |
| Decision protocol | After five paper sessions: `insufficient \| kill \| continue \| inconclusive`. `continue` = more paper / wider paper universe, never live. [OPENING15_DECISION_PROTOCOL.md](OPENING15_DECISION_PROTOCOL.md) |

Schwab OAuth is **not** connected. Expanded portfolio is **Tradier read-only** (`/accounts/{id}/balances|positions|orders`) until Schwab lands. Schwab remains **holdings-first** when that integration exists — it is not a second live-order path. Account numbers are opaque `acct-` aliases in model-facing JSON.

Runbooks: [OPENING15_EXPERIMENT.md](OPENING15_EXPERIMENT.md), [TUESDAY_EXECUTION_READINESS.md](TUESDAY_EXECUTION_READINESS.md), [GROK_RESEARCH_HANDOFF.md](GROK_RESEARCH_HANDOFF.md).

## APIs used (names only — no secrets)

Credential **names** only. Examples in the tree are `YOUR_*`. Do not ask for or commit tokens.

| Surface | Role |
| --- | --- |
| Unusual Whales `GET /api/option-trades`, `GET /api/news/headlines` | Opening prints + company headlines. Env: `UW_API_TOKEN` or `UW_API_KEY` |
| Tradier production `GET /markets/quotes`, `/calendar`, `/history`, `/options/expirations`, `/options/chains` | Quotes, session calendar, prior bars, near chains. Env: `TRADIER_ACCESS_TOKEN` |
| Tradier production `GET /accounts/{id}/balances\|positions\|orders` | Read-only interim portfolio. Optional `TRADIER_ACCOUNT_ID`. **GET only** on the research path |
| Finnhub `GET /news?category=general` | World news when entitled. Optional `FINNHUB_API_KEY`. Unused/401/403 → coverage **missing**, not fabricated |
| Codex CLI `codex exec` | Opening15 recommend. ChatGPT Pro session. `OPENAI_API_KEY` is **not** required on `codex_cli` |

Tradier sandbox is paper-lifecycle only (15-minute delayed). Sandbox ≠ live fill evidence.

**Still missing / not claimed:** Schwab OAuth, exchange depth, dedicated macro-release calendars, UW article bodies, independently reconciled OPRA, live broker orders from this research path.

## How to run tests locally

No credentials are required. Collectors and Opening15 tests use mocked HTTP.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests scripts
pytest
mypy src/groktrading
python scripts/scan_secrets.py
```

Focused checks:

```bash
pytest tests/test_research_collectors.py tests/test_opening15.py tests/test_public_audit_docs.py
```

CI on GitHub runs the same ruff / pytest / mypy / secret-scan set. Do not place live orders or restart Helsinki to review this tree.

## What to review / recommend

1. **Selection quality** — Opening15 discretionary picks vs the live-desk UW flow + sit-2 / matching-ask / already-run rails. What to promote or skip on a $25k planning frame. Do not invent prints.
2. **Risk** — live-card rails (overnight OK, 12:30 entry-cutoff only, ≥20% cash, qty=1). Multi-lift discussion after a working thesis, without silently rewriting gate math.
3. **Expanded context gaps** — world news entitlement, `$VIX.X` often missing (macro **partial**), no dedicated FOMC/earnings calendar, no depth, Tradier XML-JSON oddities on account snapshots. Portfolio collector must fail closed (coverage **missing** or empty working-orders list with a reason) rather than crash `collect_context`.
4. **Schwab still holdings-first** — when Schwab OAuth lands it is a holdings/portfolio source, not a second live-order path. Until then, Tradier read-only snapshot is interim.
5. **Architecture / WS safety** — Helsinki vs Grok Bot vs Opening15; ticks never submit; Grok outside the broker boundary. [WEBSOCKETS.md](WEBSOCKETS.md), [SAFETY.md](SAFETY.md).
6. **Secrets posture** — zero credentials in the tree; `scripts/scan_secrets.py` + detect-secrets in CI.

## Explicit ask

Please recommend how to pursue **capital expansion** on a **$25k YOLO options desk**:

- **Selection** — what to promote / skip given Unusual Whales flow and (on the live desk) sit-2 / matching-ask / already-run rails
- **Opening15** — how baseline vs expanded Context should change discretionary first-15m paper picks; label gaps instead of fabricating coverage
- **Multi-lift** — adding risk **after** a working thesis, without inventing prices and without silently rewriting `qty=1` in the gate
- **Exits / trails** — discuss candidates only. Trail policy is **under trial**, not adopted. Do **not** lock a take-gain rule as desk policy in this repo

**Reject** “preserve capital / flatten everything / no overnight / raise the cash floor to 50%+” as the default recommendation unless a finding is **safety-critical** (secrets, WS-to-order bypass, quote-freshness hole, credential leak). Expansion advice that ignores the live card is out of scope.

Do **not** invent live quotes, fills, or P&L. Journaled rows in `logs/trades.jsonl` are recorded artifacts (`invented: false`), not a performance claim. n=3 live days ≠ edge.

## Pointers

| Doc | Why |
| --- | --- |
| [OPENAI_AUDIT_BRIEF.md](OPENAI_AUDIT_BRIEF.md) | Sibling OpenAI pack: review scope, frozen operator choices, $25k YOLO ask |
| [WEBSOCKETS.md](WEBSOCKETS.md) | Finnhub ≠ option NBBO; Helsinki tape vs package `feeds/`; WS never orders |
| [SAFETY.md](SAFETY.md) | Live card, gate checklist, P0 hardening, forbidden list |
| [OPENING15_EXPERIMENT.md](OPENING15_EXPERIMENT.md) | First-15m paper experiment, Codex CLI, 15:55 ET exit |
| [TUESDAY_EXECUTION_READINESS.md](TUESDAY_EXECUTION_READINESS.md) | Tuesday = clean baseline paper pilot (`research.cli run`), not `--allow-degraded` |
| [OPENING15_DECISION_PROTOCOL.md](OPENING15_DECISION_PROTOCOL.md) | Five paper sessions → insufficient/kill/continue/inconclusive; continue ≠ live |
| [GROK_RESEARCH_HANDOFF.md](GROK_RESEARCH_HANDOFF.md) | Collectors, coverage contract, Schwab-not-ready portfolio |
| [README.md](../README.md) | Public-audit lead, $25k mandate, live card |
| [ARCHITECTURE.md](ARCHITECTURE.md) / [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md) | Runtime split |

## Out of scope for this review

- Deploying to Helsinki or restarting systemd units
- Placing orders
- Changing gate math because a preservation book “would be safer”
- Committing credentials, `/home/box` audit-pack secrets, or live Tradier tokens
- Treating sandbox delayed data as live fill evidence
- Treating Opening15 paper marks as live fills or as an edge claim
