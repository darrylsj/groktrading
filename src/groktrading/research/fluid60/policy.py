"""One-minute inventory optimization. No broker imports or order submission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import product
from typing import Literal, cast

import numpy as np

from .schema import Config, Forecast, Quote
from .simulator import Array


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    multiplier: int
    entry_cost: float  # Total dollars, including entry fee.
    opened_at: datetime


@dataclass(frozen=True)
class Intent:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    multiplier: int
    limit: float  # USD per share; option contract multiplier applied separately.
    decided_at: datetime
    eligible_at: datetime
    expires_at: datetime
    reason: str


def fee(q: Quote, quantity: int, config: Config) -> float:
    return quantity * (
        config.stock_fee_per_share if q.asset == "stock" else config.option_fee_per_contract
    )


def slip(q: Quote, config: Config) -> float:
    return config.stock_slippage if q.asset == "stock" else config.option_slippage


def fresh(q: Quote, at: datetime, config: Config) -> bool:
    return (
        q.received_at <= at
        and 0 <= (at - q.event_at).total_seconds() <= config.max_age_seconds
        and q.trading
        and not q.delayed
        and q.bid > 0
        and (q.expires_at is None or q.expires_at > at)
    )


def proceeds(q: Quote, quantity: int, config: Config) -> float:
    return max(q.bid - slip(q, config), 0) * quantity * q.multiplier - fee(q, quantity, config)


def cost(q: Quote, quantity: int, config: Config) -> float:
    return (q.ask + slip(q, config)) * quantity * q.multiplier + fee(q, quantity, config)


def terminal_bids(q: Quote, f: Forecast, at: datetime, config: Config) -> Array:
    if f.status != "valid" or f.at != at or f.expires_at != at + timedelta(seconds=60):
        raise ValueError("unusable_forecast")
    if q.underlying != f.symbol or not fresh(q, at, config):
        raise ValueError("stale_or_mismatched_quote")
    mids = np.array(f.future_mids)
    if q.asset == "stock":
        # Model predicts price changes on XNAS; anchor to the execution quote.
        current_mid = (q.bid + q.ask) / 2
        return cast(
            Array,
            np.maximum(
                current_mid
                + mids
                - f.mid
                - np.maximum(np.array(f.future_spreads), q.ask - q.bid) / 2,
                0,
            ),
        )
    if (
        q.greeks_at is None
        or q.delta is None
        or q.gamma is None
        or q.theta_per_day is None
        or q.vega_per_vol_point is None
        or q.expires_at is None
    ):
        raise ValueError("missing_option_terms")
    if (at - q.greeks_at).total_seconds() > config.max_greeks_age_seconds:
        raise ValueError("stale_greeks")
    if (q.expires_at - at).total_seconds() < config.min_option_seconds_to_expiry:
        raise ValueError("near_expiry")
    ds = mids - f.mid
    if np.max(np.abs(ds)) / f.mid > config.option_max_spot_move_fraction:
        raise ValueError("option_local_approximation_out_of_range")
    change = q.delta * ds + 0.5 * q.gamma * ds**2 + q.theta_per_day * 60 / 86400
    # Equal-weight scenario stress, not a calibrated IV probability distribution.
    shocks = np.array([-1.0, 0.0, 1.0]) * config.option_iv_shock_points
    changes = change[:, None] + q.vega_per_vol_point * shocks[None, :]
    return np.maximum(q.bid + changes.ravel(), 0)


def utility(pnl: Array, config: Config) -> float:
    """Separable expected P&L minus expected loss; no invented cross-asset correlation."""
    return float(pnl.mean() - config.downside_weight * np.maximum(-pnl, 0).mean())


def choose(
    at: datetime,
    cash: float,
    positions: dict[str, Position],
    quotes: dict[str, Quote],
    forecasts: dict[str, Forecast],
    config: Config,
) -> tuple[list[Intent], dict[str, object]]:
    held: dict[str, float] = {}
    buy_scores: dict[str, float] = {}
    quantities: dict[str, int] = {}
    rejected: dict[str, str] = {}
    overdue: list[Position] = []
    sellable: list[str] = []
    for symbol, p in positions.items():
        q = quotes.get(symbol)
        if q is not None and fresh(q, at, config) and q.bid_size >= p.quantity:
            sellable.append(symbol)
        if (at - p.opened_at).total_seconds() >= config.max_hold_minutes * 60:
            overdue.append(p)
    for symbol, q in quotes.items():
        if q.underlying not in config.symbols:
            continue
        try:
            if q.underlying not in forecasts:
                raise ValueError("missing_forecast")
            future = terminal_bids(q, forecasts[q.underlying], at, config)
            n = (
                positions[symbol].quantity
                if symbol in positions
                else (config.stock_lot if q.asset == "stock" else 1)
            )
            terminal = np.maximum(future - slip(q, config), 0) * n * q.multiplier
            terminal -= fee(q, n, config)
            if symbol in positions:
                held[symbol] = utility(terminal - proceeds(q, n, config), config)
            elif (
                (q.ask - q.bid) / q.ask <= config.max_spread_fraction
                and q.ask_size >= n
                and cost(q, n, config) <= config.capital * config.max_position_fraction
            ):
                buy_scores[symbol] = utility(terminal - cost(q, n, config), config)
                quantities[symbol] = n
        except ValueError as exc:
            rejected[symbol] = str(exc)
    # Unknown held forecasts are exit candidates, as are maximum holding times.
    forced = sorted(
        {
            p.symbol: p for p in overdue + [p for s, p in positions.items() if s not in held]
        }.values(),
        key=lambda p: (p.opened_at, p.symbol),
    )
    for s in positions:
        held.setdefault(s, 0.0)
    baseline = sum(held.values())
    best = baseline
    selection: tuple[str | None, str | None] = (None, None)
    reason = "expected_pnl"
    if forced:
        # Do not accumulate new exposure while exit backlog exists.
        sale = next((p.symbol for p in forced if p.symbol in sellable), None)
        selection = (sale, None)
        best = baseline - held[sale] if sale is not None else baseline
        reason = "risk_exit"
    else:
        for sale, buy in product([None, *sorted(sellable)], [None, *sorted(buy_scores)]):
            funds = cash
            score = baseline
            if sale is not None:
                funds += proceeds(quotes[sale], positions[sale].quantity, config)
                score -= held[sale]
            if buy is not None:
                funds -= cost(quotes[buy], quantities[buy], config)
                score += buy_scores[buy]
                if funds < config.capital * config.reserve_fraction:
                    continue
            if score > best + 1e-10:
                best, selection = score, (sale, buy)
        if best - baseline < config.minimum_improvement:
            selection = (None, None)
            best = baseline
    intents: list[Intent] = []
    for side, chosen_symbol in zip(("sell", "buy"), selection, strict=True):
        if chosen_symbol is None:
            continue
        symbol = chosen_symbol
        q = quotes[symbol]
        n = positions[symbol].quantity if side == "sell" else quantities[symbol]
        intents.append(
            Intent(
                symbol=symbol,
                side="sell" if side == "sell" else "buy",
                quantity=n,
                multiplier=q.multiplier,
                limit=max(q.bid - slip(q, config), 0)
                if side == "sell"
                else q.ask + slip(q, config),
                decided_at=at,
                eligible_at=at + timedelta(seconds=config.latency_seconds),
                expires_at=at
                + timedelta(seconds=config.latency_seconds + config.fill_window_seconds),
                reason=reason,
            )
        )
    return intents, {
        "hold_score": baseline,
        "selected_score": best,
        "hold_values": held,
        "buy_values": buy_scores,
        "rejected": rejected,
        "reason": reason,
        "exit_backlog": [p.symbol for p in forced],
    }
