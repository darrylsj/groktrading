"""In-memory brokers for tests. No network. No credentials."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from groktrading.brokers.protocol import VenueId
from groktrading.models import AccountSnapshot, ClockSnapshot, MarketState, OptionQuote
from groktrading.timeutil import UTC


class RecordingOrderBroker:
    """OrderBroker stub used by OrderMachine tests. No network. No credentials."""

    def __init__(self) -> None:
        self.previews: list[dict[str, str]] = []
        self.submits: list[dict[str, str]] = []
        self.known_by_tag: dict[str, dict[str, Any]] = {}
        self.submit_acks: bool = True
        self.next_broker_id: str = "brk-1"

    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        self.previews.append(payload)
        return {"status": "ok", "preview": True, "tag": payload.get("tag")}

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        self.submits.append(payload)
        if not self.submit_acks:
            return {"status": "unknown"}
        row = {"id": self.next_broker_id, "tag": payload.get("tag"), "status": "ok"}
        tag = payload.get("tag")
        if tag:
            self.known_by_tag[tag] = row
        return row

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None:
        return self.known_by_tag.get(tag)


class RecordingBroker(RecordingOrderBroker):
    """Full Broker stub. Default venue is Tradier so OrderMachine stays equivalent."""

    venue_id: VenueId = "tradier"

    def __init__(self) -> None:
        super().__init__()
        now = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
        self.account = AccountSnapshot(
            cash=Decimal("600"),
            buying_power=Decimal("600"),
            working_option_symbols=[],
            open_position_symbols=[],
            as_of=now,
            equity=Decimal("600"),
        )
        self.open_positions: list[str] = []
        self.clock = ClockSnapshot(state=MarketState.OPEN, as_of=now)
        self.quote: OptionQuote | None = None
        self.quote_symbols: list[str] = []
        self.cancel_calls = 0
        self.canceled_ids: list[str] = []

    def balances(self) -> AccountSnapshot:
        return self.account

    def positions(self) -> list[str]:
        return list(self.open_positions)

    def quote_option(self, option_symbol: str) -> OptionQuote:
        self.quote_symbols.append(option_symbol)
        if self.quote is not None:
            return self.quote
        now = self.account.as_of
        return OptionQuote(
            option_symbol=option_symbol,
            bid=Decimal("1.20"),
            ask=Decimal("1.25"),
            quote_ts=now,
            source="tradier_production",
            delayed=False,
            bid_date=now,
            ask_date=now,
            received_ts=now,
            provider_symbol=option_symbol,
        )

    def snapshot_account(self) -> AccountSnapshot:
        return self.account.model_copy(
            update={"open_position_symbols": list(self.open_positions)}
        )

    def market_clock(self) -> ClockSnapshot:
        return self.clock

    def cancel_working_entry_orders(self) -> list[str]:
        self.cancel_calls += 1
        return list(self.canceled_ids)


__all__ = ["RecordingBroker", "RecordingOrderBroker"]
