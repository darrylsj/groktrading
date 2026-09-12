# Shortlist ranker examples (not auto-enabled)

Plane 2 timer/service. **Do not enable from this repo.** `install_helsinki.sh`
does not copy these units. **Merge ≠ Helsinki restart.**

| File | Role |
| --- | --- |
| `groktrading-shortlist.service` | Oneshot: write `/opt/trading-desk/state/shortlist.json` |
| `groktrading-shortlist.timer` | Every **10s** (`OnUnitActiveSec=10`; documented 5–15s) |

`emit_sit_match` is false. `SIT_MATCH_WEBHOOK=0` (hunt default off). No
`grok-webhook.env`. No orders. No LLM.

Until an operator copies these onto the host and the file is actually
refreshing, Monday hunt stays **Continual15-only**. See
[docs/REALTIME_PLANES.md](../../../../docs/REALTIME_PLANES.md).
