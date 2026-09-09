from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.account_events import (
    NEVER_ORDERS_NOTE,
    AccountEventStreamState,
    PositionTruth,
    ReconnectingAccountEventsClient,
    parse_account_event,
    public_account_events_ws,
    request_session_id,
    subscribe_payload,
)
from groktrading.feeds.finnhub import backoff_seconds
from groktrading.redaction import REDACTED
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _order(
    *,
    status: str,
    symbol: str | None = "NVDA260918P00170000",
    side: str | None = "buy_to_open",
    order_id: int = 1107075,
) -> str:
    body = {
        "id": order_id,
        "event": "order",
        "status": status,
        "type": "limit",
        "side": side,
        "option_symbol": symbol,
        "exec_quantity": 1.0 if status == "filled" else 0.0,
        "remaining_quantity": 0.0 if status == "filled" else 1.0,
        "transaction_date": "2026-09-09T16:29:50.000Z",
        "account": "ACCOUNT_ID_REDACTED",
    }
    return json.dumps(body)


def test_parse_fill_cancel_heartbeat_and_junk() -> None:
    fill = parse_account_event(_order(status="filled"))
    assert fill is not None
    assert fill.kind == "order"
    assert fill.material is True
    assert fill.material_kind == "fill"
    assert fill.symbol == "NVDA260918P00170000"
    cancel = parse_account_event(_order(status="canceled", side="buy_to_open"))
    assert cancel is not None
    assert cancel.material_kind == "cancel"
    beat = parse_account_event('{"event":"heartbeat"}')
    assert beat is not None
    assert beat.material is False
    assert beat.kind == "heartbeat"
    assert parse_account_event("not-json") is None
    assert parse_account_event(b"[1,2]") is None


def test_flatten_clears_in_position() -> None:
    truth = PositionTruth()
    open_fill = parse_account_event(_order(status="filled", side="buy_to_open"))
    assert open_fill is not None
    assert truth.apply(open_fill) is True
    assert "NVDA260918P00170000" in truth.open_symbols
    flat = parse_account_event(_order(status="filled", side="sell_to_close", order_id=99))
    assert flat is not None
    assert truth.apply(flat) is True
    assert truth.open_symbols == set()
    assert truth.last_material_kind == "fill"


def test_material_without_symbol_requests_rest_refresh() -> None:
    event = parse_account_event(_order(status="filled", symbol=None, side=None))
    assert event is not None
    assert event.needs_rest_refresh is True
    truth = PositionTruth()
    assert truth.apply(event) is True
    assert truth.needs_rest_refresh is True


def test_reconnect_backoff_and_listen_until() -> None:
    clock = FrozenClock(NOW)
    state = AccountEventStreamState(clock=clock, freshness_ttl_seconds=5)
    state.mark_connected()
    assert state.health().connected is True
    state.mark_disconnected()
    assert state.reconnect_attempt == 1
    assert state.next_backoff() == backoff_seconds(0)
    state.mark_disconnected()
    assert state.next_backoff() == backoff_seconds(1)
    clock._now = clock._now + timedelta(seconds=30)
    assert state.health().stale is True

    frames = [
        '{"event":"heartbeat"}',
        _order(status="filled", side="sell_to_close"),
    ]
    slept: list[float] = []
    errors = {"n": 0}

    def recv() -> str:
        if errors["n"] == 0:
            errors["n"] += 1
            raise ConnectionError("drop")
        return frames.pop(0)

    client = ReconnectingAccountEventsClient(state, recv)
    client.state.connected = False
    ticks = {"n": 0}

    def should_stop() -> bool:
        ticks["n"] += 1
        if ticks["n"] > 20:
            return True
        return not frames and errors["n"] > 0 and client.state.last_event is not None

    client.listen_until(should_stop=should_stop, sleep=slept.append)
    assert slept  # backoff after the first drop
    assert client.state.positions.last_material_kind == "fill"


def test_session_request_fail_closed_and_urls_have_no_secrets() -> None:
    class TimeoutHttp:
        def post_form(
            self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
        ) -> tuple[int, object]:
            raise TimeoutError("slow")

    class FakeHttp:
        def __init__(self, body: object, status: int = 200) -> None:
            self.body = body
            self.status = status
            self.urls: list[str] = []

        def post_form(
            self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
        ) -> tuple[int, object]:
            self.urls.append(url)
            return self.status, self.body

    with pytest.raises(TimeoutFailClosedError):
        request_session_id(TimeoutHttp(), "unused-test-token", "sandbox")
    http = FakeHttp({"stream": {"sessionid": "SESSIONPLACEHOLDER"}})
    sid = request_session_id(http, "unused-test-token", "production")
    assert sid == "SESSIONPLACEHOLDER"
    assert http.urls == ["https://api.tradier.com/v1/accounts/events/session"]
    assert "token=" not in public_account_events_ws("production")
    assert public_account_events_ws("sandbox").startswith("wss://sandbox-ws.tradier.com")
    sub = subscribe_payload(True)
    assert sub["sessionid"] == REDACTED
    assert "order" in sub["events"]


def test_state_document_never_orders_and_has_no_account_id() -> None:
    clock = FrozenClock(NOW)
    state = AccountEventStreamState(clock=clock)
    state.mark_connected()
    event = parse_account_event(_order(status="filled"))
    assert event is not None
    state.on_event(event)
    doc = state.state_document()
    blob = json.dumps(doc)
    assert doc["places_orders"] is False
    assert NEVER_ORDERS_NOTE in doc["note"]
    assert "ACCOUNT_ID_REDACTED" not in blob
    assert "1107075" not in blob
    assert "submit" not in dir(ReconnectingAccountEventsClient)
    assert not hasattr(ReconnectingAccountEventsClient, "submit_option_order")
