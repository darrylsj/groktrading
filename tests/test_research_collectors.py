from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from groktrading.research.capture import (
    ReadFeed,
    allowed_read_path,
    classify_uw_revision,
    provider_aggressor,
)
from groktrading.research.cli import demo
from groktrading.research.collectors import (
    FinnhubRest,
    account_alias,
    archived_news_detail,
    collect_context,
    collect_economic_calendar,
    collect_portfolio,
    write_expanded_context,
)
from groktrading.research.cycle import (
    CATEGORIES,
    OPTIONAL_CATEGORIES,
    Context,
    FailureRecord,
    failure_from_exception,
    write_failure,
)
from groktrading.research.opening15 import Config, Event, Packet, window
from groktrading.research.registry import freeze_active, propose, seed_registry, set_status


def _config() -> Config:
    return Config.model_validate_json(Path("research/opening15.example.json").read_text())


def _clock(at: datetime) -> Any:
    return lambda: at


def _uw_economic_body(*, empty: bool = False) -> dict[str, Any]:
    if empty:
        return {"data": []}
    return {
        "data": [
            {
                "event": "CPI",
                "forecast": "0.2%",
                "prev": "0.1%",
                "reported_period": "Aug 2026",
                "time": "2026-09-08T12:30:00Z",
                "type": "economic",
            }
        ]
    }


def _calendar_body() -> dict[str, Any]:
    days = []
    for day in range(1, 31):
        iso = date(2026, 9, day).isoformat()
        weekday = date(2026, 9, day).weekday()
        closed = weekday >= 5 or day == 7
        days.append(
            {
                "date": iso,
                "status": "closed" if closed else "open",
                "description": "holiday" if day == 7 else "",
                "open": None if closed else {"start": "09:30", "end": "16:00"},
            }
        )
    return {"calendar": {"month": 9, "year": 2026, "days": {"day": days}}}


