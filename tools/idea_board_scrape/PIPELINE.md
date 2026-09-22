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

```bash
# TradeMachine from today’s confirmed HAR
python3 tools/idea_board_scrape/get_ideas.py --source trademachine \
  --from-har evidence/idea_boards/har/trademachine_today_20260921_0910_pt_REDACTED.har

# Options AI (after OAI HAR exists)
python3 tools/idea_board_scrape/get_ideas.py --source options_ai \
  --from-har evidence/idea_boards/har/options_ai_board_*_REDACTED.har

# Both (uses each --from-har; or defaults to latest known HARs)
python3 tools/idea_board_scrape/get_ideas.py --source both \
  --from-har evidence/idea_boards/har/trademachine_today_20260921_0910_pt_REDACTED.har \
  --from-har evidence/idea_boards/har/options_ai_board_….har
```

## Confirmed endpoints (as of 2026-09-21)

| Source | Endpoint | Notes |
|---|---|---|
| TradeMachine | `GET /wp-admin/admin-ajax.php?action=tm_get_today2_strategy_results` | Today board feed (Confirmed) |
| TradeMachine | `tm_get_strategy_result` + `attach_live_option_quotes` | Legs for Active cards |
| Options AI | **No dedicated idea XHR** (2026-09-21 HAR) | Ideas via authenticated **DOM QuickStrike** scrape; chain/quote XHR is market data only |

## Cadence (proposed)

RTH: every 30–60 min via routine calling computerUse capture → `get_ideas.py`. Until OAI Confirmed, TM-only runs are fine. Opportunity wakes stay separate; this feed is **shadow shortlist fuel**, not autofire.

## Guardrails

- Paid session only; no redistributing commercial feeds.
- Never commit raw HAR / cookies / tokens.
- `no_invented_prices: true` always.
- Live Tradier lifts still go through `live_order_gate` + Continual15 gates — idea boards do not submit.
