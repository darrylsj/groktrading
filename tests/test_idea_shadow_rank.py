"""Shadow rank prefers Active Trade Machine rows and does not invent Options AI metrics."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.idea_shadow_rank.rank_open_slate import build_slate


def test_active_outranks_near_active_and_stays_shadow() -> None:
    tm = {
        "as_of_pt": "2026-09-21 08:35:00 PT",
        "login_health": "AUTHENTICATED",
        "ideas": [
            {
                "ticker": "SMH",
                "strategy": "Credit the Sell-Off",
                "status": "Near Active",
                "legs": [],
                "ui_fields": {"isActive": 0, "winRate": 0.8, "numWins": 8, "numLosses": 2},
            },
            {
                "ticker": "XLK",
                "strategy": "ETF 2-Days-Up Diagonal",
                "status": "Active",
                "legs": [{"side": "LONG"}],
                "ui_fields": {"isActive": 1, "winRate": 0.8, "numWins": 8, "numLosses": 2},
            },
        ],
    }
    oai = {
        "as_of_pt": "2026-09-21 08:46:00 PT",
        "ideas": [
            {
                "ticker": "AAPL",
                "strategy": "Call Spread",
                "status": "Available",
                "direction": "Bullish",
                "legs": [],
            }
        ],
    }
    slate = build_slate(tm, oai, gex=set(), now=datetime(2026, 9, 21, 16, 0, tzinfo=UTC))
    assert slate["shadow_only"] is True
    assert slate["no_live_orders"] is True
    tickers = [row["ticker"] for row in slate["all_ranked"] if row["source"] == "trademachine"]
    assert tickers[0] == "XLK"
    assert slate["all_ranked"][0]["score"] > next(
        row["score"] for row in slate["all_ranked"] if row["ticker"] == "SMH"
    )
    aapl = next(row for row in slate["all_ranked"] if row["ticker"] == "AAPL")
    assert aapl["compare_metrics_present"] is False
    assert aapl["pop"] is None
    assert aapl["max_risk"] is None
    assert "HAR heuristic off" in " ".join(aapl["reasons"])
