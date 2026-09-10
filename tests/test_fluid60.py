"""Behavioral checks of causal research trading, separate from live broker gates."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from groktrading.research.fluid60.cli import replay, synthetic_events, tune
from groktrading.research.fluid60.engine import PaperEngine
from groktrading.research.fluid60.feeds import (
    MBOBook,
    QuoteTerms,
    signed_option_flow,
    tradier_quote,
)
from groktrading.research.fluid60.policy import Intent, Position, choose, terminal_bids
from groktrading.research.fluid60.schema import (
    BookFrame,
    Config,
    Flows,
    Forecast,
    Level,
    Parameters,
    Quote,
)
from groktrading.research.fluid60.simulator import calibrate, consume, forecast, transport

AT = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)


def params(**updates: Any) -> Parameters:
    return Parameters.model_validate(
        {
            "source": "synthetic",
            "trained_through": AT - timedelta(days=1),
            "training_hash": "fixture",
            "observations": 10,
            **updates,
        }
    )


def config(**updates: Any) -> Config:
    return Config.model_validate({"symbols": ("AAPL", "MSFT"), "paths": 16, **updates})


def quote(at: datetime = AT, symbol: str = "AAPL", **updates: Any) -> Quote:
    return Quote.model_validate(
        {
            "event_id": f"{symbol}-{at.isoformat()}",
            "symbol": symbol,
            "underlying": symbol,
            "asset": "stock",
            "source": "synthetic",
            "event_at": at,
            "received_at": at,
            "bid": 99.99,
            "ask": 100.01,
            "bid_size": 100,
            "ask_size": 100,
            **updates,
        }
    )


def prediction(symbol: str = "AAPL", change: float = 0.5, at: datetime = AT) -> Forecast:
    return Forecast(
        symbol=symbol,
        at=at,
        expires_at=at + timedelta(seconds=60),
        mid=100,
        future_mids=(100 + change,) * 16,
        future_spreads=(0.02,) * 16,
        domain_failure_fraction=0,
        model_hash="fixture",
        data_hash="fixture",
        status="valid",
    )


def history(**flows: float) -> list[BookFrame]:
    return [
        BookFrame(
            event_id=str(j),
            symbol="AAPL",
            source="synthetic",
            interval_start=AT - timedelta(seconds=61 - j),
            event_at=AT - timedelta(seconds=60 - j),
            received_at=AT - timedelta(seconds=60 - j),
            bids=tuple(Level(price=99.99 - k * 0.01, size=100) for k in range(64)),
            asks=tuple(Level(price=100.01 + k * 0.01, size=100) for k in range(64)),
            flows=Flows.model_validate(flows),
        )
        for j in range(60)
    ]


def test_transport_conserves_mass_and_never_goes_negative() -> None:
    q = np.array([[0.0, 100.0, 20.0, 0.0], [10.0, 0.0, 0.0, 3.0]])
    for _ in range(60):
        q = transport(q, 0.15, -0.1)
        assert q.min() >= 0
        np.testing.assert_allclose(q.sum(axis=1), [120.0, 13.0])
    with pytest.raises(ValueError, match="unstable"):
        transport(q, 0.5, 0.1)


def test_queue_consumption_preserves_holes_and_excess_demand() -> None:
    q = np.array([[10.0, 0.0, 20.0], [0.0, 0.0, 5.0]])
    extra = consume(q, np.array([15.0, 8.0]))
    np.testing.assert_array_equal(q, [[0.0, 0.0, 15.0], [0.0, 0.0, 0.0]])
    np.testing.assert_array_equal(extra, [0.0, 3.0])


def test_pressure_moves_both_quotes_and_forecast_is_deterministic() -> None:
    h = history(buy=45, sell=5, bid_add=30, ask_add=30, bid_cancel=3, ask_cancel=3)
    p = params(diffusion_ticks2_per_second=0)
    f = forecast(h, AT, config(), p)
    assert f == forecast(h, AT, config(), p)
    assert f.status == "valid"
    assert np.mean(np.array(f.future_mids) - np.array(f.future_spreads) / 2) > h[-1].bids[0].price
    bearish = forecast(
        history(buy=5, sell=45, bid_add=30, ask_add=30, bid_cancel=3, ask_cancel=3), AT, config(), p
    )
    assert np.mean(bearish.future_mids) < np.mean(f.future_mids)


def test_exhausted_domain_is_rejected_not_scored_on_survivors() -> None:
    f = forecast(history(buy=100000), AT, config(), params())
    assert f.status == "out_of_domain"
    assert f.domain_failure_fraction == 1
    orders, _ = choose(AT, 25000, {}, {"AAPL": quote()}, {"AAPL": f}, config())
    assert orders == []


def test_forecast_rejects_future_fit_and_gaps() -> None:
    with pytest.raises(ValueError, match="trained"):
        forecast(history(), AT, config(), params(trained_through=AT))
    h = history()
    h[-1] = h[-1].model_copy(update={"complete": False})
    with pytest.raises(ValueError, match="incomplete"):
        forecast(h, AT, config(), params())
    h[-1] = history()[-1].model_copy(update={"interval_start": AT - timedelta(seconds=10)})
    with pytest.raises(ValueError, match="oversized"):
        forecast(h, AT, config(), params())


def test_positive_return_does_not_imply_trade_after_costs() -> None:
    orders, details = choose(
        AT, 25000, {}, {"AAPL": quote()}, {"AAPL": prediction(change=0.005)}, config()
    )
    assert orders == []
    assert details["buy_values"]["AAPL"] < 0  # type: ignore[index]


def test_one_buy_one_sell_globally_and_sunk_cost_is_ignored() -> None:
    positions = {"AAPL": Position("AAPL", 10, 1, 999999, AT - timedelta(minutes=1))}
    quotes = {"AAPL": quote(), "MSFT": quote(symbol="MSFT")}
    fs = {"AAPL": prediction(change=-0.5), "MSFT": prediction("MSFT", 0.5)}
    orders, _ = choose(AT, 24000, positions, quotes, fs, config())
    assert [(o.side, o.symbol) for o in orders] == [("sell", "AAPL"), ("buy", "MSFT")]
    positions["AAPL"] = replace(positions["AAPL"], entry_cost=1)
    assert orders == choose(AT, 24000, positions, quotes, fs, config())[0]


def test_reserve_and_one_lot_position_cap() -> None:
    qs, fs = {"AAPL": quote()}, {"AAPL": prediction()}
    assert choose(AT, 5000, {}, qs, fs, config())[0] == []
    assert choose(AT, 25000, {}, qs, fs, config(stock_lot=100))[0] == []


def test_risk_exit_backlog_sells_oldest_and_blocks_new_buys() -> None:
    ps = {
        s: Position(s, 10, 1, 1000, AT - timedelta(minutes=10 - i))
        for i, s in enumerate(("AAPL", "MSFT"))
    }
    qs = {s: quote(symbol=s) for s in ps}
    fs = {s: prediction(s) for s in ps}
    orders, details = choose(AT, 23000, ps, qs, fs, config())
    assert len(orders) == 1 and orders[0].symbol == "AAPL" and orders[0].side == "sell"
    assert details["reason"] == "risk_exit"


def test_put_delta_gamma_theta_and_vega_units() -> None:
    q = quote(
        symbol="PUT",
        underlying="AAPL",
        asset="put",
        multiplier=100,
        bid=2,
        ask=2.02,
        delta=-0.5,
        gamma=0.02,
        theta_per_day=-1.44,
        vega_per_vol_point=0.1,
        greeks_at=AT,
        expires_at=AT + timedelta(days=2),
    )
    bids = terminal_bids(q, prediction(change=-1), AT, config())
    # -0.5 * -1 + 0.5 * .02 * 1 - 1.44 / 1440 = .509 USD per share.
    np.testing.assert_allclose(bids[:3], [2.459, 2.509, 2.559])
    orders, _ = choose(AT, 25000, {}, {q.symbol: q}, {"AAPL": prediction(change=-1)}, config())
    assert orders[0].quantity == 1 and orders[0].multiplier == 100
    assert orders[0].symbol == "PUT"
    with pytest.raises(ValueError, match="stale_greeks"):
        terminal_bids(
            q.model_copy(update={"greeks_at": AT - timedelta(minutes=5)}),
            prediction(),
            AT,
            config(),
        )
    with pytest.raises(ValueError, match="near_expiry"):
        terminal_bids(
            q.model_copy(update={"expires_at": AT + timedelta(seconds=30)}),
            prediction(),
            AT,
            config(),
        )


def intent(side: str = "buy", symbol: str = "AAPL", at: datetime = AT) -> Intent:
    return Intent(
        symbol,
        "buy" if side == "buy" else "sell",
        10,
        1,
        100.015 if side == "buy" else 99.985,
        at,
        at + timedelta(seconds=1),
        at + timedelta(seconds=6),
        "test",
    )


def test_fills_require_future_event_time_size_and_limit() -> None:
    engine = PaperEngine(config(), params())
    engine.pending.append(intent())
    engine.ingest(quote(AT + timedelta(milliseconds=500)))
    assert not engine.fills
    engine.ingest(quote(AT + timedelta(seconds=1), event_at=AT))
    assert not engine.fills
    engine.ingest(quote(AT + timedelta(seconds=2), ask_size=1))
    assert not engine.fills
    engine.ingest(quote(AT + timedelta(seconds=3), ask=101))
    assert not engine.fills
    engine.ingest(quote(AT + timedelta(seconds=4)))
    assert len(engine.fills) == 1
    assert engine.fills[0]["price"] == pytest.approx(100.015)
    assert engine.cash == pytest.approx(23999.85)


def test_round_trip_uses_quoted_prices_and_both_fees() -> None:
    engine = PaperEngine(config(stock_fee_per_share=0.01), params())
    engine.pending.append(intent())
    engine.ingest(quote(AT + timedelta(seconds=1)))
    engine.pending.append(intent("sell", at=AT + timedelta(minutes=1)))
    engine.ingest(quote(AT + timedelta(seconds=61), bid=101, ask=101.02))
    assert engine.realized == pytest.approx(9.6)
    assert engine.cash == pytest.approx(25009.6)
    assert engine.total_fees == pytest.approx(0.2)
    assert not engine.positions


def test_expired_orders_do_not_fill_and_missing_marks_are_null() -> None:
    engine = PaperEngine(config(), params())
    engine.pending.append(intent())
    engine.ingest(quote(AT + timedelta(seconds=6)))
    assert not engine.fills and not engine.pending
    engine.positions["MSFT"] = Position("MSFT", 10, 1, 1000, AT)
    assert engine.report()["final_mark"]["net_pnl"] is None
    assert engine.report()["max_drawdown_dollars"] is None


def test_buy_cannot_spend_unfilled_sale_proceeds() -> None:
    engine = PaperEngine(config(), params())
    engine.cash = 5000
    engine.positions["MSFT"] = Position("MSFT", 10, 1, 1000, AT - timedelta(minutes=1))
    engine.pending = [intent("sell", "MSFT"), intent()]
    engine.ingest(quote(AT + timedelta(seconds=1)))
    assert not engine.fills
    engine.ingest(quote(AT + timedelta(seconds=2), symbol="MSFT", bid=101, ask=101.02))
    engine.ingest(quote(AT + timedelta(seconds=3)))
    assert [f["side"] for f in engine.fills] == ["sell", "buy"]
    assert engine.cash >= 5000


def test_chronology_duplicates_source_separation_and_quote_regression() -> None:
    engine = PaperEngine(config(), params())
    q = quote()
    engine.ingest(q)
    engine.ingest(q)
    assert len(engine.input_hashes) == 1
    with pytest.raises(ValueError, match="conflicting duplicate"):
        engine.ingest(q.model_copy(update={"bid": 99}))
    with pytest.raises(ValueError, match="received_at order"):
        engine.ingest(quote(AT - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="synthetic and real"):
        engine.ingest(q.model_copy(update={"source": "xnas_itch"}))
    engine.ingest(quote(AT + timedelta(seconds=1), event_at=AT - timedelta(seconds=1), bid=99))
    assert engine.quotes["AAPL"].bid == q.bid


def test_option_flow_sign_and_revision_is_forward_only() -> None:
    flow = signed_option_flow(
        trade_id="first",
        symbol="AAPL",
        executed_at=AT,
        received_at=AT,
        side="buy",
        size=10,
        delta=-0.5,
    )
    assert flow is not None and flow.signed_delta_shares == -500
    assert (
        signed_option_flow(
            trade_id="unknown",
            symbol="AAPL",
            executed_at=AT,
            received_at=AT,
            side="unknown",
            size=10,
            delta=0.5,
        )
        is None
    )
    engine = PaperEngine(config(), params(source="xnas_itch"))
    engine.ingest(flow)
    revision = flow.model_copy(
        update={
            "event_id": "rev",
            "revision_of": "first",
            "signed_delta_shares": 0,
            "received_at": AT + timedelta(seconds=1),
        }
    )
    engine.ingest(revision)
    assert "first" not in engine.flows and len(engine.input_hashes) == 2


def mbo(
    action: str,
    oid: int,
    side: str = "A",
    price: float = 100.01,
    size: int = 10,
    sequence: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "action": action,
        "order_id": oid,
        "side": side,
        "price": price,
        "size": size,
        "sequence": sequence,
        "publisher_id": 2,
        "event_at": AT.isoformat(),
        **extra,
    }


def test_mbo_snapshot_and_fill_cancel_not_double_counted() -> None:
    book = MBOBook("AAPL")
    with pytest.raises(ValueError, match="missing initial"):
        book.apply([mbo("A", 1)], AT)
    book.apply(
        [
            mbo("R", 0),
            mbo("A", 1, "B", 99.99, 100),
            mbo("A", 2, "B", 99.98, 100),
            mbo("A", 3, "A", 100.01, 100),
            mbo("A", 4, "A", 100.02, 100),
        ],
        AT,
    )
    events = book.apply(
        [mbo("F", 3, size=30, sequence=2), mbo("C", 3, size=30, sequence=2)],
        AT + timedelta(seconds=1),
    )
    assert book.orders[3][2] == 70
    assert isinstance(events[0], BookFrame)
    assert events[0].flows.buy == 30 and events[0].flows.ask_cancel == 0
    events = book.apply([mbo("C", 3, size=10, sequence=3)], AT + timedelta(seconds=2))
    assert isinstance(events[0], BookFrame) and events[0].flows.ask_cancel == 10
    assert book.orders[3][2] == 60
    with pytest.raises(ValueError, match="unknown order"):
        book.apply([mbo("C", 999, sequence=4)], AT + timedelta(seconds=3))


def test_snapshot_placements_are_excluded_from_flow() -> None:
    book = MBOBook("AAPL")
    rows = [
        mbo("R", 0),
        mbo("A", 1, "B", 99.99, 100),
        mbo("A", 2, "B", 99.98, 100),
        mbo("A", 3, "A", 100.01, 100),
        mbo("A", 4, "A", 100.02, 100),
    ]
    book.apply([{**r, "snapshot": True} for r in rows], AT)
    assert not book.apply([mbo("N", 0, sequence=2)], AT + timedelta(seconds=1))
    events = book.apply([mbo("N", 0, sequence=3)], AT + timedelta(seconds=2))
    assert isinstance(events[0], BookFrame) and events[0].flows == Flows()


def test_tuning_rejects_training_overlap_before_running() -> None:
    with pytest.raises(ValueError, match="precede validation"):
        tune([quote()], config(), params(trained_through=AT))


def test_replay_prefix_invariance_and_minute_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    def controlled(
        h: list[BookFrame], at: datetime, c: Config, p: Parameters, options_flow: float = 0
    ) -> Forecast:
        return prediction(at=at, change=0.5 if at.minute % 2 else -0.5)

    monkeypatch.setattr("groktrading.research.fluid60.engine.forecast", controlled)
    events = list(synthetic_events(AT - timedelta(seconds=2), 185))
    prefix = replay(events[:480], config(), params())
    full = replay(events, config(), params())
    assert prefix["fills"] == full["fills"][: len(prefix["fills"])]
    assert prefix["decisions"] == full["decisions"][: len(prefix["decisions"])]
    assert full["fills"]
    budget = Counter((f["decided_at"], f["side"]) for f in full["fills"])
    assert max(budget.values()) == 1
    selected = replay(events, config(selected_through=events[-1].received_at), params())
    assert not selected["fills"]


def test_calibration_cutoff_and_source_provenance() -> None:
    fitted = calibrate(history())
    assert fitted.trained_through == history()[-1].received_at
    assert fitted.source == "synthetic" and fitted.observations == 59
    assert fitted.options_beta == 0  # No invented options-flow calibration.


def test_tradier_uses_older_side_time_and_explicit_units() -> None:
    terms = QuoteTerms(
        underlying="AAPL",
        asset="put",
        size_multiplier=1,
        theta_per_day_scale=1,
        vega_per_vol_point_scale=0.01,
        expires_at=AT + timedelta(days=3),
    )
    row = {
        "symbol": "PUT",
        "bid": 2,
        "ask": 2.02,
        "bidsize": 10,
        "asksize": 11,
        "bid_date": (AT - timedelta(seconds=2)).timestamp() * 1000,
        "ask_date": AT.timestamp() * 1000,
        "greeks": {
            "delta": -0.5,
            "gamma": 0.01,
            "theta": -0.03,
            "vega": 10,
            "updated_at": AT.isoformat(),
        },
    }
    q = tradier_quote(row, terms, AT)
    assert q.event_at == AT - timedelta(seconds=2)
    assert q.vega_per_vol_point == 0.1 and q.bid_size == 10
    row["greeks"].pop("updated_at")
    q = tradier_quote(row, terms, AT)
    with pytest.raises(ValueError, match="missing_option_terms"):
        terminal_bids(q, prediction(), AT, config())


def test_drawdown_includes_costs_at_fill_time() -> None:
    engine = PaperEngine(config(), params())
    engine.pending.append(intent())
    engine.ingest(quote(AT + timedelta(seconds=1)))
    assert engine.report()["max_drawdown_dollars"] == pytest.approx(0.30)


def test_invalid_depth_does_not_reenter_until_complete() -> None:
    h = history()
    with pytest.raises(ValueError, match="mixed book identity"):
        forecast([h[0].model_copy(update={"symbol": "MSFT"}), *h[1:]], AT, config(), params())
    h[-1] = h[-1].model_copy(update={"event_at": AT - timedelta(seconds=30)})
    with pytest.raises(ValueError, match="stale_book"):
        forecast(h, AT, config(), params())


def test_validation_selection_freezes_cutoff_and_writes_six_scores() -> None:
    events = list(synthetic_events(AT - timedelta(seconds=120), 245))
    chosen, audit = tune(events, config(), params())
    assert chosen.selected_through == events[-1].received_at
    assert len(audit["candidates"]) == 6
    assert chosen.minimum_improvement in (0.25, 1, 2)
    assert chosen.downside_weight in (0, 0.5)
