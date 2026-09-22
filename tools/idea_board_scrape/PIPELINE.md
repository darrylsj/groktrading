# Get-ideas pipeline (TradeMachine + Options AI)

**Goal:** Repeatable acquisition of trade ideas into `idea_board.v0_1`, ledger, and a Continual15 **shadow** pointer. Scrapers never place broker orders.

## Flow

```
[computerUse / paid session]
   → CDP HAR capture (DevTools Save-HAR picker is broken on this box)
   → redact_har.py → *_REDACTED.har
   → get_ideas.py --from-har …
   → evidence/idea_boards/<source>_YYYYMMDD_HHMM_pt.json (+ .md)
   → append idea_board_ledger.jsonl
   → state/idea_board_latest.json   # shadow feed for Continual15
```

## CLI

There is no default HAR. Pass the capture you just redacted. `--source both`
requires one Trade Machine input and one Options AI DOM board. A `--from-har`
is not dropped when `--from-board` is also set. The shadow file is replaced
only after every source succeeds.

```bash
python3 tools/idea_board_scrape/redact_har.py /tmp/tm.har /tmp/tm_REDACTED.har

python3 tools/idea_board_scrape/get_ideas.py --source trademachine \
  --from-har /tmp/tm_REDACTED.har

# Options AI: validated DOM board. HAR→ideas is disabled.
python3 tools/idea_board_scrape/get_ideas.py --source options_ai \
  --from-board evidence/idea_boards/options_ai_20260921_0846_pt.json

python3 tools/idea_board_scrape/get_ideas.py --source both \
  --from-har /tmp/tm_REDACTED.har \
  --from-board evidence/idea_boards/options_ai_20260921_0846_pt.json
```

## Confirmed endpoints (as of 2026-09-21)

| Source | Endpoint | Notes |
|---|---|---|
| TradeMachine | `GET /wp-admin/admin-ajax.php?action=tm_get_today2_strategy_results` | Today board feed (Confirmed) |
| TradeMachine | `tm_get_strategy_result` + `attach_live_option_quotes` | Legs for Active cards |
| Options AI | **No dedicated idea XHR** (2026-09-21 HAR) | DOM QuickStrike / Strategy Builder boards only. `expire-strikes`, `chain-details`, and quotes are not idea cards. HAR heuristic is disabled. |

## Cadence (proposed)

RTH: every 30–60 min via routine calling computerUse capture → `get_ideas.py`. Until OAI Confirmed, TM-only runs are fine. Opportunity wakes stay separate; this feed is **shadow shortlist fuel**, not autofire.

## Guardrails

- Paid session only; no redistributing commercial feeds.
- Never commit a HAR. `redact_har.py` refuses a destination name without `REDACTED`. Unsupported body encodings fail closed.
- `no_invented_prices: true` always. Do not invent Options AI status, mode, or login health from chain JSON.
- Shadow pointer metadata is not a live-order authorization. Adapters must require `provenance.execution_realm` of `shadow` or `paper`.
- `get_ideas.py` does not call `live_order_gate`. Paper one-lots are `https://sandbox.tradier.com/v1` only (`tools/tradier_paper/`, dry-run unless `--submit`).
- Options AI: copy `max_risk`, `max_gain`, and `pop` when the DOM shows them. Do not invent them from chain XHR. Expected Move is 92.5% of the ATM straddle, not a probability.
- Trade Machine: Active first. Empty Near Active legs are expected. Do not invent legs.
- Vendor use and the underuse gap: [docs/IDEA_PRODUCT_USE.md](../../docs/IDEA_PRODUCT_USE.md), [docs/UNDERUSE_GAP_20260921.md](../../docs/UNDERUSE_GAP_20260921.md). Shadow rank: `tools/idea_shadow_rank/`.
