# Persistent logs

This repository keeps **two** committed, secret-free logs. They are not interchangeable.

| File | Role |
| --- | --- |
| [CHANGELOG.md](../CHANGELOG.md) | Development log (Keep a Changelog). Operator and session history in **America/Los_Angeles**. |
| [logs/trades.jsonl](../logs/trades.jsonl) | Live trade journal. One JSON object per round-trip (an open lot is allowed). |

`thinking.jsonl` remains the **mixed decision tape**. It is a host runtime artifact, not a substitute for either committed log, and it must not be treated as the trade journal or the changelog.

## Rules

- **Never commit secrets.** No credentials, tokens, webhook HMAC material, host IPs, or private keys. Redact before any append. Env files stay on the host (`0600`); see [SAFETY.md](SAFETY.md).
- **Append-only.** Do not rewrite history to invent or erase fills. Correct a journal error with a later note, not a silent edit of a recorded row.
- **Do not invent prices or P&L.** Every `logs/trades.jsonl` row must set `"invented": false`. Missing an `exit_order_id` is recorded as `null` plus a note, not guessed.
- **n=3 is not an edge.** The live card is frozen at n=3. Do not size up, claim expectancy, or treat a handful of prints as a researched edge.

## What goes where

- Software, infra, cron, webhook, and policy notes → `CHANGELOG.md`.
- Broker round-trips (entry/exit, OCC, fills, realized USD) → `logs/trades.jsonl`.
- Mixed thesis / skip / approve scratch → `thinking.jsonl` on the host only.

Daily flat sessions and “do not chase” reminders belong in the changelog. They are not extra journal fills.

## Git

`*.jsonl` remains gitignored as a runtime pattern. `logs/trades.jsonl` is the
explicit journal exception. `tests/fixtures/**/*.jsonl` is also excepted so
labeled synthetic fixtures (for example the GEX shadow pair file) can be
committed without dragging in `thinking.jsonl` or other tapes.
