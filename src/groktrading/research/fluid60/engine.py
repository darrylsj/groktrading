"""Causal event replay and forward paper engine; never a broker execution client."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np

from .policy import Intent, Position, choose, cost, fee, fresh, proceeds, slip
from .schema import (
    BookFrame,
    Config,
    Event,
    Forecast,
    OptionFlow,
    Parameters,
    Quote,
    digest,
    minute_floor,
)
from .simulator import forecast

NY = ZoneInfo("America/New_York")


class PaperEngine:
    """Feed events in received_at order, tick on wall-clock minute boundaries.

    At equal timestamps, the minute decision precedes that timestamp's events.
    Independent return paths use a separable risk penalty in the optimizer.
    """

    def __init__(
        self, config: Config, params: Parameters, model: Literal["fluid", "persistence"] = "fluid"
    ) -> None:
        self.config, self.params, self.model = config, params, model
        self.cash = config.capital
        self.positions: dict[str, Position] = {}
        self.quotes: dict[str, Quote] = {}
        self.books: dict[str, list[BookFrame]] = defaultdict(list)
        self.flows: dict[str, OptionFlow] = {}
        self.seen: dict[str, str] = {}
        self.last_received: datetime | None = None
        self.next_tick: datetime | None = None
        self.pending: list[Intent] = []
        self.forecasts: list[Forecast] = []
        self.outcomes: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []
        self.equity: list[dict[str, Any]] = []
        self.realized = 0.0
        self.total_fees = 0.0
        self.input_hashes: list[str] = []

    def ingest(self, event: Event) -> None:
        at = event.received_at
        if self.last_received is not None and at < self.last_received:
            raise ValueError("events must be in received_at order; never silently reorder")
        if (event.source == "synthetic") != (self.params.source == "synthetic"):
            raise ValueError("cannot mix synthetic and real data/model")
        fingerprint = digest(event.model_dump(mode="json"))
        key = f"{event.source}:{event.kind}:{event.event_id}"
        if key in self.seen:
            if self.seen[key] != fingerprint:
                raise ValueError("conflicting duplicate event; use explicit revision")
            return
        self.seen[key] = fingerprint
        self.input_hashes.append(fingerprint)
        if self.next_tick is None:
            self.next_tick = minute_floor(at) + timedelta(minutes=1)
        self.advance(at)
        self.last_received = at
        if isinstance(event, BookFrame):
            previous_book = self.books.get(event.symbol, [])
            if previous_book and event.event_at < previous_book[-1].event_at:
                raise ValueError("book event timestamp regressed; rebuild the input")
            self.books[event.symbol].append(event)
            cutoff = at - timedelta(seconds=self.config.lookback_seconds + 60)
            self.books[event.symbol] = [
                f for f in self.books[event.symbol] if f.received_at >= cutoff
            ]
        elif isinstance(event, OptionFlow):
            if event.revision_of is not None:
                self.flows.pop(event.revision_of, None)
            self.flows[event.event_id] = event
            self.flows = {
                k: v for k, v in self.flows.items() if (at - v.received_at).total_seconds() <= 120
            }
        else:
            previous = self.quotes.get(event.symbol)
            # A late old quote cannot supersede a newer market timestamp.
            if previous is None or event.event_at >= previous.event_at:
                if previous is not None and (event.asset, event.underlying, event.multiplier) != (
                    previous.asset,
                    previous.underlying,
                    previous.multiplier,
                ):
                    raise ValueError("instrument identity changed")
                self.quotes[event.symbol] = event
                self._execute(event)

    def advance(self, at: datetime) -> None:
        """Drive this from an external clock for streaming; events cannot precede it."""
        if self.last_received is not None and at < self.last_received:
            raise ValueError("clock moved backward")
        while self.next_tick is not None and self.next_tick <= at:
            self._tick(self.next_tick)
            self.next_tick += timedelta(minutes=1)
        self._expire(at)
        self.last_received = at

    def _expire(self, at: datetime) -> None:
        remaining = []
        for order in self.pending:
            if at >= order.expires_at:
                self.orders.append({**asdict(order), "status": "expired", "at": at})
            else:
                remaining.append(order)
        self.pending = remaining

    def _tick(self, at: datetime) -> None:
        self._expire(at)
        for f in self.forecasts:
            if f.expires_at != at or f.status != "valid":
                continue
            history = self.books.get(f.symbol, [])
            latest = history[-1] if history else None
            if (
                latest is not None
                and latest.complete
                and latest.trading
                and (0 <= (at - latest.event_at).total_seconds() <= self.config.max_age_seconds)
            ):
                self.outcomes.append(
                    {
                        "symbol": f.symbol,
                        "at": f.at,
                        "target_at": at,
                        "actual_mid": latest.mid,
                        "predicted_mid": float(np.mean(f.future_mids)),
                        "zero_return_mid": f.mid,
                    }
                )
        local = at.astimezone(NY)
        minute = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not 570 <= minute < 960:
            return
        forecasts: dict[str, Forecast] = {}
        unavailable: dict[str, str] = {}
        for symbol in self.config.symbols:
            try:
                flow = sum(
                    v.signed_delta_shares
                    for v in self.flows.values()
                    if v.symbol == symbol and 0 <= (at - v.event_at).total_seconds() < 60
                )
                f = forecast(self.books.get(symbol, []), at, self.config, self.params, flow)
                if self.model == "persistence":
                    h = self.books[symbol][-1]
                    f = f.model_copy(
                        update={
                            "future_mids": (h.mid,) * self.config.paths,
                            "future_spreads": (h.asks[0].price - h.bids[0].price,)
                            * self.config.paths,
                            "status": "valid",
                            "domain_failure_fraction": 0.0,
                            "model_hash": digest(["persistence", f.model_hash]),
                        }
                    )
                forecasts[symbol] = f
                self.forecasts.append(f)
                if f.status != "valid":
                    unavailable[symbol] = f.status
            except ValueError as exc:
                unavailable[symbol] = str(exc)
        # No new 60-second forecasts may open exposure into the regular close.
        eligible = forecasts if minute < 959 else {}
        if self.config.selected_through is not None and at <= self.config.selected_through:
            eligible = {}
        intents, details = choose(at, self.cash, self.positions, self.quotes, eligible, self.config)
        self.pending.extend(intents)
        self.orders.extend({**asdict(i), "status": "submitted_paper", "at": at} for i in intents)
        self.decisions.append(
            {
                "at": at,
                "orders": [asdict(i) for i in intents],
                "unavailable": unavailable,
                **details,
            }
        )
        self.equity.append(self.mark(at))

    def _execute(self, q: Quote) -> None:
        at = q.received_at
        remaining: list[Intent] = []
        for order in self.pending:
            if (
                order.symbol != q.symbol
                or at < order.eligible_at
                or q.event_at < order.eligible_at
                or not fresh(q, at, self.config)
            ):
                remaining.append(order)
                continue
            n = order.quantity
            if order.side == "buy":
                price = q.ask + slip(q, self.config)
                dollars = cost(q, n, self.config)
                if (
                    q.ask_size < n
                    or price > order.limit + 1e-9
                    or self.cash - dollars < self.config.capital * self.config.reserve_fraction
                    or q.symbol in self.positions
                    or dollars > self.config.capital * self.config.max_position_fraction
                ):
                    remaining.append(order)
                    continue
                self.cash -= dollars
                self.positions[q.symbol] = Position(q.symbol, n, q.multiplier, dollars, at)
                realized: float | None = None
            else:
                price = max(q.bid - slip(q, self.config), 0)
                if q.bid_size < n or price < order.limit - 1e-9 or q.symbol not in self.positions:
                    remaining.append(order)
                    continue
                p = self.positions.pop(q.symbol)
                dollars = proceeds(q, n, self.config)
                self.cash += dollars
                realized = dollars - p.entry_cost
                self.realized += realized
            paid_fee = fee(q, n, self.config)
            self.total_fees += paid_fee
            self.fills.append(
                {
                    **asdict(order),
                    "at": at,
                    "quote_event_id": q.event_id,
                    "quote_event_at": q.event_at,
                    "price": price,
                    "fee": paid_fee,
                    "cash_after": self.cash,
                    "realized_pnl": realized,
                }
            )
            self.orders.append({**asdict(order), "status": "filled_paper", "at": at})
            self.equity.append(self.mark(at))
        self.pending = remaining

    def mark(self, at: datetime) -> dict[str, Any]:
        value = self.cash
        missing = []
        for symbol, p in self.positions.items():
            q = self.quotes.get(symbol)
            if q is None or not fresh(q, at, self.config) or q.bid_size < p.quantity:
                missing.append(symbol)
            else:
                value += proceeds(q, p.quantity, self.config)
        return {
            "at": at,
            "liquidation_equity": None if missing else value,
            "net_pnl": None if missing else value - self.config.capital,
            "unmarked_positions": missing,
            "cash": self.cash,
        }

    def report(self) -> dict[str, Any]:
        if self.last_received is None:
            raise ValueError("empty replay")
        mark = self.mark(self.last_received)
        mse = (
            float(np.mean([(o["predicted_mid"] - o["actual_mid"]) ** 2 for o in self.outcomes]))
            if self.outcomes
            else None
        )
        null_mse = (
            float(np.mean([(o["zero_return_mid"] - o["actual_mid"]) ** 2 for o in self.outcomes]))
            if self.outcomes
            else None
        )
        marks = [e["liquidation_equity"] for e in [*self.equity, mark]]
        max_dd: float | None = None
        if all(v is not None for v in marks):
            curve = np.array([self.config.capital, *marks], dtype=float)
            max_dd = float(np.max(np.maximum.accumulate(curve) - curve))
        return {
            "mode": "synthetic_demo" if self.params.source == "synthetic" else "paper_replay",
            "model": self.model,
            "config": self.config.model_dump(mode="json"),
            "parameters": self.params.model_dump(mode="json"),
            "config_hash": digest(self.config.model_dump(mode="json")),
            "input_hash": digest(self.input_hashes),
            "final_mark": mark,
            "realized_pnl": self.realized,
            "unrealized_pnl": None if mark["net_pnl"] is None else mark["net_pnl"] - self.realized,
            "fees": self.total_fees,
            "max_drawdown_dollars": max_dd,
            "fill_count": len(self.fills),
            "open_positions": [asdict(p) for p in self.positions.values()],
            "pending_orders": [asdict(i) for i in self.pending],
            "forecast_mse": mse,
            "zero_return_mse": null_mse,
            "forecast_count": len(self.forecasts),
            "scored_forecast_count": len(self.outcomes),
            "unusable_forecast_count": sum(f.status != "valid" for f in self.forecasts),
            "forecast_outcomes": self.outcomes,
            "decisions": self.decisions,
            "orders": self.orders,
            "fills": self.fills,
            "equity": self.equity,
            "forecasts": [f.model_dump(mode="json") for f in self.forecasts],
        }
