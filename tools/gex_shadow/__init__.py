"""GEX 60-minute paired shadow scorer. Never a live gate."""

from tools.gex_shadow.score_gex_pair import (
    LIVE_GATE,
    score_gex_pairs,
    score_gex_pairs_document,
)

__all__ = [
    "LIVE_GATE",
    "score_gex_pairs",
    "score_gex_pairs_document",
]
