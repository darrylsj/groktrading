# Passive reviewer

The reviewer is **outside the active runtime loop**.

## In the loop (Helsinki)

Feeds → normalize → filter → tape → signed webhook → Grok → deterministic gate → paper/live (if explicitly enabled) → account events → same-day audit.

## Outside the loop (reviewer)

- Read PRs and `git diff`
- Read redacted tape / paper JSON after the session
- Comment on policy drift, tests, and docs
- **Must not** approve individual ticks, block webhooks, or sit on a chat prompt before the 12:30 PT new-entry cutoff

A human may later enable live trading on the host; that is an operator action, not a reviewer callback.

If a change set is large, review after merge-candidate CI is green. Do not insert the reviewer into systemd `ExecStart`.
