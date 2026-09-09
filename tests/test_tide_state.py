from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.tide_state import (
    DEFAULT_TIDE_POLL_SEC,
    fetch_tide_snapshot,
    tide_poll_sec,
    write_tide_state,
)
from groktrading.feeds.unusual_whales import (
    UW_MARKET_TIDE_PATH,
    UnusualWhalesClient,
    net_prem_ticks_path,
)
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeHttp:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        self.urls.append(url)
        for key, body in self.routes.items():
            if key in url:
                if body == "timeout":
                    raise TimeoutError("slow")
                return 200, body
        return 404, {}


def _client(http: FakeHttp) -> UnusualWhalesClient:
    return UnusualWhalesClient(http=http, clock=FrozenClock(), token="unused-test-token")


def test_tide_and_optional_net_prem(tmp_path) -> None:  # type: ignore[no-untyped-def]
    http = FakeHttp(
        {
            UW_MARKET_TIDE_PATH: {
                "data": [
                    {
                        "timestamp": "2026-09-09T16:25:00Z",
                        "net_call_premium": "1.2",
                        "net_put_premium": "0.8",
                        "net_volume": 10,
                    }
                ]
            },
            "/api/stock/NVDA/net-prem-ticks": {
                "data": [{"timestamp": "2026-09-09T16:24:00Z", "net_call_premium": "3"}]
            },
        }
    )
    out = tmp_path / "tide_state.json"
    doc = write_tide_state(_client(http), out, now=NOW, net_prem_symbols=["nvda", "../x"])
    assert out.is_file()
    assert doc["places_orders"] is False
    assert doc["emits_sit_match"] is False
    assert doc["tick_count"] == 1
    assert doc["ticks"][0]["net_call_premium"] == "1.2"
    assert "NVDA" in doc["net_prem"]
    assert "../x" not in doc["net_prem"]
    assert any(UW_MARKET_TIDE_PATH in u for u in http.urls)
    assert any("/api/stock/NVDA/net-prem-ticks" in u for u in http.urls)


def test_net_prem_path_rejects_junk() -> None:
    with pytest.raises(ValueError):
        net_prem_ticks_path("../etc")
    with pytest.raises(ValueError):
        net_prem_ticks_path("nv da")


def test_cadence_and_tide_timeout() -> None:
    assert tide_poll_sec({}) == DEFAULT_TIDE_POLL_SEC
    assert tide_poll_sec({"TIDE_POLL_SEC": "10"}) == 60.0
    assert tide_poll_sec({"TIDE_POLL_SEC": "999"}) == 300.0
    http = FakeHttp({UW_MARKET_TIDE_PATH: "timeout"})
    with pytest.raises(TimeoutFailClosedError):
        fetch_tide_snapshot(_client(http), now=NOW)
