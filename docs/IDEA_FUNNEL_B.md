# Idea Funnel B — ranked multi-source

Locked 2026-09-20 PT. Window ~ through 2026-10-04.

This card merges the operating note from draft PR #48 with the 2026-09-21
desk sync. Vendors never autofire. Live mode stays Tradier
`top_clear_one_lots` after desk gates. Shadow may run many ideas in parallel.

## Sources (3 + tape)

1. **sit2 / Continual15 + Unusual Whales** — proprietary flow shortlist (Helsinki)
2. **Trade Machine** — visual Today setups (GUI/XHR pseudo-API; trial)
3. **Options AI** — paper / expected-move ideas (trial)

## Pipeline

Ingest → normalize one card → desk gates → score (multi-source bonus) →
**shadow many in parallel** → **live Tradier top-clear one-lots only**.

Trade Machine and Options AI ingest in this repository is the shadow/paper
HAR path, not a live order path:

1. Capture a HAR with `tools/idea_board_scrape/cdp_har_capture.js` (box computerUse).
2. Redact with `tools/idea_board_scrape/redact_har.py`.
3. Build `idea_board.v0_1` with `tools/idea_board_scrape/get_ideas.py --from-har …`
   for `--source trademachine` and `--source options_ai`.

That CLI writes evidence boards, a ledger line, and a shadow pointer. It does
not submit orders. Do not wire it to live Tradier. Playbook:
[tools/idea_board_scrape/PIPELINE.md](../tools/idea_board_scrape/PIPELINE.md).

## Live mode

`top_clear_one_lots`. Shadow parallel; no one-trade-at-a-time cap on shadow.

## Success needs

- Stable Trade Machine + Options AI scrapers (shadow/paper)
- Shared idea card schema + jsonl ledger
- Scorecard by source (shadow vs live)
- wake_proof latency gate when event wakes are on
- Kill rules: premium floor, cash reserve, ask-drift; cancel vendor trials if no edge
- Hostile review after rules exist

## Not success

More subscriptions, more alerts, or vendor autofire without desk gates.

## idea_card vs idea_board

- **`idea_board.v0_1`** — scraper output from `get_ideas.py` (Trade Machine Today
  rows and Options AI idea lists). Samples:
  [trademachine](../evidence/idea_boards/trademachine_20260921_1120_pt.json),
  [options_ai](../evidence/idea_boards/options_ai_20260921_0846_pt.json).
- **`idea_card` v0.1** — join-key contract for UW / sit2 normalize. Card:
  [IDEA_CARD_V0_1.md](IDEA_CARD_V0_1.md). The JSON schema file, the UW
  normalizer package, and the Astra re-PASS evidence note are **not in this
  tree** (Helsinki / follow-up). Do not treat this PR as that normalizer landing.

## Account posture (Darryl 2026-09-20)

Maximize gains / YOLO, with hygiene gates left on (ask-drift, freshness,
cash reserve, premium floor). Shadow many; live top-clear one-lots. This is
an operator posture, not a profitability claim.
