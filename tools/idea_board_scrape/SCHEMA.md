# Idea board scrape schema (TradeMachine + Options AI)

**Goal:** Clean, repeatable board pulls — not one-off screenshots.

## Output paths
- `evidence/idea_boards/trademachine_YYYYMMDD_HHMM_pt.json` (+ `.md` + board `.png`)
- `evidence/idea_boards/options_ai_YYYYMMDD_HHMM_pt.json` (+ `.md` + board `.png`)
- Append-only ledger: `evidence/idea_boards/idea_board_ledger.jsonl`

## JSON shape (`idea_board.v0_1`)
```json
{
  "schema": "idea_board.v0_1",
  "source": "trademachine|options_ai",
  "as_of_pt": "YYYY-MM-DD HH:MM:SS PT",
  "source_url": "https://...",
  "login_health": "AUTHENTICATED|NOT_AUTHENTICATED|UNKNOWN",
  "mode": "paper|live|n/a",
  "board": "Today|Trade|Dashboard|...",
  "ideas": [
    {
      "ticker": "XLK",
      "strategy": "string",
      "status": "Active|Near Active|Watch|...",
      "direction": "string|null",
      "legs": [{"side":"LONG|SHORT","expiry":"YYYY-MM-DD|null","strike":null,"right":"C|P|null","display_price":null}],
      "entry": {"display": "string|null", "mid": null},
      "ui_fields": {},
      "raw_text": "optional card text"
    }
  ],
  "counts": {"ideas": 0, "active": 0},
  "screenshots": ["evidence/idea_boards/...png"],
  "notes": [],
  "no_invented_prices": true
}
```

## Rules
- Only fields visible in UI (or captured XHR JSON). Never invent prices/strikes.
- Paper/shadow only — scrapers never place broker orders.
- If login wall: stop, report refs for in-chat form / 1Password; do not type secrets into chat.
- Prefer SPA XHR JSON when available; else DOM card scrape; OCR last resort.
