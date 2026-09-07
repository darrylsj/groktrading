"""SchwabBroker placeholder — OAuth not ready.

Phase B/C will implement this after Schwab OAuth is Ready For Use.
This module accepts no credentials, stores no secrets, and makes no
network calls. Instantiation and every surface raise the same error.
"""

from __future__ import annotations

from typing import Any, Literal

from groktrading.models import AccountSnapshot, ClockSnapshot, OptionQuote

SCHWAB_OAUTH_NOT_READY = (
    "Schwab OAuth not ready — no live Schwab calls from this package"
)

# Not on VenueId until Phase B. Documented so adapters do not invent a second id.
SCHWAB_VENUE_ID: Literal["schwab"] = "schwab"


class SchwabBroker:
    """Unimplemented Schwab venue. Raises on construction. No secrets."""

    venue_id: Literal["schwab"] = SCHWAB_VENUE_ID

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def balances(self) -> AccountSnapshot:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def positions(self) -> list[str]:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def quote_option(self, option_symbol: str) -> OptionQuote:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def snapshot_account(self) -> AccountSnapshot:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def market_clock(self) -> ClockSnapshot:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)

    def cancel_working_entry_orders(self) -> list[str]:
        raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)


def require_schwab_ready() -> None:
    """Factory hook for Phase B. Always refuses until OAuth Ready For Use."""
    raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)


__all__ = [
    "SCHWAB_OAUTH_NOT_READY",
    "SCHWAB_VENUE_ID",
    "SchwabBroker",
    "require_schwab_ready",
]
