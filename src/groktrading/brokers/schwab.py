"""SchwabBroker — OAuth scaffolding only; no live order or quote HTTP.

Construction fails closed without Ready For Use + env credentials + a local
token file. Even when those are present, preview/submit/quote raise
``NotImplementedError`` (Phase B/C). This module never accepts tokens as
constructor arguments and never invents a token file.
"""

from __future__ import annotations

from typing import Any, Literal

from groktrading.brokers.schwab_oauth import (
    CALLBACK_URL,
    ENV_APP_KEY,
    ENV_APP_SECRET,
    ENV_TOKEN_PATH,
    require_auth_ready,
    stub_message,
)
from groktrading.errors import SchwabAuthNotReady
from groktrading.models import AccountSnapshot, ClockSnapshot, OptionQuote

SCHWAB_OAUTH_NOT_READY = (
    "Schwab OAuth not ready — no live Schwab calls from this package"
)

# Not on VenueId until Phase B. Documented so adapters do not invent a second id.
SCHWAB_VENUE_ID: Literal["schwab"] = "schwab"

_HELPER = "python -m groktrading.brokers.schwab_oauth"


def _construction_refused(*args: object, **kwargs: object) -> SchwabAuthNotReady:
    if args or kwargs:
        return SchwabAuthNotReady(
            f"{SCHWAB_OAUTH_NOT_READY}. SchwabBroker does not accept credentials "
            f"or tokens as constructor arguments. Set {ENV_APP_KEY} / "
            f"{ENV_APP_SECRET} (optional {ENV_TOKEN_PATH}), wait for Ready For Use, "
            f"and run {_HELPER}."
        )
    return SchwabAuthNotReady(
        f"{SCHWAB_OAUTH_NOT_READY}. Complete Schwab developer app Ready For Use, "
        f"set {ENV_APP_KEY} and {ENV_APP_SECRET} (optional {ENV_TOKEN_PATH}), "
        f"callback {CALLBACK_URL} (no trailing slash), then run {_HELPER}.\n"
        f"{stub_message()}"
    )


class SchwabBroker:
    """Unimplemented Schwab venue. Auth-not-ready or Phase B/C HTTP gap."""

    venue_id: Literal["schwab"] = SCHWAB_VENUE_ID

    def __init__(self, *args: object, **kwargs: object) -> None:
        if args or kwargs:
            raise _construction_refused(*args, **kwargs)
        try:
            require_auth_ready()
        except SchwabAuthNotReady as exc:
            raise _construction_refused() from exc
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
    """Factory hook. Auth must be ready; order HTTP is still Phase B/C."""
    try:
        require_auth_ready()
    except SchwabAuthNotReady as exc:
        raise _construction_refused() from exc
    raise NotImplementedError(SCHWAB_OAUTH_NOT_READY)


__all__ = [
    "SCHWAB_OAUTH_NOT_READY",
    "SCHWAB_VENUE_ID",
    "SchwabBroker",
    "require_schwab_ready",
]
