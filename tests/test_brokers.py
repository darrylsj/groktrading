"""Phase A dual-broker protocol: Tradier extract, recording stub, Schwab placeholder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from groktrading.brokers import (
    SCHWAB_OAUTH_NOT_READY,
    SCHWAB_VENUE_ID,
    RecordingBroker,
    RecordingOrderBroker,
    SchwabBroker,
    TradierBroker,
    exit_venue,
    refuse_dual_fire,
    require_schwab_ready,
)
from groktrading.errors import LiveGatingError, TimeoutFailClosedError
from groktrading.executor import BrokerSink, Executor
from groktrading.feeds.tradier import PRODUCTION_REST, TradierClient
from groktrading.models import OrderState
from groktrading.modes import OperatingMode
from groktrading.order_fsm import (
    MemoryOrderStore,
    OrderMachine,
    payload_from_candidate,
    tradier_form,
)
from groktrading.timeutil import UTC
from helpers import morning_pt, passing_candidate, passing_context


class ScriptedHttp:
    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = routes or {}
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.deletes: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        self.gets.append(url)
        path = url.removeprefix(PRODUCTION_REST)
        if path in self.routes:
            return 200, self.routes[path]
        for key, body in self.routes.items():
            if path.startswith(key):
                return 200, body
        return 200, {}

    def post_form(
        self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        self.posts.append((url, dict(data)))
        return 200, {"id": "ord-live-1", "status": "ok", "preview": data.get("preview")}

    def delete(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        self.deletes.append(url)
        return 200, {"status": "canceled"}


class ClockObj:
    def now(self) -> datetime:
        return datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


def _tradier(http: ScriptedHttp, env: str = "production") -> TradierBroker:
    client = TradierClient(
        http=http,
        clock=ClockObj(),
        token="unused-test-token",
        account_id="PAPERACCOUNT",
        env=env,  # type: ignore[arg-type]
    )
    return TradierBroker(client=client)


def test_tradier_broker_venue_and_thin_quote_wrap() -> None:
    bid_ms = int(datetime(2026, 9, 3, 14, 29, 58, tzinfo=UTC).timestamp() * 1000)
    ask_ms = int(datetime(2026, 9, 3, 14, 29, 59, tzinfo=UTC).timestamp() * 1000)
    http = ScriptedHttp(
        {
            "/markets/quotes": {
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
            },
            "/accounts/PAPERACCOUNT/balances": {
                "balances": {
                    "total_cash": "600",
                    "option_buying_power": "600",
                    "total_equity": "600",
                }
            },
            "/accounts/PAPERACCOUNT/positions": {
                "positions": {"position": {"option_symbol": "QQQ260903C00400000"}}
            },
            "/accounts/PAPERACCOUNT/orders": {"orders": {"order": []}},
            "/markets/clock": {"clock": {"state": "open"}},
        }
    )
    broker = _tradier(http)
    assert broker.venue_id == "tradier"
    quote = broker.quote_option("SPY260903C00600000")
    assert quote.source == "tradier_production"
    assert str(quote.bid) == "1.20"
    assert str(quote.ask) == "1.25"
    snap = broker.snapshot_account()
    assert snap.cash == snap.equity
    assert broker.positions() == ["QQQ260903C00400000"]
    assert broker.market_clock().state.value == "open"
    assert broker.balances().buying_power == snap.buying_power


def test_tradier_broker_preview_submit_match_client_form() -> None:
    http = ScriptedHttp()
    broker = _tradier(http)
    candidate = passing_candidate()
    payload = payload_from_candidate(candidate)
    preview_form = tradier_form(payload, preview=True)
    submit_form = tradier_form(payload, preview=False)
    preview = broker.preview_option_order(preview_form)
    submit = broker.submit_option_order(submit_form)
    assert preview["preview"] == "true"
    assert submit["preview"] == "false"
    assert submit["id"] == "ord-live-1"
    assert http.posts[0][1] == preview_form
    assert http.posts[1][1] == submit_form
    assert http.posts[0][1]["preview"] == "true"
    assert {k: v for k, v in http.posts[0][1].items() if k != "preview"} == {
        k: v for k, v in http.posts[1][1].items() if k != "preview"
    }
    assert http.posts[0][0] == f"{PRODUCTION_REST}/accounts/PAPERACCOUNT/orders"


def test_tradier_broker_find_and_cancel_entry_only() -> None:
    http = ScriptedHttp(
        {
            "/accounts/PAPERACCOUNT/orders": {
                "orders": {
                    "order": [
                        {
                            "id": "e1",
                            "tag": "sig-1",
                            "status": "open",
                            "side": "buy_to_open",
                            "option_symbol": "SPY260903C00600000",
                        },
                        {
                            "id": "x1",
                            "tag": "exit-1",
                            "status": "open",
                            "side": "sell_to_close",
                            "option_symbol": "SPY260903C00600000",
                        },
                        {
                            "id": "done",
                            "status": "filled",
                            "side": "buy_to_open",
                            "option_symbol": "QQQ260903C00400000",
                        },
                    ]
                }
            }
        }
    )
    broker = _tradier(http)
    found = broker.find_order_by_tag("sig-1")
    assert found is not None
    assert found["id"] == "e1"
    canceled = broker.cancel_working_entry_orders()
    assert canceled == ["e1"]
    assert http.deletes == [f"{PRODUCTION_REST}/accounts/PAPERACCOUNT/orders/e1"]


def test_order_machine_recording_broker_equivalent_to_order_broker() -> None:
    full = RecordingBroker()
    subset = RecordingOrderBroker()
    now = morning_pt()
    candidate = passing_candidate()
    for sink in (full, subset):
        machine = OrderMachine(
            store=MemoryOrderStore(),
            broker=sink,
            mode=OperatingMode.PAPER,
        )
        ticket = machine.receive(candidate, now)
        ticket = machine.validate(ticket.ticket_id, now)
        ticket = machine.attach_quote(ticket.ticket_id, now)
        ticket, preview = machine.preview(ticket.ticket_id, now)
        assert preview["preview"] is True
        ticket, result = machine.final_gate(
            ticket.ticket_id, candidate, passing_context(), now
        )
        assert result.allowed is True
        ticket, body = machine.submit(ticket.ticket_id, now)
        assert ticket.state == OrderState.ACK
        assert body["id"] == "brk-1"
        assert sink.previews[0]["preview"] == "true"
        assert sink.submits[0]["preview"] == "false"
    assert full.venue_id == "tradier"


def test_executor_paper_path_uses_broker_sink() -> None:
    broker = RecordingBroker()
    exe = Executor(mode=OperatingMode.PAPER, sink=BrokerSink(broker))
    ctx = passing_context(mode=OperatingMode.PAPER, preview_ok=True)
    exe.maybe_submit(passing_candidate(), ctx)
    assert len(broker.previews) == 1
    assert broker.previews[0]["preview"] == "true"
    assert broker.submits == []


def test_refuse_dual_fire_and_exits_follow_holding_venue() -> None:
    refuse_dual_fire(signal_id="sig-1", holding_venue=None, target_venue="tradier")
    refuse_dual_fire(signal_id="sig-1", holding_venue="tradier", target_venue="tradier")
    with pytest.raises(LiveGatingError, match="no dual-fire"):
        refuse_dual_fire(
            signal_id="sig-1", holding_venue="tradier", target_venue=SCHWAB_VENUE_ID
        )
    assert exit_venue("tradier") == "tradier"
    with pytest.raises(LiveGatingError, match="holding venue"):
        exit_venue("")


def test_schwab_broker_oauth_not_ready_no_secrets() -> None:
    assert "OAuth not ready" in SCHWAB_OAUTH_NOT_READY
    assert "secret" not in SCHWAB_OAUTH_NOT_READY.lower()
    assert "token" not in SCHWAB_OAUTH_NOT_READY.lower()
    with pytest.raises(NotImplementedError, match="OAuth not ready"):
        SchwabBroker()
    with pytest.raises(NotImplementedError, match="OAuth not ready"):
        SchwabBroker(token="should-not-be-accepted")  # noqa: S106
    with pytest.raises(NotImplementedError, match="OAuth not ready"):
        require_schwab_ready()


def test_tradier_cancel_timeout_fail_closed() -> None:
    class BoomHttp(ScriptedHttp):
        def delete(
            self, url: str, headers: dict[str, str] | None = None
        ) -> tuple[int, Any]:
            raise TimeoutError("slow")

    http = BoomHttp(
        {
            "/accounts/PAPERACCOUNT/orders": {
                "orders": {
                    "order": {
                        "id": "e1",
                        "status": "open",
                        "side": "buy_to_open",
                    }
                }
            }
        }
    )
    broker = _tradier(http)
    with pytest.raises(TimeoutFailClosedError):
        broker.cancel_working_entry_orders()
