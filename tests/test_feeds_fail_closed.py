from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from groktrading.errors import BalancesParseError, StaleDataError, TimeoutFailClosedError
from groktrading.feeds.tradier import (
    PRODUCTION_REST,
    SANDBOX_REST,
    TradierClient,
    parse_tradier_balances,
    rest_base,
)
from groktrading.feeds.unusual_whales import UnusualWhalesClient
from groktrading.timeutil import UTC

# Documented cash-account shape (docs.tradier.com/docs/balances). Numbers are
# the public doc example (available vs unsettled), not a live book.
TRADIER_CASH_ACCOUNT_BALANCES = {
    "option_short_value": 0,
    "total_equity": "5653.38",
    "account_type": "cash",
    "close_pl": 0,
    "current_requirement": 0,
    "equity": 0,
    "long_market_value": 0,
    "market_value": 0,
    "open_pl": 0,
    "option_long_value": 0,
    "pending_orders_count": 0,
    "short_market_value": 0,
    "stock_long_value": 0,
    "total_cash": "5653.38",
    "uncleared_funds": 0,
    "pending_cash": 0,
    "cash": {
        "cash_available": "4343.38",
        "sweep": 0,
        "unsettled_funds": "1310.00",
    },
}


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeHttp:
    def __init__(self, body: Any, status: int = 200, timeout: bool = False) -> None:
        self.body = body
        self.status = status
        self.timeout = timeout
        self.urls: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        if self.timeout:
            raise TimeoutError("slow")
        self.urls.append(url)
        return self.status, self.body

    def post_form(
        self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        if self.timeout:
            raise TimeoutError("slow")
        return self.status, {"preview": True, "data": data}

    def delete(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        if self.timeout:
            raise TimeoutError("slow")
        self.urls.append(url)
        return self.status, {"status": "canceled"}


def test_tradier_env_urls_and_timeout() -> None:
    assert rest_base("production") == PRODUCTION_REST
    assert rest_base("sandbox") == SANDBOX_REST
    clock = FrozenClock(datetime(2026, 9, 3, 15, 0, tzinfo=UTC))
    client = TradierClient(
        http=FakeHttp({}, timeout=True),
        clock=clock,
        token="unused-test-token",
        account_id="PAPERACCOUNT",
        env="sandbox",
    )
    with pytest.raises(TimeoutFailClosedError):
        client.quote_option("SPY260903C00600000")


def test_tradier_quote_uses_provider_dates_not_http_time() -> None:
    clock = FrozenClock(datetime(2026, 9, 3, 15, 0, tzinfo=UTC))
    bid_ms = int(datetime(2026, 9, 3, 14, 59, 58, tzinfo=UTC).timestamp() * 1000)
    ask_ms = int(datetime(2026, 9, 3, 14, 59, 59, tzinfo=UTC).timestamp() * 1000)
    http = FakeHttp(
        {
            "quotes": {
                "quote": {
                    "symbol": "SPY260903C00600000",
                    "bid": "1.20",
                    "ask": "1.25",
                    "bid_date": bid_ms,
                    "ask_date": ask_ms,
                    "delayed": False,
                }
            }
        }
    )
    client = TradierClient(
        http=http,
        clock=clock,
        token="unused-test-token",
        account_id="PAPERACCOUNT",
        env="production",
    )
    quote = client.quote_option("SPY260903C00600000")
    assert quote.source == "tradier_production"
    assert quote.delayed is False
    assert quote.bid_date is not None
    assert quote.ask_date is not None
    assert quote.received_ts == clock.now()
    assert quote.quote_ts == quote.ask_date
    assert quote.provider_symbol == "SPY260903C00600000"


def test_tradier_cash_account_bp_excludes_unsettled() -> None:
    clock = FrozenClock(datetime(2026, 9, 3, 15, 0, tzinfo=UTC))
    http = FakeHttp({"balances": TRADIER_CASH_ACCOUNT_BALANCES})
    client = TradierClient(
        http=http,
        clock=clock,
        token="unused-test-token",
        account_id="PAPERACCOUNT",
        env="production",
    )
    snap = client.balances()
    available = Decimal("4343.38")
    unsettled = Decimal("1310.00")
    total_cash = available + unsettled
    assert snap.cash == available
    assert snap.buying_power == available
    assert snap.buying_power != total_cash
    assert snap.buying_power < total_cash
    parsed = parse_tradier_balances(TRADIER_CASH_ACCOUNT_BALANCES, as_of=clock.now())
    assert parsed.buying_power == available
    assert parsed.buying_power != Decimal(str(TRADIER_CASH_ACCOUNT_BALANCES["total_cash"]))


def test_tradier_margin_uses_nested_option_buying_power() -> None:
    as_of = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    snap = parse_tradier_balances(
        {
            "account_type": "margin",
            "total_cash": "900",
            "total_equity": "800",
            "margin": {"option_buying_power": "600", "stock_buying_power": "1200"},
        },
        as_of=as_of,
    )
    assert snap.buying_power == Decimal("600")
    assert snap.cash == Decimal("600")
    assert snap.cash != Decimal("900")
    assert snap.buying_power != Decimal("1200")
    assert snap.equity == Decimal("800")
    pdt = parse_tradier_balances(
        {"account_type": "pdt", "pdt": {"option_buying_power": "550"}},
        as_of=as_of,
    )
    assert pdt.buying_power == Decimal("550")


def test_tradier_balances_missing_nested_fields_raise() -> None:
    as_of = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    with pytest.raises(
        BalancesParseError,
        match="tradier_balances_missing_cash_available_or_option_buying_power",
    ):
        parse_tradier_balances(
            {
                "account_type": "cash",
                "total_cash": "5653.38",
                "option_buying_power": "5653.38",
                "stock_buying_power": "5653.38",
            },
            as_of=as_of,
        )


def test_uw_stale_fail_closed() -> None:
    clock = FrozenClock(datetime(2026, 9, 3, 15, 0, tzinfo=UTC))
    client = UnusualWhalesClient(
        http=FakeHttp({"data": []}),
        clock=clock,
        token="unused-test-token",
        freshness_ttl_seconds=1,
    )
    with pytest.raises(StaleDataError):
        client.require_fresh()
    client.get_documented_path("/api/option-trades")
    client.require_fresh()
