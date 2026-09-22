# XHR playbook — idea boards (TradeMachine + Options AI)

**Purpose:** Acquire trade ideas via own-session network traffic (HAR / XHR), normalize to `idea_board.v0_1`, feed desk gates in **shadow/paper** mode.  
**Companion research:** `evidence/idea_boards/xhr_acquisition_research_20260921.md`  
**Schema:** `SCHEMA.md`  
**Prior plan:** `evidence/trademachine_pseudo_api_plan_20260920.md`

> **Rule:** Mark endpoints **Confirmed** only after they appear in a redacted HAR. Do **not** invent live URLs.

---

## 0. Official API status (quick)

| Product | Public ideas API? | Notes |
|---|---|---|
| TradeMachine (CML) | **No** | Subscription SPA + member alerts; learn.trademachine.com is product docs, not a developer API. |
| Options AI | **No** | `trade.options.ai` email/password app; Tradier connect for execution. Not ClickOptions (`api.clickoptions.ai`). |

Practical path = **own paid session → capture SPA XHR → normalize**.

---

## 1. Capture (ask computerUse / box desktop)

Parent owns the browser via computerUse. Ask it to:

1. Use Darryl’s **paid / trial** session only.  
2. Open target board (TM **Today** first).  
3. DevTools → Network → **Preserve log** → filter **Fetch/XHR**.  
4. Reload board; open one Active idea for leg detail.  
5. **Save HAR with content** →  
   `evidence/idea_boards/har/<source>_<board>_YYYYMMDD_HHMM_pt.har`  
6. Produce `*_REDACTED.har` (strip Cookie, Authorization, Set-Cookie, tokens).  
7. Never paste secrets into chat; never commit raw HAR.

### Optional CDP/Playwright

Only on the parent-approved signed-in profile. Log `xhr`/`fetch` URL + status + JSON Content-Type; dump bodies to `evidence/idea_boards/xhr_snippets/` then redact. HAR remains the default.

---

## 2. Triage HAR

1. Filter entries with JSON responses (`content-type: application/json` or parsed JSON text).  
2. Search URL/path for: `idea|today|active|setup|strategy|alert|scan|signal|trigger|card`.  
3. Note **host**, **method**, **path**, **query keys** (not secret values).  
4. Auth mode: Cookie-only / Bearer / both / CSRF header names.  
5. Identify array-of-cards vs GraphQL `{ data: ... }` wrappers.  
6. Update endpoint ledger in the research note (Speculative → Confirmed).

Options AI HAR heuristic publication is **disabled**. Do not map
`expire-strikes`, `chain-details`, or quotes into idea cards. ClickOptions
is the wrong host. DOM QuickStrike / Strategy Builder boards are the only
Options AI input until a Confirmed idea endpoint exists.

### Heuristic JSON → schema keys (Trade Machine confirmed fields only)

| Look for | Map to |
|---|---|
| symbol / ticker / underlying | `ticker` |
| strategy / strategyName / template | `strategy` |
| active / triggered / status / nearActive | `status` |
| legs[] with strike, expiry, call/put, buy/sell | `legs[]` |
| mid / debit / credit / entry | `entry` |
| everything else useful | `ui_fields` |

Missing strike/price → `null`. **`no_invented_prices: true` always.**

---

## 3. Normalize & store

```text
evidence/idea_boards/trademachine_YYYYMMDD_HHMM_pt.json
evidence/idea_boards/options_ai_YYYYMMDD_HHMM_pt.json
evidence/idea_boards/idea_board_ledger.jsonl   # append one line
```

Minimum `notes` entry: path to redacted HAR + auth mode observed.

Login wall → `login_health: NOT_AUTHENTICATED`, empty `ideas`, stop (see SCHEMA).

---

## 4. Guardrails

- Paid session only; no redistributing commercial feed.  
- Never commit cookies/tokens/passwords/raw HAR.  
- Shadow/paper through desk gates only; scrapers do not place orders.  
- Position monitoring is a **separate** desk path — this playbook is **ideas in**, not open-P&L sync.  
- Do not call ClickOptions APIs for Options AI.

---

## 5. Ordered experiments

1. TradeMachine Today HAR → redact → map → `idea_board.v0_1` → ledger.  
2. Sanity-check vs latest GUI capture (`evidence/trademachine_ideas_*`).  
3. Options AI DOM QuickStrike / Strategy Builder board (not a HAR heuristic). Copy max risk, max gain, and PoP when shown.  
4. Promote confirmed endpoints into the research ledger.  
5. Automate repeatable XHR pull only after ≥1 Confirmed path per source.

---

## 6. Fallback order

1. XHR / HAR JSON  
2. DOM card scrape  
3. OCR (last resort)

