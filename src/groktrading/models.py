"""Typed runtime models. JSON Schema counterparts live in /schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from groktrading.modes import OperatingMode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MarketState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    PRE = "pre"
    POST = "post"
    UNKNOWN = "unknown"


class GateReason(StrEnum):
    OK = "ok"
    STALE_QUOTE = "stale_quote"
    MATCHING_ASK_FAILED = "matching_ask_failed"
    SIT2_INCOMPLETE = "sit2_incomplete"
    ALREADY_RUN = "already_run"
    FIRST_RED = "first_red"
    QUANTITY_NOT_ONE = "quantity_not_one"
    DUPLICATE_OR_WORKING = "duplicate_or_working"
    INSUFFICIENT_CASH = "insufficient_cash"
    MARKET_CLOSED = "market_closed"
    PAST_CASH_UP = "past_cash_up"
    TTL_EXPIRED = "ttl_expired"
    WS_DIRECT_LIVE_FORBIDDEN = "ws_direct_live_forbidden"
    SIGNALS_ONLY = "signals_only"
    LIVE_NOT_ENABLED = "live_not_enabled"
    PREVIEW_REQUIRED = "preview_required"
    OVERNIGHT_FORBIDDEN = "overnight_forbidden"


class OptionQuote(StrictModel):
    """Tradier production NBBO is pricing truth. Sandbox quotes are delayed artifacts."""

    option_symbol: str
    bid: Decimal
    ask: Decimal
    quote_ts: datetime
    source: Literal["tradier_production", "tradier_sandbox", "synthetic"] = "tradier_production"
    delayed: bool = False

    @field_validator("ask", "bid")
    @classmethod
    def _non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("quote prices must be non-negative")
        return value


class Candidate(StrictModel):
    signal_id: str
    underlying: str
    option_symbol: str
    side: Literal["buy_to_open"] = "buy_to_open"
    quantity: int = 1
    proposed_limit: Decimal
    sit_confirmations: int = Field(ge=0)
    is_first_red: bool
    already_run: bool
    created_ts: datetime
    ttl_seconds: float = Field(gt=0, default=15.0)
    from_websocket: bool = False


class AccountSnapshot(StrictModel):
    cash: Decimal
    buying_power: Decimal
    working_option_symbols: list[str] = Field(default_factory=list)
    open_position_symbols: list[str] = Field(default_factory=list)
    as_of: datetime


class ClockSnapshot(StrictModel):
    state: MarketState
    as_of: datetime
    next_change: datetime | None = None


class GateContext(StrictModel):
    now: datetime
    quote: OptionQuote
    account: AccountSnapshot
    clock: ClockSnapshot
    mode: OperatingMode = OperatingMode.SIGNALS_ONLY
    live_explicitly_enabled: bool = False
    preview_ok: bool = False
    matching_ask_tolerance: Decimal = Decimal("0")
    max_quote_age_seconds: float = 5.0
    cash_up_enforced: bool = True


class GateResult(StrictModel):
    allowed: bool
    reasons: list[GateReason]
    signal_id: str
    mode: OperatingMode
    note: str = ""


class LLMDecision(StrictModel):
    """Thesis and approve/skip only. No broker fields."""

    action: Literal["approve", "skip"]
    thesis: str
    facts_digest: str
    model_label: str = "grok"


class AssembledFacts(StrictModel):
    """Facts assembled by Helsinki. The LLM may only consume this payload."""

    signal_id: str
    underlying: str
    option_symbol: str
    ask: Decimal
    bid: Decimal
    sit_confirmations: int
    flow_notes: list[str] = Field(default_factory=list)
    news_headlines: list[str] = Field(default_factory=list)
    as_of: datetime


class WebhookEnvelope(StrictModel):
    signal_id: str
    idempotency_key: str
    event_type: str
    body: dict[str, object]
    created_ts: datetime


class PaperFillArtifact(StrictModel):
    signal_id: str
    option_symbol: str
    sandbox_fill_price: Decimal | None
    production_nbbo_ask: Decimal
    production_nbbo_bid: Decimal
    previewed: bool
    recorded_ts: datetime
    terminal: bool = False
    notes: str = ""


class FinnhubTrade(StrictModel):
    symbol: str
    price: float
    volume: float
    trade_ts_ms: int
    conditions: list[str] = Field(default_factory=list)


class HealthSnapshot(StrictModel):
    connected: bool
    last_event_ts: datetime | None
    watchlist: list[str]
    stale: bool
    detail: str = ""
