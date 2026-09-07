from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from groktrading.research.capture import (
    ReadFeed,
    classify_uw_revision,
    provider_aggressor,
)
from groktrading.research.cli import demo
from groktrading.research.collectors import (
    FinnhubRest,
    account_alias,
    archived_news_detail,
    collect_context,
    collect_portfolio,
    write_expanded_context,
)
from groktrading.research.cycle import (
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
    payload = json.dumps(context.model_dump(mode="json"))
    assert "SHOULD-NOT-APPEAR" not in payload
    assert "account_number" not in payload
    assert account_alias("RESEARCH1") in payload
    assert "tradier_read_only_until_schwab_oauth" in payload
    assert any(r.evidence_id.startswith("company-news:aapl-story:v2") for r in context.records)
    assert any(r.evidence_id == "calendar:print-earnings" for r in context.records)
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
        self.balances = balances if balances is not None else {
            "balances": {
                "account_number": "SHOULD-NOT-APPEAR",
                "total_cash": 1000,
                "total_equity": 1200,
                "account_type": "margin",
                "margin": {"option_buying_power": 800},
            }
        }
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
    assert set(by_cat) == {
        "company_news",
        "world_news",
        "macro",
        "calendar",
        "option_chain",
        "history",
        "portfolio",
        "depth",
    }
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
