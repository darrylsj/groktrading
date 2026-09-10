"""Live-card policy: overnight allowed, 12:30 PT entry-cutoff only, 20% cash floor.

OpenAI P0.4 flatten-everything / no-overnight is REJECTED. After 12:30 PT the
desk stops new entries and may cancel working *entry* orders. Existing overnight
long options stay on the book and continue to be monitored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from groktrading.timeutil import entry_cutoff_deadline_pt, past_entry_cutoff, session_date_pt

CASH_EQUITY_FLOOR = Decimal("0.20")
MAX_DEPLOY_RATIO = Decimal("0.80")
PREFERRED_ONE_LOT_NOTIONAL = Decimal("200")
# I1 must_trade_small ask/limit cap only. Live Bot cheap band on funded cash is
# ~$0.80–$1.50; this is not a silent rewrite of PREFERRED_ONE_LOT_NOTIONAL.
MUST_TRADE_SMALL_ASK_CAP = Decimal("1.50")
OVERNIGHT_LONG_OPTIONS_ALLOWED = True
ENTRY_CUTOFF_FLATTENS_BOOK = False
DEFAULT_MAX_QUOTE_AGE_SECONDS = 5.0
DEFAULT_MAX_QUOTE_SPREAD = Decimal("0.50")
DEFAULT_MAX_QUOTE_SPREAD_FRAC = Decimal("0.25")


class BrokerEntryCutoff(Protocol):
    def cancel_working_entry_orders(self) -> list[str]:
        """Cancel working entry orders only. Must not flatten positions."""


class AlertSink(Protocol):
    def emit(self, code: str, message: str, details: dict[str, Any]) -> None: ...


class NoOpEntryCutoff:
    def cancel_working_entry_orders(self) -> list[str]:
        return []


class RecordingAlertSink:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str, dict[str, Any]]] = []

    def emit(self, code: str, message: str, details: dict[str, Any]) -> None:
        self.alerts.append((code, message, details))


# Back-compat aliases. Flatten must never be invoked by evaluate_entry_cutoff.
NoOpFlatten = NoOpEntryCutoff


@dataclass
class EntryCutoffAction:
    cutoff_active: bool
    should_block_new_entries: bool
    deadline_pt: datetime
    session_date: str
    canceled_entry_ids: list[str]
    flatten_symbols: list[str]
    alerted: bool
    reason: str
    should_act: bool = False


# Historical name used by older tests/docs.
CashUpAction = EntryCutoffAction


def evaluate_entry_cutoff(
    now: datetime,
    broker: BrokerEntryCutoff,
    alert: AlertSink | None = None,
) -> EntryCutoffAction:
    """Stop new entries after 12:30 PT. Never auto-flatten an overnight-allowed book."""
    deadline = entry_cutoff_deadline_pt(now)
    session = session_date_pt(now).isoformat()
    if not past_entry_cutoff(now):
        return EntryCutoffAction(
            cutoff_active=False,
            should_block_new_entries=False,
            deadline_pt=deadline,
            session_date=session,
            canceled_entry_ids=[],
            flatten_symbols=[],
            alerted=False,
            reason="before_12_30_pt_entry_cutoff",
            should_act=False,
        )
    canceled: list[str] = []
    alerted = False
    reason = "entry_cutoff_12_30_pt_no_flatten_overnight_allowed"
    try:
        canceled = list(broker.cancel_working_entry_orders())
    except Exception as exc:
        alerted = True
        reason = "entry_cutoff_cancel_failed"
        if alert is not None:
            alert.emit(
                "entry_cutoff_gate_failed",
                "12:30 PT entry-cutoff cancel failed; new entries remain blocked; "
                "overnight book was not flattened",
                {"error": str(exc), "session_date": session},
            )
    if hasattr(broker, "flatten_positions"):
        # Presence is tolerated on mixed stubs. This path must never call it.
        pass
    return EntryCutoffAction(
        cutoff_active=True,
        should_block_new_entries=True,
        deadline_pt=deadline,
        session_date=session,
        canceled_entry_ids=canceled,
        flatten_symbols=[],
        alerted=alerted,
        reason=reason,
        should_act=True,
    )


def evaluate_cash_up(
    now: datetime,
    broker: BrokerEntryCutoff,
    alert: AlertSink | None = None,
) -> EntryCutoffAction:
    """Deprecated name. Delegates to entry-cutoff (does not flatten)."""
    return evaluate_entry_cutoff(now, broker, alert)


def cash_reserve_after_premium(cash: Decimal, equity: Decimal, premium: Decimal) -> Decimal:
    remaining = cash - premium
    if equity <= 0:
        return Decimal("0")
    return remaining / equity


def breaches_cash_floor(
    cash: Decimal,
    equity: Decimal,
    premium: Decimal,
    floor: Decimal = CASH_EQUITY_FLOOR,
    max_deploy: Decimal = MAX_DEPLOY_RATIO,
) -> bool:
    """True when the entry would break the ≥20% cash/equity reserve or 80% max deploy."""
    if equity <= 0:
        return True
    if premium > equity * max_deploy:
        return True
    if cash < premium:
        return True
    return cash_reserve_after_premium(cash, equity, premium) < floor


@dataclass
class PolicyCard:
    """Frozen live card. Strategy knobs (sit-2, matching-ask) stay documented elsewhere."""

    overnight_long_options_allowed: bool = OVERNIGHT_LONG_OPTIONS_ALLOWED
    entry_cutoff_flattens_book: bool = ENTRY_CUTOFF_FLATTENS_BOOK
    cash_equity_floor: Decimal = CASH_EQUITY_FLOOR
    max_deploy_ratio: Decimal = MAX_DEPLOY_RATIO
    one_lot_preference: Decimal = PREFERRED_ONE_LOT_NOTIONAL
    hard_concurrent_position_cap: int | None = None
    daily_loser_circuit_breaker: bool = False
    notes: list[str] = field(
        default_factory=lambda: [
            "12:30 PT is a new-entry cutoff only (fail-closed = no new risk).",
            "Live orders are never triggered by WebSocket alone.",
            "Grok/LLM is outside the broker execution boundary.",
            "Sit-2 is the I2 lean bar; must_trade_small is a logged I1 exception.",
        ]
    )


LIVE_CARD = PolicyCard()