def _history(symbol: str) -> dict[str, Any]:
    return {
        "history": {
            "symbol": symbol,
            "day": [
                {
                    "date": "2026-09-03",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 1000,
                },
                {
                    "date": "2026-09-04",
                    "open": 10.5,
                    "high": 12,
                    "low": 10,
                    "close": 11,
                    "volume": 1100,
                },
            ],
        }
    }


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    symbol = request.url.params.get("symbol") or request.url.params.get("symbols", "")
    if path.endswith("/api/news/headlines"):
        ticker = request.url.params.get("ticker", "AAPL")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": f"{ticker}-1",
                        "headline": f"{ticker} preopen headline",
                        "created_at": "2026-09-08T10:00:00+00:00",
                    }
                ]
            },
        )
    if path.endswith("/api/market/economic-calendar"):
        return httpx.Response(200, json=_uw_economic_body())
    if "/api/darkpool/recent" in path:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "ticker": "AAPL",
                        "price": 190.5,
                        "size": 10000,
                        "executed_at": "2026-09-08T12:00:00Z",
                    },
                    {
                        "ticker": "ZZZZ",
                        "price": 1.0,
                        "size": 50,
                        "executed_at": "2026-09-08T12:01:00Z",
                    },
                ]
            },
        )
    if "/api/darkpool/" in path:
        ticker = path.rstrip("/").split("/")[-1]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "ticker": ticker,
                        "price": 100.25,
                        "size": 2500,
                        "executed_at": "2026-09-08T11:55:00Z",
                    }
                ]
            },
        )
    if path.endswith("/api/screener/option-contracts"):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "ticker_symbol": "AAPL",
                        "option_symbol": "AAPL260911C00100000",
                        "type": "call",
                        "strike": 100,
                        "avg_price": 1.05,
                        "volume": 500,
                    },
                    {
                        "ticker_symbol": "OTHER",
                        "option_symbol": "OTHER260911C00100000",
                        "type": "call",
                        "avg_price": 2.0,
                    },
                ]
            },
        )
    if path.endswith("/api/market/market-tide"):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "timestamp": "2026-09-08T13:00:00Z",
                        "net_call_premium": 1000,
                        "net_put_premium": 800,
                    }
                ]
            },
        )
    if path.endswith("/api/congress/recent-trades"):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "ticker": "MSFT",
                        "txn_type": "Buy",
                        "amounts": "$1,000 - $15,000",
                        "filed_at_date": "2026-09-04",
                        "name": "Fixture Member",
                    },
                    {
                        "ticker": "NOTINUNIVERSE",
                        "txn_type": "Sell",
                        "amounts": "$15,001 - $50,000",
                    },
                ]
            },
        )
    if path.endswith("/api/insider/transactions"):
        return httpx.Response(200, json={"data": []})
    if path.endswith("/markets/quotes"):
        rows = []
        for item in symbol.split(","):
            if item == "$VIX.X":
                continue
            rows.append(
                {
                    "symbol": item,
                    "last": 100,
                    "bid": 99.9,
                    "ask": 100.1,
                    "delayed": False,
                    "trade_date": int(datetime(2026, 9, 8, 13, 10, tzinfo=UTC).timestamp() * 1000),
                }
            )
        return httpx.Response(200, json={"quotes": {"quote": rows}})
    if path.endswith("/markets/calendar"):
        return httpx.Response(200, json=_calendar_body())
    if path.endswith("/markets/history"):
        return httpx.Response(200, json=_history(symbol))
    if path.endswith("/markets/options/expirations"):
        return httpx.Response(
            200, json={"expirations": {"date": ["2026-09-11", "2026-09-18", "2026-10-16"]}}
        )
    if path.endswith("/markets/options/chains"):
        return httpx.Response(
            200,
            json={
                "options": {
                    "option": [
                        {
                            "symbol": f"{symbol}260911C00100000",
                            "option_type": "call",
                            "strike": 100,
                            "expiration_date": request.url.params.get("expiration"),
                            "bid": 1.0,
                            "ask": 1.1,
                            "bidsize": 10,
                            "asksize": 12,
                            "open_interest": 500,
                            "greeks": {"delta": 0.5},
                        }
                    ]
                }
            },
        )
    if path.endswith("/balances"):
        return httpx.Response(
            200,
            json={
                "balances": {
                    "account_number": "SHOULD-NOT-APPEAR",
                    "total_cash": 1000,
                    "total_equity": 1200,
                    "account_type": "margin",
                    "margin": {"option_buying_power": 800},
                    "pending_orders_count": 0,
                }
            },
        )
    if path.endswith("/positions"):
        return httpx.Response(
            200,
            json={"positions": {"position": {"symbol": "SPY", "quantity": 1, "cost_basis": 10}}},
        )
    if path.endswith("/orders"):
        return httpx.Response(200, json={"orders": {"order": []}})
    if path.endswith("/news"):
        return httpx.Response(
            200,
            json=[
                {
                    "id": 77,
                    "headline": "Overnight policy event",
                    "datetime": int(datetime(2026, 9, 8, 6, 0, tzinfo=UTC).timestamp()),
                    "source": "fixture-wire",
                    "summary": "Broad market",
                    "category": "general",
                    "url": "https://example.com/news/77",
                }
            ],
        )
    return httpx.Response(404, json={"error": "unexpected"})


