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
