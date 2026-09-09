from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from groktrading.flow_ledger import (
    FlowLedger,
    FlowLedgerError,
    draft_from_uw_row,
    evaluate_row_sit_match,
    flow_digest,
)
from groktrading.sit_match import REASON_STALE
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


def _sample(
    *,
    executed_at: str = "2026-09-09T16:29:40Z",
    ticker: str = "NVDA",
    occ: str = "NVDA260918P00170000",
    price: str = "1.07",
    ask: str = "1.10",
    option_type: str = "put",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    row = {
        "executed_at": executed_at,
        "ticker": ticker,
        "occ": occ,
        "print": price,
        "nbbo_ask": ask,
        "option_type": option_type,
    }
    if extra:
        row.update(extra)
    return row


def test_append_iter_recent_and_digest_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    clock = FrozenClock(NOW)
    ledger = FlowLedger(tmp_path / "flow.sqlite", clock=clock)
    first = ledger.append_row(_sample())
    again = ledger.append_row(_sample())
    assert first.raw_digest == again.raw_digest
    assert first.row_id == again.row_id
    assert first.ticker == "NVDA"
    assert first.option_type == "put"
    assert first.source == "option-trades"
    clock.now_value = NOW + timedelta(seconds=5)
    second = ledger.append_row(_sample(occ="NVDA260918P00175000", extra={"n": "2"}))
    recent = list(ledger.iter_recent(limit=10))
    assert [r.occ for r in recent] == [second.occ, first.occ]


def test_flow_alerts_source_and_uw_aliases() -> None:
    payload = {
        "created_at": "2026-09-09T16:29:50Z",
        "ticker_symbol": "spy",
        "option_chain_id": "SPY260903C00600000",
        "avg_price": "2.50",
        "ask": "2.55",
        "type": "Calls",
    }
    row = draft_from_uw_row(payload, ingested_at=NOW, source="flow-alerts")
    assert row.ticker == "SPY"
    assert row.occ == "SPY260903C00600000"
    assert row.option_type == "call"
    assert row.source == "flow-alerts"
    assert row.raw_digest == flow_digest(payload)


def test_flow_alerts_append_row_maps_option_chain() -> None:
    """Live UW flow-alerts rows use option_chain (not occ / option_symbol / option_chain_id)."""
    payload = {
        "option_chain": "spxw260930p07500000",
        "created_at": "2026-09-09T16:29:50Z",
        "ticker": "SPXW",
        "price": "1.25",
        "ask": "1.30",
        "type": "Puts",
    }
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    row = ledger.append_row(payload, source="flow-alerts")
    assert row.source == "flow-alerts"
    assert row.occ == "SPXW260930P07500000"
    assert row.ticker == "SPXW"
    assert row.print == "1.25"
    assert row.nbbo_ask == "1.30"
    assert row.option_type == "put"
    stored = list(ledger.iter_recent(limit=5, source="flow-alerts"))
    assert len(stored) == 1
    assert stored[0].occ == "SPXW260930P07500000"


def test_append_fail_closed_on_bad_clock_or_source() -> None:
    with pytest.raises(FlowLedgerError):
        draft_from_uw_row(_sample(executed_at="not-a-time"), ingested_at=NOW)
    with pytest.raises(FlowLedgerError):
        draft_from_uw_row({k: v for k, v in _sample().items() if k != "ticker"}, ingested_at=NOW)
    with pytest.raises(FlowLedgerError):
        draft_from_uw_row(_sample(option_type="straddle"), ingested_at=NOW)
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    with pytest.raises(FlowLedgerError):
        ledger.append_row(_sample(), source="not-a-source")  # type: ignore[arg-type]


def test_sit_match_stale_row_is_stored_but_not_emittable() -> None:
    clock = FrozenClock(NOW)
    ledger = FlowLedger(":memory:", clock=clock)
    stale = ledger.append_row(_sample(executed_at="2026-09-09T13:30:00Z"))
    fresh = ledger.append_row(_sample(executed_at="2026-09-09T16:29:40Z", extra={"k": "b"}))
    stale_gate = evaluate_row_sit_match(stale, NOW)
    fresh_gate = evaluate_row_sit_match(fresh, NOW)
    assert stale_gate.allow is False
    assert stale_gate.reason == REASON_STALE
    assert fresh_gate.allow is True
    assert list(ledger.iter_recent(limit=5))  # both stored


def test_purge_older_than_uses_fake_clock() -> None:
    clock = FrozenClock(NOW)
    ledger = FlowLedger(":memory:", clock=clock)
    old = _sample(executed_at="2026-09-01T16:00:00Z", extra={"day": "old"})
    ledger.append_row(old, ingested_at=NOW - timedelta(days=10))
    ledger.append_row(_sample(), ingested_at=NOW)
    removed = ledger.purge_older_than(7, now=NOW)
    assert removed == 1
    kept = list(ledger.iter_recent(limit=10))
    assert len(kept) == 1
    assert kept[0].occ == "NVDA260918P00170000"
    with pytest.raises(FlowLedgerError):
        ledger.purge_older_than(0, now=NOW)


def test_digest_redacts_secret_keys() -> None:
    a = flow_digest(_sample(extra={"token": "should-not-matter"}))
    b = flow_digest(_sample(extra={"token": "different-secret"}))
    assert a == b
    assert "should-not-matter" not in a