def _feeds() -> tuple[ReadFeed, ReadFeed, FinnhubRest]:
    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    finnhub = FinnhubRest(
        "test-only",
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    uw.interval = tradier.interval = finnhub.interval = 0
    return uw, tradier, finnhub


def test_classify_uw_revisions() -> None:
    assert classify_uw_revision({"tags": ["ask_side"]}) == "print"
    assert classify_uw_revision({"tags": ["cancelled"]}) == "cancellation"
    assert classify_uw_revision({"trade_codes": ["correction"]}) == "correction"
    assert provider_aggressor({"tags": ["ask_side"]}) == {"label": "ask_side", "source": "uw_tag"}
    assert provider_aggressor({"price": 1, "nbbo_bid": 0.9, "nbbo_ask": 1.1}) == {
        "label": "unknown",
        "source": "not_supplied",
    }


def test_collectors_fill_context_with_mocked_http(tmp_path: Path) -> None:
    config = _config()
    uw, tradier, finnhub = _feeds()
    start, _ = window(date(2026, 9, 8))
    at = start - timedelta(minutes=20)
    news = [
        Event(
            event_id="news:AAPL:1",
            kind="news",
            symbol="AAPL",
            event_at=at - timedelta(hours=2),
            received_at=at,
            source="uw",
            raw={
                "id": "aapl-story",
                "headline": "AAPL revision one",
                "created_at": "2026-09-08T08:00:00+00:00",
            },
        ),
        Event(
            event_id="news:AAPL:2",
            kind="news",
            symbol="AAPL",
            event_at=at - timedelta(hours=1),
            received_at=at,
            source="uw",
            raw={
                "id": "aapl-story",
                "headline": "AAPL revision two",
                "created_at": "2026-09-08T09:00:00+00:00",
            },
        ),
    ]
    flow = [
        Event(
            event_id="uw:1",
            kind="option_trade",
            symbol="AAPL",
            event_at=start + timedelta(minutes=1),
            received_at=start + timedelta(minutes=1),
            source="uw",
            raw={"option_chain_id": "AAPL260911C00100000", "tags": ["earnings", "ask_side"]},
        )
    ]
    context = collect_context(
        config=config,
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=finnhub,
        account_id="RESEARCH1",
        news_events=news,
        flow_events=flow,
        clock=_clock(at),
    )
    by_cat = {entry.category: entry.status for entry in context.coverage}
    assert by_cat["company_news"] == "partial"
    assert by_cat["world_news"] == "available"
    macro = next(entry for entry in context.coverage if entry.category == "macro")
    assert macro.status == "partial"
    assert "$VIX.X" in macro.detail
    assert by_cat["calendar"] == "available"
    assert by_cat["option_chain"] == "available"
    assert by_cat["history"] == "available"
    assert by_cat["portfolio"] == "available"
    assert by_cat["depth"] == "missing"
    assert by_cat["dark_pool"] == "available"
    assert by_cat["option_screener"] == "available"
    assert by_cat["market_tide"] == "available"
    assert by_cat["political"] == "available"
    assert set(by_cat) == CATEGORIES
    payload = json.dumps(context.model_dump(mode="json"))
    assert "SHOULD-NOT-APPEAR" not in payload
    assert "account_number" not in payload
    assert account_alias("RESEARCH1") in payload
    assert "tradier_read_only_until_schwab_oauth" in payload
    assert any(r.evidence_id.startswith("company-news:aapl-story:v2") for r in context.records)
    assert any(r.evidence_id == "calendar:print-earnings" for r in context.records)
    econ = next(r for r in context.records if r.evidence_id == "calendar:uw-economic")
    assert econ.payload["event_count"] == 1
    assert "actual" not in econ.payload
    assert any(r.evidence_id == "darkpool:AAPL" for r in context.records)
    congress = next(r for r in context.records if r.evidence_id == "political:uw-congress")
    assert congress.payload["row_count"] == 1
    assert congress.payload["trades"][0]["ticker"] == "MSFT"
    assert not any(r.evidence_id == "political:uw-insider" for r in context.records)
    chain = next(r for r in context.records if r.category == "option_chain")
    assert chain.payload["contracts"][0]["open_interest_label"] == "prior_day_provider_field"
    hist = next(r for r in context.records if r.evidence_id == "history:AAPL")
    assert hist.payload["excluded_on_or_after"] == "2026-09-08"
    assert all(bar["date"] < "2026-09-08" for bar in hist.payload["bars"])
    detail = archived_news_detail(context, "company-news:aapl-story:v1")
    assert detail["payload"]["version"] == 1
    demo(tmp_path / "demo", config)
    packet = Packet.model_validate_json((tmp_path / "demo/packet.json").read_text())
    with pytest.raises(ValueError, match="degraded"):
        context.for_selection(packet)
    context.for_selection(packet, allow_degraded=True)
    uw.close()
    tradier.close()
    finnhub.close()


def test_world_news_and_portfolio_missing_when_unused() -> None:
    config = _config()
    uw, tradier, _ = _feeds()
    start, _ = window(date(2026, 9, 8))
    context = collect_context(
        config=config,
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=None,
        account_id=None,
        clock=_clock(start - timedelta(minutes=10)),
    )
    status = {entry.category: entry.status for entry in context.coverage}
    assert status["world_news"] == "missing"
    assert status["portfolio"] == "missing"
    world = next(c.detail for c in context.coverage if c.category == "world_news")
    assert "Not fabricated" in world
    assert "Schwab" in next(c.detail for c in context.coverage if c.category == "portfolio")
    uw.close()
    tradier.close()


class _AccountFeed:
    """Minimal ReadFeed stand-in for portfolio payload-shape tests."""

    def __init__(
        self,
        *,
        balances: Any = None,
        positions: Any = None,
        orders: Any = None,
    ) -> None:
        self.balances = (
            balances
            if balances is not None
            else {
                "balances": {
                    "account_number": "SHOULD-NOT-APPEAR",
                    "total_cash": 1000,
                    "total_equity": 1200,
                    "account_type": "margin",
                    "margin": {"option_buying_power": 800},
                }
            }
        )
        self.positions = positions if positions is not None else {"positions": {"position": []}}
        self.orders = orders

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if path.endswith("/balances"):
            return self.balances
        if path.endswith("/positions"):
            return self.positions
        if path.endswith("/orders"):
            return self.orders
        raise ValueError("read endpoint not allowed")


def _portfolio_clock() -> Any:
    return _clock(datetime(2026, 9, 8, 13, 10, tzinfo=UTC))


def test_portfolio_null_string_orders_is_empty_working() -> None:
    """Tradier XML-JSON often emits {\"orders\": \"null\"}; that is an empty book, not a crash."""
    records, coverage = collect_portfolio(
        tradier=_AccountFeed(orders={"orders": "null"}),
        account_id="RESEARCH1",
        clock=_portfolio_clock(),
    )
    assert coverage.status == "available"
    assert coverage.category == "portfolio"
    assert "no working orders" in coverage.detail
    assert records[0].payload["working_orders"] == []
    blob = json.dumps(records[0].model_dump(mode="json"))
    assert "SHOULD-NOT-APPEAR" not in blob
    assert "RESEARCH1" not in blob
    assert records[0].payload["account_alias"] == account_alias("RESEARCH1")
    assert records[0].payload["account_alias"].startswith("acct-")


def test_portfolio_mixed_order_rows_keep_dicts() -> None:
    records, coverage = collect_portfolio(
        tradier=_AccountFeed(
            orders={
                "orders": {
                    "order": [
                        "junk",
                        {
                            "symbol": "AAPL",
                            "status": "open",
                            "side": "buy",
                            "quantity": 1,
                            "type": "limit",
                        },
                    ]
                }
            }
        ),
        account_id="RESEARCH1",
        clock=_portfolio_clock(),
    )
    assert coverage.status == "available"
    assert records[0].payload["working_orders"] == [
        {"symbol": "AAPL", "side": "buy", "quantity": 1, "status": "open", "type": "limit"}
    ]


def test_portfolio_string_order_rows_fail_closed() -> None:
    """List-of-strings / unexpected order rows must not be treated as an empty book."""
    records, coverage = collect_portfolio(
        tradier=_AccountFeed(orders={"orders": {"order": ["open", "pending"]}}),
        account_id="RESEARCH1",
        clock=_portfolio_clock(),
    )
    assert records == []
    assert coverage.status == "missing"
    assert "orders unusable" in coverage.detail
    assert "Working orders not assumed empty" in coverage.detail
    assert "RESEARCH1" not in coverage.detail


def test_collect_context_survives_crashing_orders_payload() -> None:
    """Host crash: AttributeError on str.get from unexpected Tradier orders shapes."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/orders"):
            return httpx.Response(200, json={"orders": {"order": ["open", "filled"]}})
        return _handler(request)

    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    finnhub = FinnhubRest(
        "test-only",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uw.interval = tradier.interval = finnhub.interval = 0
    start, _ = window(date(2026, 9, 8))
    context = collect_context(
        config=_config(),
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=finnhub,
        account_id="SECRETACCT99",
        clock=_clock(start - timedelta(minutes=10)),
    )
    by_cat = {entry.category: entry.status for entry in context.coverage}
    assert set(by_cat) == CATEGORIES
    assert by_cat["portfolio"] == "missing"
    portfolio = next(entry for entry in context.coverage if entry.category == "portfolio")
    assert "orders unusable" in portfolio.detail
    assert "Working orders not assumed empty" in portfolio.detail
    assert by_cat["macro"] == "partial"
    blob = json.dumps(context.model_dump(mode="json"))
    assert "SECRETACCT99" not in blob
    assert "account_number" not in blob
    uw.close()
    tradier.close()
    finnhub.close()


def test_collect_context_survives_orders_null_string_wrapper() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/orders"):
            return httpx.Response(200, json={"orders": "null"})
        return _handler(request)

    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uw.interval = tradier.interval = 0
    start, _ = window(date(2026, 9, 8))
    context = collect_context(
        config=_config(),
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=None,
        account_id="SECRETACCT99",
        clock=_clock(start - timedelta(minutes=10)),
    )
    portfolio = next(entry for entry in context.coverage if entry.category == "portfolio")
    assert portfolio.status == "available"
    record = next(item for item in context.records if item.category == "portfolio")
    assert record.payload["working_orders"] == []
    assert record.payload["account_alias"] == account_alias("SECRETACCT99")
    blob = json.dumps(context.model_dump(mode="json"))
    assert "SECRETACCT99" not in blob
    uw.close()
    tradier.close()


def test_finnhub_entitlement_sets_world_news_missing() -> None:
    config = _config()
    uw, tradier, _ = _feeds()
    denied = FinnhubRest(
        "test-only",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403, json={}))),
    )
    denied.interval = 0
    start, _ = window(date(2026, 9, 8))
    context = collect_context(
        config=config,
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=denied,
        account_id=None,
        clock=_clock(start - timedelta(minutes=10)),
    )
    assert next(c.status for c in context.coverage if c.category == "world_news") == "missing"
    uw.close()
    tradier.close()
    denied.close()


def test_write_context_and_failure_record(tmp_path: Path) -> None:
    config = _config()
    uw, tradier, finnhub = _feeds()
    start, _ = window(date(2026, 9, 8))
    write_expanded_context(
        config=config,
        session=date(2026, 9, 8),
        directory=tmp_path,
        uw=uw,
        tradier=tradier,
        news_events=[],
        flow_events=[],
        finnhub=finnhub,
        account_id="RESEARCH1",
        clock=_clock(start - timedelta(minutes=15)),
    )
    Context.model_validate_json((tmp_path / "context.json").read_text())
    assert (tmp_path / "raw/uw-economic-calendar.json").is_file()
    assert (tmp_path / "raw/uw-darkpool-AAPL.json").is_file()
    assert (tmp_path / "raw/uw-darkpool-recent.json").is_file()
    assert (tmp_path / "raw/uw-option-screener.json").is_file()
    assert (tmp_path / "raw/uw-market-tide.json").is_file()
    assert (tmp_path / "raw/uw-congress-recent.json").is_file()
    record = failure_from_exception(
        session=date(2026, 9, 8),
        stage="select",
        exc=ValueError("expanded context incomplete; explicit degraded research mode required"),
        directory=tmp_path / "failed-select",
    )
    write_failure(tmp_path / "failed-select", record)
    loaded = FailureRecord.model_validate_json(
        (tmp_path / "failed-select/failure-record.json").read_text()
    )
    assert loaded.status == "failed"
    assert loaded.decision_hash is None
    assert "pnl" not in loaded.model_dump()
    uw.close()
    tradier.close()
    finnhub.close()


def test_prompt_registry_is_immutable_file_based(tmp_path: Path) -> None:
    registry = seed_registry()
    assert registry.active_version_id == "selector_v2"
    assert all(item.status == "accepted" for item in registry.versions)
    proposed = propose(
        registry,
        version_id="selector_v2_shadow",
        prompt_name="selector_v2.md",
        parent_version="selector_v2",
        hypothesis="Test a wording change on future sessions only",
        proposed_difference="Shadow arm; do not modify confirmatory selector_v2",
        forward_test="Equal evidence/compute on later sessions; no retrospective fit",
    )
    assert proposed.get("selector_v2_shadow").status == "proposed"
    shadowed = set_status(proposed, "selector_v2_shadow", "shadow")
    frozen_at = datetime.fromisoformat("2026-09-08T12:00:00+00:00")
    frozen = freeze_active(shadowed, "selector_v2", frozen_at)
    assert frozen.active_version_id == "selector_v2"
    with pytest.raises(ValueError, match="already exists"):
        propose(
            proposed,
            version_id="selector_v2_shadow",
            prompt_name="selector_v2.md",
            parent_version="selector_v2",
            hypothesis="dup",
            proposed_difference="dup",
            forward_test="dup",
        )
    with pytest.raises(ValueError, match="accepted or shadow"):
        freeze_active(proposed, "selector_v2_shadow", frozen_at)


def test_option_chain_subset_is_partial_not_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/options/expirations"):
            symbol = request.url.params.get("symbol")
            if symbol != "AAPL":
                return httpx.Response(200, json={"expirations": {"date": []}})
        return _handler(request)

    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uw.interval = tradier.interval = 0
    start, _ = window(date(2026, 9, 8))
    context = collect_context(
        config=_config(),
        session=date(2026, 9, 8),
        uw=uw,
        tradier=tradier,
        finnhub=None,
        account_id=None,
        clock=_clock(start - timedelta(minutes=10)),
    )
    chain = next(entry for entry in context.coverage if entry.category == "option_chain")
    assert chain.status == "partial"
    assert "AAPL" not in chain.detail or "per_symbol_missing" in chain.detail
    assert "MSFT" in chain.detail
    uw.close()
    tradier.close()


def test_portfolio_unknown_cash_or_bp_is_not_available() -> None:
    records, coverage = collect_portfolio(
        tradier=_AccountFeed(balances={"balances": {"account_type": "margin", "total_equity": 10}}),
        account_id="RESEARCH1",
        clock=_portfolio_clock(),
    )
    assert records == []
    assert coverage.status == "missing"
    assert "buying power" in coverage.detail.lower() or "cash" in coverage.detail.lower()


def test_chain_preserves_provider_quote_timestamps_and_stamps_after_http() -> None:
    ticks = {"n": 0}

    def clock() -> datetime:
        ticks["n"] += 1
        return datetime(2026, 9, 8, 13, 10, ticks["n"], tzinfo=UTC)

    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/options/chains"):
            seen.append(ticks["n"])
            return httpx.Response(
                200,
                json={
                    "options": {
                        "option": [
                            {
                                "symbol": "AAPL260911C00100000",
                                "option_type": "call",
                                "strike": 100,
                                "expiration_date": "2026-09-11",
                                "bid": 1.0,
                                "ask": 1.1,
                                "bidsize": 10,
                                "asksize": 12,
                                "open_interest": 500,
                                "bid_date": int(
                                    datetime(2026, 9, 8, 13, 10, tzinfo=UTC).timestamp() * 1000
                                ),
                                "ask_date": int(
                                    datetime(2026, 9, 8, 13, 10, tzinfo=UTC).timestamp() * 1000
                                ),
                            }
                        ]
                    }
                },
            )
        return _handler(request)

    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tradier.interval = 0
    from groktrading.research.collectors import collect_option_chain

    records, coverage = collect_option_chain(
        config=_config(),
        session=date(2026, 9, 8),
        tradier=tradier,
        clock=clock,
    )
    assert coverage.status == "available"
    contract = records[0].payload["contracts"][0]
    assert contract["bid_date"]
    assert contract["ask_date"]
    assert "quote_ages_seconds" in contract
    assert records[0].received_at > datetime(2026, 9, 8, 13, 10, 0, tzinfo=UTC)
    assert seen and all(n >= 0 for n in seen)
    tradier.close()


def test_optional_collectors_timeout_does_not_abort_baseline(tmp_path: Path) -> None:
    from groktrading.research.capture import isolate_optional_collectors

    def hang(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("finnhub hung")

    import groktrading.research.collectors as collectors

    original = collectors.write_expanded_context
    collectors.write_expanded_context = hang  # type: ignore[method-assign]
    try:
        isolate_optional_collectors(
            config=_config(),
            session=date(2026, 9, 8),
            directory=tmp_path,
            uw=None,  # type: ignore[arg-type]
            tradier=None,  # type: ignore[arg-type]
            news_events=[],
            deadline=datetime(2026, 9, 8, 13, 30, tzinfo=UTC),
        )
    finally:
        collectors.write_expanded_context = original  # type: ignore[method-assign]
    failure = json.loads((tmp_path / "context-failed.json").read_text())
    assert "hung" in failure["detail"] or failure["detail"] == "TimeoutError"
    assert "baseline packet still captured" in failure["note"]
    assert not (tmp_path / "packet.json").exists()


def test_optional_collectors_hang_returns_at_budget_not_at_completion(tmp_path: Path) -> None:
    """Regression: a collector that hangs must not hold the opening tape past its budget.

    The previous `with ThreadPoolExecutor` form called shutdown(wait=True) on exit and
    blocked until the hung thread finished, delaying stock capture past 09:30.
    """
    import threading
    import time

    from groktrading.research.capture import isolate_optional_collectors
    from groktrading.research.opening15 import now_utc

    started = threading.Event()

    def hang(*args: Any, **kwargs: Any) -> None:
        started.set()
        time.sleep(2.0)  # simulates a collector stuck in an HTTP call past the budget

    import groktrading.research.collectors as collectors

    original = collectors.write_expanded_context
    collectors.write_expanded_context = hang  # type: ignore[method-assign]
    budget = 0.3
    t0 = time.monotonic()
    try:
        isolate_optional_collectors(
            config=_config(),
            session=date(2026, 9, 8),
            directory=tmp_path,
            uw=None,  # type: ignore[arg-type]
            tradier=None,  # type: ignore[arg-type]
            news_events=[],
            deadline=now_utc() + timedelta(seconds=budget),
        )
        elapsed = time.monotonic() - t0
    finally:
        # Let the abandoned thread finish before restoring the module attribute.
        time.sleep(2.2)
        collectors.write_expanded_context = original  # type: ignore[method-assign]
    assert started.is_set()
    assert elapsed < 1.0, f"returned after {elapsed:.2f}s; must return at budget, not completion"
    failure = json.loads((tmp_path / "context-failed.json").read_text())
    assert failure["detail"] == "expanded collectors exceeded preopen budget"
    assert "baseline packet still captured" in failure["note"]


def test_day_plan_creates_outcome_context_step(tmp_path: Path) -> None:
    from groktrading.research.cycle_cli import tuesday_commands

    plan = tuesday_commands(date(2026, 9, 8), tmp_path, allow_degraded=False)
    expanded = " ".join(plan["expanded"])
    assert "outcome-context.json" in expanded
    assert "collect-context" in expanded
    assert plan["expanded"][-3].endswith("outcome-context.json  # post-session outcome collector")
    assert "--allow-degraded" not in " ".join(plan["baseline"])
    assert "research.cli run" in plan["baseline"][-1]
    assert "clean baseline" in plan["note"]
    assert "Post-Tue paper days" in plan["note"]
    assert "default to expanded select" in plan["note"]


def test_day_plan_and_fail_cli(tmp_path: Path, monkeypatch: Any) -> None:
    from groktrading.research import cycle_cli

    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "day-plan",
            "--session",
            "2026-09-08",
            "--out",
            str(tmp_path / "plan.json"),
            "--allow-degraded",
        ],
    )
    cycle_cli.main()
    plan = json.loads((tmp_path / "plan.json").read_text())
    expected = "research.cli run --session 2026-09-08 --output " + tmp_path.as_posix()
    assert plan["baseline"][-1].endswith(expected)
    assert "--allow-degraded" in " ".join(plan["expanded"])
    assert "cycle_cli select" in " ".join(plan["expanded"])
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "fail",
            "--session",
            "2026-09-08",
            "--stage",
            "select",
            "--detail",
            "expanded context incomplete",
            "--out",
            str(tmp_path / "failed"),
        ],
    )
    cycle_cli.main()
    failure_path = tmp_path / "failed/failure-record.json"
    loaded = FailureRecord.model_validate_json(failure_path.read_text())
    assert loaded.stage == "select"
    assert loaded.decision_hash is None


def test_allowed_uw_expanded_paths() -> None:
    assert allowed_read_path("/api/market/economic-calendar")
    assert allowed_read_path("/api/darkpool/AAPL")
    assert allowed_read_path("/api/darkpool/recent")
    assert allowed_read_path("/api/screener/option-contracts")
    assert allowed_read_path("/api/market/market-tide")
    assert allowed_read_path("/api/congress/recent-trades")
    assert allowed_read_path("/api/insider/transactions")
    assert not allowed_read_path("/api/darkpool/../secret")
    assert not allowed_read_path("/api/options/flow")


def test_uw_economic_calendar_empty_data_is_available(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/market/economic-calendar"):
            return httpx.Response(200, json=_uw_economic_body(empty=True))
        return _handler(request)

    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uw.interval = 0
    start, _ = window(date(2026, 9, 8))
    records, coverage = collect_economic_calendar(
        uw=uw,
        clock=_clock(start - timedelta(minutes=20)),
        directory=tmp_path,
    )
    assert coverage.status == "available"
    assert records[0].payload["event_count"] == 0
    assert records[0].payload["events"] == []
    assert "actual" not in records[0].payload
    assert (tmp_path / "raw/uw-economic-calendar.json").is_file()
    uw.close()


def test_uw_expanded_http_failure_does_not_abort_baseline(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/api/darkpool/" in path or path.endswith(
            (
                "/api/market/economic-calendar",
                "/api/screener/option-contracts",
                "/api/market/market-tide",
                "/api/congress/recent-trades",
                "/api/insider/transactions",
            )
        ):
            return httpx.Response(403, json={"error": "forbidden"})
        return _handler(request)

    uw = ReadFeed(
        "https://api.unusualwhales.com",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tradier = ReadFeed(
        "https://api.tradier.com/v1",
        "test-only",
        120,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    uw.interval = tradier.interval = 0
    start, _ = window(date(2026, 9, 8))
    from groktrading.research.capture import isolate_optional_collectors

    isolate_optional_collectors(
        config=_config(),
        session=date(2026, 9, 8),
        directory=tmp_path,
        uw=uw,
        tradier=tradier,
        news_events=[],
        deadline=start,
    )
    assert not (tmp_path / "context-failed.json").exists()
    context = Context.model_validate_json((tmp_path / "context.json").read_text())
    by_cat = {entry.category: entry.status for entry in context.coverage}
    assert by_cat["calendar"] == "partial"
    assert by_cat["dark_pool"] == "missing"
    assert by_cat["option_screener"] == "missing"
    assert by_cat["market_tide"] == "missing"
    assert by_cat["political"] == "missing"
    assert by_cat["option_chain"] == "available"
    assert not (tmp_path / "packet.json").exists()
    uw.close()
    tradier.close()


def test_optional_uw_categories_do_not_force_degraded(tmp_path: Path) -> None:
    config = _config()
    demo(tmp_path / "demo", config)
    packet = Packet.model_validate_json((tmp_path / "demo/packet.json").read_text())
    end = window(packet.session)[1]
    required = CATEGORIES - OPTIONAL_CATEGORIES
    from groktrading.research.cycle import Coverage, Evidence

    ctx = Context(
        session=packet.session,
        frozen_at=end,
        records=[
            Evidence(
                evidence_id=c,
                category=c,  # type: ignore[arg-type]
                symbols=[],
                source="synthetic",
                source_uri="fixture",
                as_of=end,
                received_at=end,
                summary="Synthetic test evidence",
                payload={"value": 1},
            )
            for c in sorted(required)
        ],
        coverage=[
            Coverage(
                category=c,  # type: ignore[arg-type]
                status="available" if c in required else "missing",
                detail="fixture",
            )
            for c in sorted(CATEGORIES)
        ],
    )
    ctx.for_selection(packet, allow_degraded=False)
