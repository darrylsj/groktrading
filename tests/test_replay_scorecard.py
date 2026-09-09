from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from groktrading.feeds.shadow_marks import ShadowMarkBook
from groktrading.flow_ledger import FlowLedger
from groktrading.models import OptionQuote
from groktrading.replay_scorecard import scorecard
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _row(occ: str, executed: str, extra: str = "") -> dict[str, str]:
    body = {
        "executed_at": executed,
        "ticker": occ[:4],
        "occ": occ,
        "print": "1.00",
        "nbbo_ask": "1.05",
        "option_type": "put",
    }
    if extra:
        body["k"] = extra
    return body


def test_first_print_already_run_and_stale_counts() -> None:
    ledger = FlowLedger(":memory:", clock=FrozenClock())
    ledger.append_row(_row("NVDA260918P00170000", "2026-09-09T16:29:40Z"))
    ledger.append_row(
        _row("NVDA260918P00170000", "2026-09-09T16:29:50Z", extra="2")
    )
    ledger.append_row(_row("AMD260918P00100000", "2026-09-09T13:00:00Z", extra="old"))
    card = scorecard(ledger, now=NOW)
    assert card.stored == 3
    assert card.first_print == 2
    assert card.already_run == 1
    assert card.stale_filtered == 1
    assert card.unique_occ == 2
    doc = card.document()
    assert doc["pnl"] is None
    assert "No invented PnL" in doc["note"]
    assert doc["places_orders"] is False

    prior = scorecard(
        ledger, now=NOW, already_run_occs=["NVDA260918P00170000"]
    )
    assert prior.first_print == 1
    assert prior.already_run == 2


def test_optional_marks_counted_no_pnl() -> None:
    ledger = FlowLedger(":memory:", clock=FrozenClock())
    ledger.append_row(_row("NVDA260918P00170000", "2026-09-09T16:29:40Z"))
    book = ShadowMarkBook(":memory:", clock=FrozenClock())
    book.append_quote(
        OptionQuote(
            option_symbol="NVDA260918P00170000",
            bid=Decimal("1.00"),
            ask=Decimal("1.05"),
            quote_ts=NOW,
            source="tradier_production",
        )
    )
    card = scorecard(ledger, now=NOW, mark_book=book)
    assert card.marks_present is True
    assert card.marked_rows == 1
    assert card.document()["pnl"] is None


def test_empty_ledger() -> None:
    ledger = FlowLedger(":memory:", clock=FrozenClock())
    card = scorecard(ledger, now=NOW)
    assert card.stored == 0
    assert card.first_print == 0
    assert card.already_run == 0
    assert card.stale_filtered == 0
    assert card.marks_present is False
