from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from groktrading.errors import StaleDataError, TimeoutFailClosedError
from groktrading.feeds.tradier import PRODUCTION_REST, SANDBOX_REST, TradierClient, rest_base
from groktrading.feeds.unusual_whales import UnusualWhalesClient
from groktrading.timeutil import UTC


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
