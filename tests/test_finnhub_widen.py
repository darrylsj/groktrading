from __future__ import annotations

from typing import Any

import pytest

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.finnhub import (
    DEFAULT_WATCHLIST_BOUND,
    FINNHUB_NOT_NBBO_NOTE,
    FinnhubWatchlist,
    clamp_watch_widen_cap,
    overnight_news_batch,
    widen_for_risk_and_flow,
    widen_watchlist,
)


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


def test_widen_cap_and_priority() -> None:
    assert clamp_watch_widen_cap(8) == 16
    assert clamp_watch_widen_cap(99) == 40
    watch = FinnhubWatchlist(bound=DEFAULT_WATCHLIST_BOUND)
    watch.add("SPY")
    watch.add("QQQ")
    added = widen_for_risk_and_flow(
        watch,
        open_risk=["NVDA"],
        fresh_flow=["AMD", "NVDA", "IWM"],
        cap=32,
    )
    assert added == ["NVDA", "AMD", "IWM"]
    assert watch.bound == 32
    assert watch.symbols[:2] == ["SPY", "QQQ"]


def test_widen_stops_at_cap_without_raising() -> None:
    watch = FinnhubWatchlist(bound=16)
    extras = [f"T{i:02d}" for i in range(50)]
    added = widen_watchlist(watch, extras, cap=16)
    assert len(watch.symbols) == 16
    assert len(added) == 16


def test_overnight_news_batch_only_watch_symbols() -> None:
    http = FakeHttp(
        [{"headline": "chip news", "datetime": 1, "source": "wire", "id": 9}]
    )
    doc = overnight_news_batch(
        http,
        ["nvda", "amd", "nvda"],
        token="unused-test-token",
        from_date="2026-09-08",
        to_date="2026-09-09",
    )
    assert doc["option_nbbo"] is False
    assert FINNHUB_NOT_NBBO_NOTE in doc["note"]
    assert doc["places_orders"] is False
    assert doc["symbols"] == ["NVDA", "AMD"]
    assert doc["news"]["NVDA"][0]["headline"] == "chip news"
    assert all("/company-news?" in u for u in http.urls)
    assert "token=" not in "".join(http.urls)


def test_overnight_news_timeout_skips_symbol() -> None:
    http = FakeHttp({}, timeout=True)
    with pytest.raises(TimeoutFailClosedError):
        # probe itself fail-closes; batch catches and records
        from groktrading.feeds.finnhub import probe_company_news

        probe_company_news(
            http, "NVDA", token="unused-test-token", from_date="2026-09-08", to_date="2026-09-09"
        )
    doc = overnight_news_batch(
        FakeHttp({}, timeout=True),
        ["NVDA"],
        token="unused-test-token",
        from_date="2026-09-08",
        to_date="2026-09-09",
    )
    assert "NVDA" in doc["errors"]
    assert doc["news"] == {}
