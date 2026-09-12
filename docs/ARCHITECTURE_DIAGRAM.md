# Architecture diagram

Runtime split for GrokTrading: outside APIs, Helsinki (always-on, non-LLM), the Grok Bot computer (LLM), and a passive reviewer outside the active loop.

![GrokTrading architecture](groktrading-architecture.png)

Longer prose: [ARCHITECTURE.md](ARCHITECTURE.md). Hunt planes: [REALTIME_PLANES.md](REALTIME_PLANES.md). WebSockets: [WEBSOCKETS.md](WEBSOCKETS.md). Auditor brief: [OPENAI_AUDIT_BRIEF.md](OPENAI_AUDIT_BRIEF.md). API surfaces: [API_MATRIX.md](API_MATRIX.md). Reviewer: [REVIEWER.md](REVIEWER.md).

## Legend

| Mark | Meaning |
| --- | --- |
| Solid arrow | Live data or control |
| Dashed arrow | Paper / verification only |
| Outside World APIs | Unusual Whales flow, Finnhub stock WS/REST, Tradier production, Tradier sandbox |
| Helsinki | Always-on ingest, filters, signed webhook, nightly scorer — **no LLM** |
| Grok Bot computer | **LLM** thesis / approve-skip on **frozen facts only** (must not call Tradier). **Gate / executor** uses Tradier production for fresh OCC quotes and live orders |
| Passive Trade Reviewer | Reads the audit pack after the fact; **no** control or order permissions |

**Hard rules:** Finnhub is not option NBBO. WebSocket never places orders; the final gate rechecks a fresh Tradier **production** quote. Matching ask uses production NBBO. Maintain **≥20% cash/equity** (max deploy 80%). Overnight longs allowed. **12:30 PT** new-entry cutoff only (not a flatten). Grok is outside the broker boundary. Sandbox is **not** live fill evidence. Planning capital is **$25k** (YOLO expansion); do not confuse that with current broker equity.

## Mermaid (GitHub-native)

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
    RANK["Thin ranker 5–15s\nshortlist.json"]
    HOOK["Signed webhook outbox\nin_position / fills / login_dead"]
    NIGHT["Nightly print scorer cron"]
  end
  subgraph Grok["Grok Bot computer — LLM"]
    LLM["Continual15 thesis / approve-skip\non frozen facts only"]
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
  FILT --> RANK
  RANK -->|"pull shortlist"| LLM
  FILT --> HOOK
  HOOK -->|"in_position / cash_up"| LLM
  LLM --> GATE
  GATE --> EXEC
  EXEC -->|"live"| TP
  EXEC -.->|"paper verify"| TS
  GATE --> AUDIT
  ROUT --> AUDIT
  NIGHT --> AUDIT
  AUDIT --> REV
```
