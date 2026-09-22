# Idea shadow rank (open slate)

Scores Trade Machine and Options AI `idea_board.v0_1` boards into a ranked
open slate. `shadow_only` is always true. This tool never places broker orders
and never invents prices, legs, or Compare metrics.

## Score (0–100)

- **signal_strength (0–40):** Active above Near Active (Trade Machine); defined-risk prior (Options AI). DOM max risk / max gain / PoP add presence only.
- **historical_hit (0–40):** vendor `winRate` plus a sample-size bonus when the board has them. Options AI without a vendor hit rate stays a low prior.
- **confluence (0–20):** same ticker on both boards, broad ETF, GEX shadow overlap.

Tiers: A ≥ 70, B ≥ 50, C ≥ 35, else D.

```bash
python3 tools/idea_shadow_rank/rank_open_slate.py
```

Writes `state/shadow_open_rank_latest.json`, an evidence card, and an append-only
ledger. Those paths are runtime output, not a live-order authorization.
