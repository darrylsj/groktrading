# OpenAI audit brief

Public review pack for **external OpenAI / independent auditors** looking at [`darrylsj/groktrading`](https://github.com/darrylsj/groktrading). You have never been required to see the Helsinki host. Do **not** invent live prices or P&L. Do **not** treat this git merge as a deploy.

**Not financial advice.** This is a **public reference package**. Default mode is **signals-only**. Live trading is **operator-gated** and is never the default.

## Operator mandate (read first)

This is Darryl’s **YOLO account**. The goal is **capital expansion**, not capital preservation.

| Frame | Meaning |
| --- | --- |
| **Planning / selection / multi-lift sizing** | **$25,000** desk capital |
| **Live Tradier fills** | May still be **cash-constrained** on a **smaller funded balance** until the $25k is deposited |
| **Do not confuse** | Planning capital ≠ current broker equity. Auditors must not assume the live book already holds $25k, and must not size recommendations as if the funded cash were $25k **today**. |

Milestone spirit: grow aggressively **within the live-card risk rails** (cash/equity ≥20% / max deploy 80%, overnight OK, 12:30 PT = new-entry cutoff only). Do **not** reframe the desk as a preservation or “don’t lose” book.

Historical note only: the live funded book started small (early operator notes used ~$600 / first milestone $1,000 / $10,000). That is **not** the primary planning frame. Planning capital is **$25k**.

Encoded gate math in this tree remains **one-lot** (`quantity == 1`, preference ~$200 notional). $25k frames **planning / selection / multi-lift discussion**. Changing qty or adding concurrent caps is **not** an auditor drive-by; see “Do not change without operator OK.”

## What to review

1. **Architecture** — Helsinki ingest vs Grok consumer vs this package. [ARCHITECTURE.md](ARCHITECTURE.md), [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md), [README.md](../README.md).
2. **Gates** — P0.1 production quote freshness, P0.2 broker-authoritative final gate, P0.3 preview→submit FSM, P0.4 entry-cutoff (no flatten). [SAFETY.md](SAFETY.md), `src/groktrading/gate.py`, `quote_gate.py`, `order_fsm.py`, `policy.py`.
3. **WebSocket safety** — ticks never place live orders; Finnhub is not option NBBO; final gate rechecks fresh Tradier **production** quotes. [WEBSOCKETS.md](WEBSOCKETS.md).
4. **Policy / live card** — overnight long options allowed; 12:30 PT = new-entry cutoff only; cash/equity ≥20%; no hard concurrent-position caps; no daily-loser circuit breaker. README live card + [OPERATING_MODEL.md](OPERATING_MODEL.md).
5. **Secrets posture** — zero credentials in the tree; `scripts/scan_secrets.py` + detect-secrets in CI; examples are `YOUR_*` only.
6. **LLM boundary** — Grok is outside the broker execution boundary (approve/skip on frozen facts; never sets OCC, qty, limit, account, or order action).

## What NOT to change without operator OK

These are **frozen operator choices**, not open defects:

- Overnight long options **allowed**
- **12:30 PT = new-entry cutoff only** (not a forced flatten; fail-closed = no new risk)
- **No hard concurrent-position caps**
- **No daily-loser circuit breaker**
- Cash/equity **≥20%** / max deploy **80%** (do not restore a ≥50% “preservation” floor)
- Default mode **signals-only**; live never default
- WebSocket **never** a live submit path
- Grok **outside** the broker boundary

An older external note (“OpenAI P0.4”) proposed flatten-everything at 12:30 PT and no overnight. **That is rejected.** See [SAFETY.md](SAFETY.md).

## Explicit ask

Please recommend how to pursue **capital expansion** on a **$25k YOLO options desk**:

- **Selection** — what to promote / skip given Unusual Whales flow + sit-2 / matching-ask / already-run rails
- **Multi-lift** — how to think about adding risk **after** a working thesis, without inventing prices and without silently rewriting qty=1 in the gate
- **Exits / trails** — discuss candidates only. Trail policy is **under trial**, not adopted. If you mention a trail, treat it as a candidate (for example an arm-+50% / keep-60%-of-peak ratchet idea) — **do not lock a take-gain rule** as desk policy in this repo. This tree does not currently encode an adopted trail.

**Reject** “preserve capital / flatten everything / no overnight / raise the cash floor to 50%+” as the default recommendation unless a finding is **safety-critical** (secrets, WS-to-order bypass, quote-freshness hole, credential leak). Expansion advice that ignores the live card is out of scope.

Do **not** invent live quotes, fills, or P&L. Journaled historical rows in `logs/trades.jsonl` are recorded artifacts (`invented: false`), not a performance claim. n=3 live days ≠ edge.

## Pointers

| Doc | Why |
| --- | --- |
| [README.md](../README.md) | Public-audit lead, **$25k YOLO mandate**, live card |
| [SAFETY.md](SAFETY.md) | Gate checklist, P0 hardening, forbidden list |
| [WEBSOCKETS.md](WEBSOCKETS.md) | Finnhub vs Helsinki tape vs package `feeds/`; WS ≠ orders; webhook events |
| [ARCHITECTURE.md](ARCHITECTURE.md) / [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md) | Runtime split |
| [OPERATING_MODEL.md](OPERATING_MODEL.md) | Modes, paper vs production pricing |
| [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md) | Host facts; this commit is not deployed |
| [REVIEWER.md](REVIEWER.md) | Passive reviewer is **outside** the loop |
| [OPENING15_DECISION_PROTOCOL.md](OPENING15_DECISION_PROTOCOL.md) | Five paper sessions then act; `continue` never means live |
| [TUESDAY_EXECUTION_READINESS.md](TUESDAY_EXECUTION_READINESS.md) | Tuesday = clean baseline paper pilot, not expanded readiness |

## Out of scope for this review

- Deploying to Helsinki or restarting systemd units
- Placing orders
- Changing gate math because a preservation book “would be safer”
- Committing credentials, `/home/box` audit-pack secrets, or live Tradier tokens
- Treating sandbox delayed data as live fill evidence
