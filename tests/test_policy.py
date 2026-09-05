from __future__ import annotations

from datetime import datetime

from groktrading.policy import (
    CASH_EQUITY_FLOOR,
    ENTRY_CUTOFF_FLATTENS_BOOK,
    LIVE_CARD,
    OVERNIGHT_LONG_OPTIONS_ALLOWED,
    RecordingAlertSink,
    evaluate_cash_up,
    evaluate_entry_cutoff,
)
from groktrading.timeutil import PT, past_entry_cutoff


class RecordingEntryCutoff:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.flatten_calls = 0

    def cancel_working_entry_orders(self) -> list[str]:
        self.cancel_calls += 1
        return ["ord-1"]

    def flatten_positions(self) -> list[str]:
        self.flatten_calls += 1
        return ["SPY260903C00600000"]


class ExplodingCancel:
    def cancel_working_entry_orders(self) -> list[str]:
        raise RuntimeError("tradier_cancel_failed")

    def flatten_positions(self) -> list[str]:
        raise AssertionError("flatten must not be called")


def test_live_card_constants() -> None:
    assert OVERNIGHT_LONG_OPTIONS_ALLOWED is True
    assert ENTRY_CUTOFF_FLATTENS_BOOK is False
    assert CASH_EQUITY_FLOOR == LIVE_CARD.cash_equity_floor
    assert LIVE_CARD.hard_concurrent_position_cap is None
    assert LIVE_CARD.daily_loser_circuit_breaker is False


def test_before_entry_cutoff_no_action() -> None:
    now = datetime(2026, 9, 3, 12, 29, tzinfo=PT)
    assert past_entry_cutoff(now) is False
    broker = RecordingEntryCutoff()
    action = evaluate_entry_cutoff(now, broker)
    assert action.should_block_new_entries is False
    assert action.canceled_entry_ids == []
    assert action.flatten_symbols == []
    assert broker.cancel_calls == 0
    assert broker.flatten_calls == 0


def test_at_and_after_12_30_pt_cancels_entries_does_not_flatten() -> None:
    now = datetime(2026, 9, 3, 12, 30, tzinfo=PT)
    broker = RecordingEntryCutoff()
    action = evaluate_entry_cutoff(now, broker)
    assert action.should_block_new_entries is True
    assert action.canceled_entry_ids == ["ord-1"]
    assert action.flatten_symbols == []
    assert broker.flatten_calls == 0
    assert "no_flatten" in action.reason
    assert "overnight_allowed" in action.reason
    later = datetime(2026, 9, 3, 13, 0, tzinfo=PT)
    later_action = evaluate_cash_up(later, RecordingEntryCutoff())
    assert later_action.should_block_new_entries is True
    assert later_action.flatten_symbols == []


def test_cutoff_cancel_failure_alerts_and_does_not_flatten() -> None:
    now = datetime(2026, 9, 3, 12, 31, tzinfo=PT)
    alerts = RecordingAlertSink()
    action = evaluate_entry_cutoff(now, ExplodingCancel(), alerts)
    assert action.alerted is True
    assert action.should_block_new_entries is True
    assert action.flatten_symbols == []
    assert alerts.alerts
    assert alerts.alerts[0][0] == "entry_cutoff_gate_failed"
