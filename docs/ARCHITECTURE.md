# Architecture

This repository is a **reference and deployment package**. It is not itself a live trading deployment. Default mode is `signals_only`. Paper is explicit. Live order placement is never the default and cannot be driven by WebSocket callbacks.

## Runtime loop vs reviewer

The **passive reviewer** sits outside the active loop. Review happens on git diffs, PRs, and after-the-fact audit files. Reviewer comments must not be required for a tick, a webhook, or a gate decision.

## Data flow

```mermaid
flowchart LR
  subgraph Feeds
    FH[Finnhub stock trades WS / REST]
    UW[Unusual Whales options flow]
    TRP[Tradier production NBBO / clock / balances]
    TRS[Tradier sandbox paper account]
  end

  subgraph Helsinki["Helsinki always-on ingest"]
    ING[Ingest]
    NORM[Normalize + freshness]
    FILT[Filter sit-2 / no-spray]
    TAPE[Normalized tape JSON]
    WH[Signed webhook]
  end

  subgraph Decision
    GROK[Grok thesis approve/skip]
  end

  subgraph Gate["Deterministic gate"]
    G[Fresh quote TTL matching-ask qty cash clock 12:30]
  end

  subgraph Broker
    PAPER[Tradier paper]
    LIVE[Tradier live]
    EVT[Account events]
  end

  AUDIT[Same-day audit artifacts]
  REV[Passive reviewer outside loop]

  FH --> ING
  UW --> ING
  TRP --> ING
  ING --> NORM --> FILT --> TAPE
  TAPE --> WH --> GROK
  GROK --> G
  TRP --> G
  G -->|signals_only default| AUDIT
  G -->|explicit paper| PAPER
  G -->|explicit live never from WS| LIVE
  PAPER --> EVT
  LIVE --> EVT
  EVT --> AUDIT
  FILT -.->|WS must not place live| G
  REV -.-> AUDIT
```

## Helsinki responsibilities

| Stage | Behavior |
| --- | --- |
| Ingest | Finnhub last prints, UW flow (documented paths), Tradier quotes/chains/clock/balances/positions/orders/events |
| Normalize | Typed models, UTC timestamps, redaction before disk |
| Freshness | TTL fail-closed; stale UW/Tradier/Finnhub data cannot pass the gate |
| Filter | Sit-2, skip already-run, no first-red, no spray, one-lot only |
| Webhook | Signed HMAC, idempotency key, cooldown; **no LLM polling** |
| Paper vs live | Separate env files and account IDs; production NBBO is pricing truth |
| systemd | Units load root-only `0600` env files; examples live under `deploy/examples/` |

Finnhub tape integration into an existing Tradier/UW tape is an **explicit operator deployment step**. This repo does not perform that merge and does not claim to be deployed. See `docs/OBSERVED_DEPLOYMENT.md`.

## Grok role

Grok consumes **assembled facts only**. It returns `approve` or `skip` plus a thesis. It must not invent prices, P&L, or fills, and it must not hold a broker client. After an `approve`, the **deterministic gate** rechecks a **fresh Tradier option quote**.

## Safety invariants

- WebSocket events never directly trigger live orders.
- Quantity on options is exactly **1** contract.
- Flatten / cancel by **12:30 America/Los_Angeles**. No overnight positions.
- Matching ask; skip already-run; no first-red; sit-2.
- Timeouts and stale quotes fail closed.
