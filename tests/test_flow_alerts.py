from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.flow_alerts import (
    DEFAULT_FLOW_ALERTS_POLL_SEC,
    FLOW_ALERT_EVENT,
    SeenAlertStore,
    extract_alert_id,
    flow_alerts_poll_sec,
    is_sit_match_shaped,
    poll_flow_alerts,
)
from groktrading.feeds.unusual_whales import UW_FLOW_ALERTS_PATH, UnusualWhalesClient
from groktrading.flow_ledger import FlowLedger
from groktrading.sit_match import REASON_STALE, SIT_MATCH_EVENT
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


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


def _alert(
    *,
    alert_id: str = "alert-1",
    executed_at: str = "2026-09-09T16:29:40Z",
    occ: str = "NVDA260918P00170000",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": alert_id,
        "ticker": "NVDA",
        "option_symbol": occ,
        "price": "1.07",
        "ask": "1.10",
        "type": "Puts",
        "executed_at": executed_at,
    }
    if extra:
        row.update(extra)
    return row


def _client(http: FakeHttp) -> UnusualWhalesClient:
    return UnusualWhalesClient(http=http, clock=FrozenClock(NOW), token="unused-test-token")


def test_extract_alert_id_and_sit_match_shaped() -> None:
    assert extract_alert_id(_alert()) == "alert-1"
    assert extract_alert_id({"alert_id": "x"}) == "x"
    assert extract_alert_id({"ticker": "NVDA"}) is None
    assert is_sit_match_shaped(_alert()) is True
    assert is_sit_match_shaped({"id": "1", "ticker": "NVDA"}) is False


def test_poll_emits_only_on_new_alert_id() -> None:
    body = {"data": [_alert(), _alert(alert_id="alert-2", extra={"n": "2"})]}
    http = FakeHttp(body)
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    seen = SeenAlertStore()
    emitted: list[str] = []
    first = poll_flow_alerts(
        _client(http),
        ledger,
        seen,
        now=NOW,
        on_material=lambda hit: emitted.append(str(hit.alert_id)),
    )
    assert first.fetched == 2
    assert first.new_ids == 2
    assert first.emitted == 2
    assert first.stored == 2
    assert emitted == ["alert-1", "alert-2"]
    assert all(h.event_type == FLOW_ALERT_EVENT for h in first.hits if h.emit)
    assert list(ledger.iter_recent(limit=5, source="flow-alerts"))
    assert UW_FLOW_ALERTS_PATH in http.urls[0]

    second = poll_flow_alerts(
        _client(http),
        ledger,
        seen,
        now=NOW + timedelta(seconds=20),
        on_material=lambda hit: emitted.append(str(hit.alert_id)),
    )
    assert second.new_ids == 0
    assert second.emitted == 0
    assert second.stored == 2  # digest-idempotent append returns existing
    assert emitted == ["alert-1", "alert-2"]


def test_missing_alert_id_stores_but_does_not_emit() -> None:
    payload = _alert()
    del payload["id"]
    http = FakeHttp({"data": [payload]})
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    seen = SeenAlertStore()
    result = poll_flow_alerts(_client(http), ledger, seen, now=NOW)
    assert result.stored == 1
    assert result.emitted == 0
    assert result.hits[0].skip_reason == "missing_alert_id"


def test_sit_match_shaped_stale_does_not_emit_sit_match() -> None:
    stale = _alert(executed_at="2026-09-09T13:30:00Z")
    http = FakeHttp({"data": [stale]})
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    seen = SeenAlertStore()
    result = poll_flow_alerts(
        _client(http), ledger, seen, now=NOW, emit_sit_match=True
    )
    assert result.stored == 1
    assert result.emitted == 0
    assert result.hits[0].event_type is None
    assert result.hits[0].sit_match is not None
    assert result.hits[0].sit_match.reason == REASON_STALE

    fresh = _alert(alert_id="fresh", executed_at="2026-09-09T16:29:40Z")
    http2 = FakeHttp({"data": [fresh]})
    ok = poll_flow_alerts(
        _client(http2), ledger, seen, now=NOW, emit_sit_match=True
    )
    assert ok.emitted == 1
    assert ok.hits[0].event_type == SIT_MATCH_EVENT


def test_cadence_clamp_and_timeout_fail_closed() -> None:
    assert flow_alerts_poll_sec({}) == DEFAULT_FLOW_ALERTS_POLL_SEC
    assert flow_alerts_poll_sec({"FLOW_ALERTS_POLL_SEC": "5"}) == 15.0
    assert flow_alerts_poll_sec({"FLOW_ALERTS_POLL_SEC": "90"}) == 30.0
    http = FakeHttp({}, timeout=True)
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    with pytest.raises(TimeoutFailClosedError):
        poll_flow_alerts(_client(http), ledger, SeenAlertStore(), now=NOW)


def test_option_chain_alias_is_sit_match_shaped() -> None:
    payload = {
        "id": "oc-1",
        "ticker": "SPXW",
        "option_chain": "spxw260930p07500000",
        "price": "1.25",
        "ask": "1.30",
        "type": "Puts",
        "executed_at": "2026-09-09T16:29:40Z",
    }
    assert is_sit_match_shaped(payload) is True
    created_only = dict(payload)
    del created_only["executed_at"]
    created_only["created_at"] = "2026-09-09T16:29:50Z"
    assert is_sit_match_shaped(created_only) is False


def test_seen_after_append_retries_store_failure() -> None:
    """H1: marking seen before append would drop a later complete row."""
    incomplete = {
        "id": "retry-me",
        "executed_at": "2026-09-09T16:29:40Z",
        "price": "1.07",
        "ask": "1.10",
        "type": "Puts",
    }
    complete = _alert(alert_id="retry-me")
    ledger = FlowLedger(":memory:", clock=FrozenClock(NOW))
    seen = SeenAlertStore()
    first = poll_flow_alerts(
        _client(FakeHttp({"data": [incomplete]})), ledger, seen, now=NOW
    )
    assert first.stored == 0
    assert first.emitted == 0
    assert first.hits[0].skip_reason == "store_failed"
    assert seen.known("retry-me") is False
    second = poll_flow_alerts(
        _client(FakeHttp({"data": [complete]})), ledger, seen, now=NOW
    )
    assert second.stored == 1
    assert second.emitted == 1
    assert seen.known("retry-me") is True


def test_seen_store_persists(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "seen.json"
    store = SeenAlertStore(path)
    assert store.remember("a") is True
    assert store.remember("a") is False
    again = SeenAlertStore(path)
    assert again.known("a") is True
