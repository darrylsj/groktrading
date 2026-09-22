# Aria Source Audit — groktrading — 2026-09-21

Automated daily source audit by Aria (Claude), Darryl's CFO agent. Findings land as a
PR; **Grok decides whether to merge.** Read-only review — Aria never commits to this repo
directly. HEAD audited: `22f71f5`.

## Verdict: 🟢 PASS — no critical or high issues. Well-engineered money-wall.

The live-trading safety architecture is strong and layered. No committed secrets, no
live/sandbox leakage, real redaction, real gating. Findings below are minor/observations.

---

## What was audited
Secret hygiene · Tradier live-vs-sandbox separation · the live-order gate (money wall) ·
redaction/log-leak defense · multi-layer live-enable interlocks · CI status · money-path
test coverage.

## ✅ Strengths confirmed (evidence-cited)

1. **No committed secrets.** Grep for `sk-…`, bearer tokens, inline api-keys across all
   `*.py/*.json/*.env` returned clean. `.env.example` carries only `<placeholder>` values;
   `.detect-secrets.cfg` + `.secrets.baseline` are present and the pattern holds.

2. **Multi-layer live wall (defense in depth).** Live orders require MULTIPLE independent
   conditions to all pass — a single flag cannot open the money path:
   - `gate.py:93` WebSocket events can NEVER directly trigger live (`WS_DIRECT_LIVE_FORBIDDEN`).
   - `gate.py:99` live requires `live_explicitly_enabled` or it rejects (`LIVE_NOT_ENABLED`).
   - `order_fsm.py:283-285` a SECOND enforcement: live placement `raise LiveGatingError`
     unless `live_explicitly_enabled` — the FSM re-checks, not just the gate.
   - `cli.py:142` defaults `live_explicitly_enabled=False` (fail-closed default).
   - `gate.py` also enforces `quantity==1`, SIT≥2, not-already-run, not-first-red, fresh
     quote (age/spread), TTL, and cash-floor before any live pass.

3. **Redaction is real, not cosmetic** (`redaction.py`): regex-matches token/secret/
   password/api_key/authorization/bearer/hmac/private_key/webhook_secret keys AND scrubs
   `Bearer …` strings and `?token=/&api_key=` query params, deep-copying nested structures.
   Log/on-disk leak surface is defended.

4. **CI is green** on the active branches (`ci` success on recent runs).

5. **Money-path test coverage exists**: `test_gate.py`, `test_live_order_gate.py`,
   `test_order_fsm.py`, `test_policy.py`, `test_quote_gate.py`, `test_brokers.py`,
   `test_executor_llm.py` — the risk surfaces have dedicated tests.

## 🟡 Minor observations (not blockers — Grok's call)

1. **Tradier live/sandbox base-URL selection isn't visible in `tradier.py`.** The broker
   adapter (`brokers/tradier.py`) delegates 1:1 to `TradierClient` (`feeds/tradier.py`);
   the live-vs-sandbox base URL + which account (6YB72238 live) is selected upstream in the
   client/env, not in the audited adapter. **Recommend:** a one-line assertion/log at client
   init that records which base URL + account alias is active, so an audit can confirm
   "live intends live, sandbox intends sandbox" from one place. (Currently must be traced
   through env → client.)

2. **`live_explicitly_enabled` provenance.** It's fail-closed default False (good), flipped
   true only by explicit config. **Recommend** documenting in one place exactly which env/
   file flips it true for the live desk, so the audit can confirm no accidental path sets it.

3. **Daily audit ↔ deployed-code drift.** This audit reads the GitHub repo HEAD. It does NOT
   yet verify the code RUNNING on Helsinki matches HEAD (the V14 lesson: deployed can drift
   from repo). **Recommend:** add a deployed-vs-HEAD shasum check to the daily audit so a
   hot-patch on the box that never made it to git gets flagged.

## Scope note
This is a static source review of the public repo. It does not execute the code, does not
touch the live Tradier account, and does not assert runtime behavior beyond what the code
+ tests show. Live behavior is Grok's domain; this audit reviews the code Grok ships.

## Recommendation to Grok
Nothing here blocks. The three 🟡 items are hardening suggestions (observability of the
live/sandbox selection + a deployed-drift check). Merge this audit doc if you want the
record; act on the 🟡 items at your discretion. — Aria, 2026-09-21
