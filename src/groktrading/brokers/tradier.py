"""TradierBroker — thin venue adapter over the existing TradierClient.

No rewrite of quote, account, or order HTTP. Live form bodies stay exactly
as `order_fsm.tradier_form` already emits them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from groktrading.brokers.protocol import VenueId
from groktrading.feeds.tradier import TradierClient
from groktrading.models import AccountSnapshot, ClockSnapshot, OptionQuote


@dataclass
class TradierBroker:
    """Phase A live/paper venue. Delegates 1:1 to TradierClient."""

    client: TradierClient
    venue_id: VenueId = "tradier"

    def balances(self) -> AccountSnapshot:
        return self.client.balances()

    def positions(self) -> list[str]:
        return self.client.position_symbols()

    def quote_option(self, option_symbol: str) -> OptionQuote:
        return self.client.quote_option(option_symbol)

    def snapshot_account(self) -> AccountSnapshot:
        return self.client.snapshot_account()

    def market_clock(self) -> ClockSnapshot:
        return self.client.market_clock()

    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        body = self.client.preview_option_order(payload)
        return body if isinstance(body, dict) else {"result": body}

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        body = self.client.submit_option_order(payload)
        return body if isinstance(body, dict) else {"result": body}

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None:
        return self.client.find_order_by_tag(tag)

    def cancel_working_entry_orders(self) -> list[str]:
        return self.client.cancel_working_entry_orders()


__all__ = ["TradierBroker"]
