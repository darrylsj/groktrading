from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.shadow_marks import (
    ShadowMarkBook,
    due,
    poll_shadow_marks,
    shadow_mark_sec,
)
from groktrading.models import OptionQuote
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class FakeQuotes:
    def __init__(self, quotes: dict[str, OptionQuote] | None = None, timeout: bool = False) -> None:
        self.quotes = quotes or {}
        self.timeout = timeout
        self.asked: list[str] = []

    def quote_option(self, option_symbol: str) -> OptionQuote:
        self.asked.append(option_symbol)
        if self.timeout:
            raise TimeoutFailClosedError("tradier_timeout")
        return self.quotes[option_symbol]


def _quote(occ: str, ask: str = "1.25") -> OptionQuote:
    return OptionQuote(
        option_symbol=occ,
        bid=Decimal("1.20"),
        ask=Decimal(ask),
        quote_ts=NOW,
        source="tradier_production",
        delayed=False,
    )


def test_append_and_iter_marks() -> None:
    book = ShadowMarkBook(":memory:", clock=FrozenClock(NOW))
    mark = book.append_quote(_quote("NVDA260918P00170000"))
    assert mark.occ == "NVDA260918P00170000"
    assert mark.ask == "1.25"
    assert mark.source == "tradier_production"
    recent = list(book.iter_recent(limit=10))
    assert len(recent) == 1
    assert recent[0].bid == "1.20"


def test_poll_minute_cadence_and_timeout_skip() -> None:
    occ = "NVDA260918P00170000"
    book = ShadowMarkBook(":memory:", clock=FrozenClock(NOW))
    quotes = FakeQuotes({occ: _quote(occ)})
    first = poll_shadow_marks(quotes, book, [occ, occ, "bad!"], now=NOW)
    assert len(first) == 1
    assert quotes.asked == [occ]

    skipped = poll_shadow_marks(
        quotes, book, [occ], now=NOW + timedelta(seconds=10), last_poll=NOW
    )
    assert skipped == []

    later = poll_shadow_marks(
        quotes, book, [occ], now=NOW + timedelta(seconds=60), last_poll=NOW
    )
    assert len(later) == 1
    assert due(NOW, NOW + timedelta(seconds=60), cadence_sec=60) is True

    errors: list[str] = []
    timed = FakeQuotes(timeout=True)
    marks = poll_shadow_marks(
        timed, book, [occ], now=NOW, on_error=lambda s, _e: errors.append(s)
    )
    assert marks == []
    assert errors == [occ]


def test_cadence_clamp() -> None:
    assert shadow_mark_sec({}) == 60.0
    assert shadow_mark_sec({"SHADOW_MARK_SEC": "5"}) == 30.0
    assert shadow_mark_sec({"SHADOW_MARK_SEC": "999"}) == 180.0


def test_no_submit_on_book() -> None:
    assert not hasattr(ShadowMarkBook, "submit_option_order")
    assert "submit" not in dir(ShadowMarkBook)
