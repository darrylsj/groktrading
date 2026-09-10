"""Strict, availability-timestamped research contracts. Prices are USD per share."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Level(Strict):
    price: float = Field(gt=0)
    size: float = Field(gt=0)


class Flows(Strict):
    bid_add: float = Field(default=0, ge=0)
    ask_add: float = Field(default=0, ge=0)
    bid_cancel: float = Field(default=0, ge=0)
    ask_cancel: float = Field(default=0, ge=0)
    buy: float = Field(default=0, ge=0)
    sell: float = Field(default=0, ge=0)


class BookFrame(Strict):
    kind: Literal["book"] = "book"
    event_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z][A-Z.]{0,9}$")
    source: Literal["synthetic", "xnas_itch"]
    scope: Literal["XNAS"] = "XNAS"
    interval_start: AwareDatetime
    event_at: AwareDatetime
    received_at: AwareDatetime
    complete: bool = True
    trading: bool = True
    tick: float = Field(default=0.01, gt=0)
    bids: tuple[Level, ...] = Field(min_length=2)
    asks: tuple[Level, ...] = Field(min_length=2)
    flows: Flows = Field(default_factory=Flows)

    @model_validator(mode="after")
    def valid(self) -> BookFrame:
        if self.interval_start >= self.received_at or self.event_at > self.received_at:
            raise ValueError("invalid availability interval")
        for side, reverse in ((self.bids, True), (self.asks, False)):
            prices = [x.price for x in side]
            if prices != sorted(set(prices), reverse=reverse):
                raise ValueError("book levels must be ordered and unique")
            if any(abs(p / self.tick - round(p / self.tick)) > 1e-5 for p in prices):
                raise ValueError("price not on instrument tick grid")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("locked or crossed book")
        return self

    @property
    def mid(self) -> float:
        return (self.bids[0].price + self.asks[0].price) / 2


class Quote(Strict):
    kind: Literal["quote"] = "quote"
    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    underlying: str = Field(pattern=r"^[A-Z][A-Z.]{0,9}$")
    asset: Literal["stock", "call", "put"]
    source: Literal["synthetic", "tradier_production", "xnas_itch"]
    event_at: AwareDatetime
    received_at: AwareDatetime
    bid: float = Field(ge=0)
    ask: float = Field(gt=0)
    bid_size: int = Field(ge=0)
    ask_size: int = Field(ge=0)
    delayed: bool = False
    trading: bool = True
    multiplier: int = Field(default=1, ge=1, le=100)
    delta: float | None = Field(default=None, ge=-1, le=1)
    gamma: float | None = Field(default=None, ge=0)
    theta_per_day: float | None = None
    vega_per_vol_point: float | None = Field(default=None, ge=0)
    greeks_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    iv: float | None = Field(default=None, gt=0, le=10)

    @model_validator(mode="after")
    def valid(self) -> Quote:
        if self.bid > self.ask or self.event_at > self.received_at:
            raise ValueError("crossed/future quote")
        if self.asset == "stock":
            if self.multiplier != 1 or self.symbol != self.underlying:
                raise ValueError("stock identity/multiplier mismatch")
        elif self.multiplier != 100:
            raise ValueError("only standard equity options supported")
        if self.asset == "call" and self.delta is not None and self.delta < 0:
            raise ValueError("call delta sign")
        if self.asset == "put" and self.delta is not None and self.delta > 0:
            raise ValueError("put delta sign")
        if self.greeks_at is not None and self.greeks_at > self.received_at:
            raise ValueError("future Greeks")
        return self


class OptionFlow(Strict):
    kind: Literal["option_flow"] = "option_flow"
    event_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z][A-Z.]{0,9}$")
    event_at: AwareDatetime
    received_at: AwareDatetime
    source: Literal["synthetic", "uw"]
    signed_delta_shares: float
    revision_of: str | None = None

    @model_validator(mode="after")
    def valid(self) -> OptionFlow:
        if self.event_at > self.received_at:
            raise ValueError("future flow")
        return self


Event = BookFrame | Quote | OptionFlow


def parse_event(raw: dict[str, Any]) -> Event:
    models: dict[str, type[BookFrame] | type[Quote] | type[OptionFlow]] = {
        "book": BookFrame,
        "quote": Quote,
        "option_flow": OptionFlow,
    }
    return models[raw["kind"]].model_validate(raw)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Config(Strict):
    selected_through: AwareDatetime | None = None
    symbols: tuple[str, ...] = (
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "TSLA",
        "AMD",
        "AVGO",
        "PLTR",
    )
    capital: float = Field(default=25000, gt=0)
    reserve_fraction: float = Field(default=0.20, ge=0, lt=1)
    stock_lot: int = Field(default=10, ge=1, le=10000)
    paths: int = Field(default=128, ge=16, le=4096)
    horizon_seconds: Literal[60] = 60
    lookback_seconds: int = Field(default=120, ge=10, le=3600)
    min_history_seconds: int = Field(default=60, ge=5)
    max_age_seconds: float = Field(default=3, gt=0, le=30)
    max_greeks_age_seconds: float = Field(default=60, gt=0, le=600)
    max_gap_seconds: float = Field(default=5, gt=0)
    latency_seconds: float = Field(default=1, ge=0, lt=60)
    fill_window_seconds: float = Field(default=5, gt=0, lt=60)
    stock_slippage: float = Field(default=0.005, ge=0)
    option_slippage: float = Field(default=0.01, ge=0)
    stock_fee_per_share: float = Field(default=0, ge=0)
    option_fee_per_contract: float = Field(default=0.65, ge=0)
    minimum_improvement: float = Field(default=0.25, ge=0)
    downside_weight: float = Field(default=0.25, ge=0)
    max_spread_fraction: float = Field(default=0.05, gt=0, le=1)
    max_position_fraction: float = Field(default=0.10, gt=0, le=0.80)
    max_hold_minutes: int = Field(default=5, ge=1, le=390)
    grid_cells: int = Field(default=64, ge=4, le=512)
    seed: int = Field(default=20260910, ge=0)
    option_iv_shock_points: float = Field(default=0.5, ge=0, le=20)
    option_max_spot_move_fraction: float = Field(default=0.02, gt=0, le=0.10)
    min_option_seconds_to_expiry: int = Field(default=3600, ge=60)

    @model_validator(mode="after")
    def valid(self) -> Config:
        if len(set(self.symbols)) != len(self.symbols) or not self.symbols:
            raise ValueError("unique nonempty universe required")
        if self.min_history_seconds > self.lookback_seconds:
            raise ValueError("warmup exceeds lookback")
        if self.latency_seconds + self.fill_window_seconds >= 60:
            raise ValueError("fill window reaches forecast expiry")
        return self


class Parameters(Strict):
    version: Literal["fluid60-v1"] = "fluid60-v1"
    trained_through: AwareDatetime
    source: Literal["synthetic", "xnas_itch"]
    diffusion_ticks2_per_second: float = Field(default=0.02, ge=0, le=0.20)
    drift_ticks_per_second: float = Field(default=0, ge=-0.10, le=0.10)
    options_beta: float = Field(default=0, ge=-1, le=1)
    inside_spread_fraction: float = Field(default=0.25, ge=0, le=1)
    training_hash: str
    observations: int = Field(ge=1)


class Forecast(Strict):
    symbol: str
    at: AwareDatetime
    expires_at: AwareDatetime
    mid: float
    future_mids: tuple[float, ...]
    future_spreads: tuple[float, ...]
    domain_failure_fraction: float
    model_hash: str
    data_hash: str
    status: Literal["valid", "out_of_domain"]


def minute_floor(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(second=0, microsecond=0)
