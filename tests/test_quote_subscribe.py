from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from groktrading.errors import WatchlistBoundError
from groktrading.feeds.quote_subscribe import TradierQuoteInterest, quote_watch_bound
from groktrading.flow_ledger import draft_from_uw_row
from groktrading.sit_match import evaluate_sit_match_freshness
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


def test_touch_fresh_print_and_drop_idle() -> None:
    interest = TradierQuoteInterest(bound=3, idle_ttl_seconds=60)
    fresh = evaluate_sit_match_freshness("2026-09-09T16:29:40Z", NOW)
    assert interest.note_fresh_print("nvda", now=NOW, freshness=fresh) is True
    assert interest.note_fresh_print("NVDA", now=NOW, freshness=fresh) is False
    stale = evaluate_sit_match_freshness("2026-09-09T13:30:00Z", NOW)
    assert interest.note_fresh_print("AMD", now=NOW, freshness=stale) is False
    assert interest.symbols() == ["NVDA"]

    interest.touch("SPY", NOW)
    later = NOW + timedelta(seconds=120)
    dropped = interest.drop_idle(later)
    assert "NVDA" in dropped
    assert "SPY" in dropped
    assert interest.symbols() == []


def test_lru_evict_at_bound() -> None:
    interest = TradierQuoteInterest(bound=2, idle_ttl_seconds=3600)
    interest.touch("AAA", NOW)
    interest.touch("BBB", NOW + timedelta(seconds=1))
    interest.touch("CCC", NOW + timedelta(seconds=2))
    assert "AAA" not in interest.symbols()
    assert set(interest.symbols()) == {"BBB", "CCC"}


def test_bound_env_and_state_document() -> None:
    assert quote_watch_bound({}) == 40
    assert quote_watch_bound({"TRADIER_QUOTE_WATCH_BOUND": "99"}) == 40
    interest = TradierQuoteInterest()
    doc = interest.state_document(now=NOW)
    assert doc["places_orders"] is False
    assert doc["live_socket"] is False
    assert doc["host_owned_tape"] == "ws_tape.py"
    assert "ws_tape.py" in doc["note"]


def test_note_flow_row_uses_sit_match_freshness() -> None:
    interest = TradierQuoteInterest()
    row = draft_from_uw_row(
        {
            "executed_at": "2026-09-09T16:29:40Z",
            "ticker": "TSLA",
            "occ": "TSLA260918C00200000",
            "print": "2.00",
            "nbbo_ask": "2.05",
            "option_type": "call",
        },
        ingested_at=NOW,
    )
    assert interest.note_flow_row(row, NOW) is True
    stale = draft_from_uw_row(
        {
            "executed_at": "2026-09-09T10:00:00Z",
            "ticker": "AMD",
            "occ": "AMD260918C00100000",
            "print": "1.00",
            "nbbo_ask": "1.05",
            "option_type": "call",
        },
        ingested_at=NOW,
    )
    assert interest.note_flow_row(stale, NOW) is False
    assert "AMD" not in interest.symbols()


def test_full_after_idle_drop_still_respects_bound() -> None:
    interest = TradierQuoteInterest(bound=1, idle_ttl_seconds=10)
    interest.touch("AAA", NOW)
    with pytest.raises(WatchlistBoundError):
        interest.bound = 0
        interest.last_seen["AAA"] = NOW
        interest.touch("BBB", NOW)
