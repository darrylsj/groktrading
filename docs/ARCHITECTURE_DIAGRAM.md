# Architecture diagram

Runtime split for GrokTrading: outside APIs, Helsinki (always-on, non-LLM), the Grok Bot computer (LLM), and a passive reviewer outside the active loop.

![GrokTrading architecture](groktrading-architecture.png)

Longer prose: [ARCHITECTURE.md](ARCHITECTURE.md). API surfaces: [API_MATRIX.md](API_MATRIX.md). Reviewer: [REVIEWER.md](REVIEWER.md).

## Legend

| Mark | Meaning |
| --- | --- |
| Solid arrow | Live data or control |
| Dashed arrow | Paper / verification only |
| Outside World APIs | Unusual Whales flow, Finnhub stock WS/REST, Tradier production, Tradier sandbox |
| Helsinki | Always-on ingest, filters, signed webhook, nightly scorer — **no LLM** |
| Grok Bot computer | Thesis / approve-skip on **frozen facts**, then a deterministic final gate |
| Passive Trade Reviewer | Reads the audit pack after the fact; **no** control or order permissions |

**Hard rules:** Finnhub is not option NBBO. WebSocket never places orders. Matching ask uses a Tradier **production** quote. Maintain **≥50% cash**. **12:30 PT** new-entry cutoff. Sandbox is **not** live fill evidence.

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
    FILT["Deterministic filters\nsit-2 · matching ask\nskip already-run · 50% cash"]
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
