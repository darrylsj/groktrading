from __future__ import annotations

from datetime import datetime

from groktrading.policy import NoOpFlatten, evaluate_cash_up
from groktrading.timeutil import PT, past_cash_up


class RecordingFlatten:
    def cancel_open_orders(self) -> list[str]:
        return ["ord-1"]

    def flatten_positions(self) -> list[str]:
        return ["SPY260903C00600000"]


def test_before_cash_up_no_action() -> None:
    now = datetime(2026, 9, 3, 12, 29, tzinfo=PT)
    assert past_cash_up(now) is False
    action = evaluate_cash_up(now, RecordingFlatten())
    assert action.should_act is False
    assert action.cancel_ids == []


def test_at_and_after_12_30_pt_flattens() -> None:
    now = datetime(2026, 9, 3, 12, 30, tzinfo=PT)
    action = evaluate_cash_up(now, RecordingFlatten())
    assert action.should_act is True
    assert action.cancel_ids == ["ord-1"]
    assert action.flatten_symbols == ["SPY260903C00600000"]
    assert "no_overnight" in action.reason
    later = datetime(2026, 9, 3, 13, 0, tzinfo=PT)
    assert evaluate_cash_up(later, NoOpFlatten()).should_act is True
