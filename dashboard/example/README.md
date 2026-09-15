# Example static output

Built from `tests/fixtures/dashboard/` — **not** from live Helsinki.

| File | Role |
| --- | --- |
| `board.json` | `groktrading.desk_board.v1` |
| `index.html` | Self-contained page for `darrylsj/trading-desk-live-board` (Vercel) |

Regenerate:

```bash
PYTHONPATH=src:. python -m dashboard build \
  --refuses tests/fixtures/dashboard/uw_opportunity_refuses.jsonl \
  --shortlist tests/fixtures/dashboard/shortlist.json \
  --shadow-summary tests/fixtures/dashboard/shadow_summary.json \
  --finnhub-tape tests/fixtures/dashboard/finnhub_tape.json \
  --live-tape tests/fixtures/dashboard/live_tape_health.json \
  --session 2026-09-14 \
  --now 2026-09-14T16:45:00+00:00 \
  --out-dir dashboard/example
```

Do not treat these counts as live desk state.
