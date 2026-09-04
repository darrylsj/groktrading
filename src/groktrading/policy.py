"""12:30 PT cancel/flatten policy. No overnight positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from groktrading.timeutil import cash_up_deadline_pt, past_cash_up, session_date_pt


class BrokerFlatten(Protocol):
    def cancel_open_orders(self) -> list[str]:
        ...

    def flatten_positions(self) -> list[str]:
        ...


@dataclass
class CashUpAction:
    should_act: bool
    deadline_pt: datetime
    session_date: str
    cancel_ids: list[str]
    flatten_symbols: list[str]
    reason: str


class NoOpFlatten:
    def cancel_open_orders(self) -> list[str]:
        return []

    def flatten_positions(self) -> list[str]:
        return []


def evaluate_cash_up(now: datetime, broker: BrokerFlatten) -> CashUpAction:
    deadline = cash_up_deadline_pt(now)
    if not past_cash_up(now):
        return CashUpAction(
            should_act=False,
            deadline_pt=deadline,
            session_date=session_date_pt(now).isoformat(),
            cancel_ids=[],
            flatten_symbols=[],
            reason="before_12_30_pt",
        )
    cancel_ids = broker.cancel_open_orders()
    flatten_symbols = broker.flatten_positions()
    return CashUpAction(
        should_act=True,
        deadline_pt=deadline,
        session_date=session_date_pt(now).isoformat(),
        cancel_ids=cancel_ids,
        flatten_symbols=flatten_symbols,
        reason="cash_up_12_30_pt_no_overnight",
    )
