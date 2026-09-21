# Idea Funnel B — ranked multi-source

Locked 2026-09-20 PT. Window ~ through 2026-10-04.

## Sources (3 + tape)

1. **sit2 / Continual15 + Unusual Whales** — proprietary flow shortlist (Helsinki)
2. **Trade Machine** — visual Today setups (GUI/XHR pseudo-API; trial)
3. **Options AI** — paper / expected-move ideas (trial)

## Pipeline

Ingest → normalize one card → desk gates → score (multi-source bonus) →
**shadow many in parallel** → **live Tradier top-clear one-lots only**.
Vendors never autofire.

## Live mode

`top_clear_one_lots`. Shadow parallel; no one-trade-at-a-time cap on
shadow.

## Success needs

- Stable TM + Options AI scrapers
- Shared idea_card schema + jsonl ledger
- Scorecard by source (shadow vs live)
- wake_proof latency gate when event wakes on
- Kill rules: premium floor, cash reserve, ask-drift; cancel vendor
  trials if no edge
- Hostile review after rules exist

## Not success

More subscriptions, more alerts, or vendor autofire without desk gates.
