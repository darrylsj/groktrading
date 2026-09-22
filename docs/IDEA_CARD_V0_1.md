# idea_card schema v0.1

**Status:** described here as `approved_for_normalize_uw` on the desk
(2026-09-20 PT). The Astra re-PASS evidence note, `schemas/idea_card.v0_1.json`,
and `tools/idea_card_normalize/` are **not in this repository**.

**Scope of this card:** UW / sit2 normalize contract. Trade Machine and Options
AI boards in this tree use `idea_board.v0_1` via
[tools/idea_board_scrape/](../tools/idea_board_scrape/PIPELINE.md), which is
shadow/paper only. Vendors never autofire. Do not widen bands off this note.

## Hard rules

1. Join key + gate fuel, not brochure.
2. Does **not** replace `groktrading.shortlist.v1`.
3. Vendors never autofire; `execution_realm` paper/shadow until desk clears live_eligible.
4. Mid forbidden for ask-drift — use `ask_at_print` / `ask_at_decision`.
5. `score_hints` allow liquidity, multi_source_count, print_kind, unusual,
   expected_move, upside_asymmetric — **forbid** win_rate, vendor_confidence,
   backtest_edge, max_loss_priority.
6. Multi-source: one card per claim; cluster/related ids; never force-merge different OCC.
7. `raw_refs` full blob on disk at ingest (host evidence path; not committed here).
8. Shadow many in parallel; live = top-clear one-lots — prefer participation over zero-fill fear.
9. **Conditional required (null forbidden):**
   - UW single: `legs[0].occ`, `print_age_sec`, `print_side`, `entry_ref.ask_at_print`, `from_open_pct`
   - TradeMachine: `strategy_template_id`, `vendor_status`

## premium → ask_at_print

Rule: `ask_at_print = float(shortlist.premium)`.

## Ship gate

Normalize code for this card ships only after the schema file is in-repo and
a golden round-trip exists. Designing against v0.1 is fine. `get_ideas.py`
is a separate shadow board feed and is not that normalizer.
