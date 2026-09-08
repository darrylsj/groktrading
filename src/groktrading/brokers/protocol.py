"""Venue-aware broker protocol (Phase A: Tradier only).

`OrderBroker` remains the preview/submit/find subset used by `OrderMachine`.
`Broker` is the structural superset live/paper paths should depend on:
balances, positions, option quote, preview, submit, find-by-tag, and
cancel of working entry orders.

A print may be sent to at most one venue. Exits follow the holding venue.
Tuesday Opening15 (`research.cli run`) must not import this package.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from groktrading.errors import LiveGatingError
from groktrading.models import AccountSnapshot, ClockSnapshot, OptionQuote

VenueId = Literal["tradier"]

# Planned Phase B/C venue. Not on VenueId until Schwab OAuth is Ready For Use.
PLANNED_SCHWAB_VENUE = "schwab"


class OrderBroker(Protocol):
    """Preview → submit → find-by-tag. Payload stays immutable except preview."""

    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]: ...

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]: ...

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None: ...


class Broker(OrderBroker, Protocol):
    """Venue-aware execution + gate inputs. Phase A implementer is Tradier only."""

    venue_id: VenueId

    def balances(self) -> AccountSnapshot: ...

    def positions(self) -> list[str]: ...

    def quote_option(self, option_symbol: str) -> OptionQuote: ...

    def snapshot_account(self) -> AccountSnapshot: ...

    def market_clock(self) -> ClockSnapshot: ...

    def cancel_working_entry_orders(self) -> list[str]: ...


def refuse_dual_fire(
    *,
    signal_id: str,
    holding_venue: str | None,
    target_venue: str,
) -> None:
    """A print/signal may be submitted to at most one venue."""
    if holding_venue is not None and holding_venue != target_venue:
        raise LiveGatingError(
            f"no dual-fire same print {signal_id}: "
            f"holding={holding_venue} target={target_venue}"
        )


def exit_venue(holding_venue: str) -> str:
    """Exits follow the venue that holds the position. Never the other book."""
    if not holding_venue:
        raise LiveGatingError("exit requires a holding venue")
    return holding_venue


__all__ = [
    "PLANNED_SCHWAB_VENUE",
    "Broker",
    "OrderBroker",
    "VenueId",
    "exit_venue",
    "refuse_dual_fire",
]
