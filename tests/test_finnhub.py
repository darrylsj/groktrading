from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from groktrading.errors import WatchlistBoundError
from groktrading.feeds.finnhub import (
    FinnhubStreamState,
    FinnhubWatchlist,
    backoff_seconds,
    parse_finnhub_message,
    public_ws_url,
)
from groktrading.io_atomic import write_json_atomic
from groktrading.redaction import REDACTED
from groktrading.timeutil import UTC


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


TRADE_FRAME = json.dumps(
    {
        "type": "trade",
        "data": [
            {"s": "SPY", "p": 561.25, "t": 1690000000000, "v": 10, "c": ["@"]},
            {"s": "QQQ", "p": 480.1, "t": 1690000000001, "v": 2},
        ],
    }
)


def test_parse_trade_and_ignore_ping() -> None:
    trades = parse_finnhub_message(TRADE_FRAME)
    assert [t.symbol for t in trades] == ["SPY", "QQQ"]
    assert trades[0].price == 561.25
    assert parse_finnhub_message('{"type":"ping"}') == []
    assert parse_finnhub_message(b'{"type":"trade","data":[]}') == []


def test_parse_skips_incomplete_rows() -> None:
    raw = json.dumps({"type": "trade", "data": [{"s": "SPY"}, {"p": 1, "t": 1, "s": "IWM"}]})
    trades = parse_finnhub_message(raw)
    assert [t.symbol for t in trades] == ["IWM"]


def test_watchlist_bound() -> None:
    watch = FinnhubWatchlist(bound=2)
    watch.add("spy")
    watch.add("SPY")
    watch.add("QQQ")
    with pytest.raises(WatchlistBoundError):
        watch.add("IWM")
    msgs = watch.subscribe_messages()
    assert json.loads(msgs[0]) == {"type": "subscribe", "symbol": "SPY"}


def test_backoff_and_reconnect_state() -> None:
    assert backoff_seconds(0) == 1.0
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(10) == 60.0
    clock = FrozenClock(datetime(2026, 9, 3, 14, 0, tzinfo=UTC))
    state = FinnhubStreamState(watchlist=FinnhubWatchlist(), clock=clock, freshness_ttl_seconds=5)
    state.watchlist.add("SPY")
    state.mark_connected()
    state.on_trades(parse_finnhub_message(TRADE_FRAME))
    assert state.health().connected is True
    assert state.health().stale is False
    state.mark_disconnected()
    assert state.reconnect_attempt == 1
    assert state.next_backoff() == backoff_seconds(0)
    state.mark_disconnected()
    assert state.next_backoff() == backoff_seconds(1)
    clock._now = clock._now + timedelta(seconds=30)
    assert state.health().stale is True


def test_ws_url_never_embeds_secret() -> None:
    text = public_ws_url(token_present=True)
    assert "placeholder" not in text or REDACTED in text
    assert "wss://ws.finnhub.io" in public_ws_url(False)


def test_atomic_redacted_tape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "tape.json"
    write_json_atomic(
        path,
        {"token": "super-secret", "FINNHUB_API_KEY": "abc", "trades": []},
    )
    loaded = json.loads(path.read_text())
    assert loaded["token"] == REDACTED
    assert loaded["FINNHUB_API_KEY"] == REDACTED
