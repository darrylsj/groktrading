from __future__ import annotations

from datetime import datetime
from typing import Any

from groktrading.feeds.screener_snapshot import (
    DEFAULT_SCREENER_POLL_SEC,
    fetch_screener_snapshot,
    screener_poll_sec,
    write_screener_state,
)
from groktrading.feeds.unusual_whales import UW_SCREENER_PATH, UnusualWhalesClient
from groktrading.timeutil import UTC

RTH = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)  # 09:30 PT Wednesday
AH = datetime(2026, 9, 9, 22, 0, 0, tzinfo=UTC)  # 15:00 PT


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class FakeHttp:
    def __init__(self, body: Any) -> None:
        self.body = body
        self.urls: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        self.urls.append(url)
        return 200, self.body


def test_rth_snapshot_does_not_emit_sit_match(tmp_path) -> None:  # type: ignore[no-untyped-def]
    http = FakeHttp(
        {
            "data": [
                {
                    "ticker_symbol": "NVDA",
                    "option_symbol": "NVDA260918P00170000",
                    "avg_price": "1.10",
                    "premium": "50000",
                }
            ]
        }
    )
    client = UnusualWhalesClient(
        http=http, clock=FrozenClock(RTH), token="unused-test-token"
    )
    path = tmp_path / "screener_state.json"
    doc = write_screener_state(client, path, now=RTH, clock_state="open")
    assert path.is_file()
    assert doc["emits_sit_match"] is False
    assert doc["places_orders"] is False
    assert doc["wrote"] is True
    assert doc["row_count"] == 1
    assert UW_SCREENER_PATH in http.urls[0]


def test_after_hours_skips_write(tmp_path) -> None:  # type: ignore[no-untyped-def]
    http = FakeHttp({"data": [{"ticker_symbol": "NVDA"}]})
    client = UnusualWhalesClient(
        http=http, clock=FrozenClock(AH), token="unused-test-token"
    )
    path = tmp_path / "screener_state.json"
    snap = fetch_screener_snapshot(client, now=AH, clock_state="closed")
    assert snap.wrote is False
    assert snap.skipped_reason == "not_rth"
    doc = write_screener_state(client, path, now=AH, clock_state="closed")
    assert path.exists() is False
    assert doc["emits_sit_match"] is False
    assert http.urls == []


def test_screener_cadence_clamp() -> None:
    assert screener_poll_sec({}) == DEFAULT_SCREENER_POLL_SEC
    assert screener_poll_sec({"SCREENER_POLL_SEC": "60"}) == 300.0
    assert screener_poll_sec({"SCREENER_POLL_SEC": "9999"}) == 900.0
