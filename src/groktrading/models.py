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


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


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
    MUST_TRADE_SMALL_EXCEPTION = "must_trade_small_exception"
    ASK_ABOVE_SMALL_BAND = "ask_above_small_band"
    ALREADY_RUN = "already_run"
    FIRST_RED = "first_red"
    QUANTITY_NOT_ONE = "quantity_not_one"
    DUPLICATE_OR_WORKING = "duplicate_or_working"
    INSUFFICIENT_CASH = "insufficient_cash"
    MARKET_CLOSED = "market_closed"
    PAST_CASH_UP = "past_cash_up"
    ENTRY_CUTOFF = "entry_cutoff"
    TTL_EXPIRED = "ttl_expired"
    WS_DIRECT_LIVE_FORBIDDEN = "ws_direct_live_forbidden"
    SIGNALS_ONLY = "signals_only"
    LIVE_NOT_ENABLED = "live_not_enabled"
    PREVIEW_REQUIRED = "preview_required"
    OVERNIGHT_FORBIDDEN = "overnight_forbidden"
    QUOTE_OCC_MISMATCH = "quote_occ_mismatch"
    QUOTE_DELAYED = "quote_delayed"
    QUOTE_SANDBOX = "quote_sandbox"
    QUOTE_SYNTHETIC = "quote_synthetic"
    QUOTE_ASK_NOT_POSITIVE = "quote_ask_not_positive"
    QUOTE_CROSSED = "quote_crossed"
    QUOTE_FUTURE_TS = "quote_future_ts"
    QUOTE_PROVIDER_STALE = "quote_provider_stale"
    QUOTE_MISSING_FIELDS = "quote_missing_fields"
    QUOTE_SPREAD = "quote_spread"
    NO_CHASE = "no_chase"
    CASH_RESERVE = "cash_reserve"
    IN_POSITION = "in_position"
    SESSION_FACTS_REQUIRED = "session_facts_required"
    MISSING_EXECUTED_AT = "missing_executed_at"
    UNPARSEABLE_EXECUTED_AT = "unparseable_executed_at"
    STALE_PRINT = "stale_print"


class OptionQuote(StrictModel):
    """Tradier production NBBO is pricing truth. Sandbox quotes are delayed artifacts."""

    option_symbol: str
    bid: Decimal
    ask: Decimal
    quote_ts: datetime
    source: Literal["tradier_production", "tradier_sandbox", "synthetic"] = "tradier_production"
    delayed: bool = False
    bid_date: datetime | None = None
    ask_date: datetime | None = None
    received_ts: datetime | None = None
    provider_symbol: str | None = None

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
    executed_at: datetime | None = None
    must_trade_small: bool = False
    committed_i2: bool = False


class AccountSnapshot(StrictModel):
    cash: Decimal
    buying_power: Decimal
    working_option_symbols: list[str] = Field(default_factory=list)
    open_position_symbols: list[str] = Field(default_factory=list)
    as_of: datetime
    equity: Decimal | None = None

    def equity_for_reserve(self) -> Decimal:
        """Equity used for the 20% cash floor. Missing equity falls back to cash."""
        return self.equity if self.equity is not None else self.cash


class ClockSnapshot(StrictModel):
    state: MarketState
    as_of: datetime
    next_change: datetime | None = None


class SessionFacts(StrictModel):
    """Durable session facts. Candidate booleans are not sufficient alone."""

    sit_confirmations: int = Field(ge=0, default=0)
    already_run_underlyings: list[str] = Field(default_factory=list)
    already_run_option_symbols: list[str] = Field(default_factory=list)
    first_red_option_symbols: list[str] = Field(default_factory=list)
    as_of: datetime | None = None


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
    cash_equity_floor: Decimal = Decimal("0.20")
    max_deploy_ratio: Decimal = Decimal("0.80")
    max_quote_spread: Decimal = Decimal("0.50")
    max_quote_spread_frac: Decimal = Decimal("0.25")
    session_facts: SessionFacts | None = None


class GateResult(StrictModel):
    allowed: bool
    reasons: list[GateReason]
    signal_id: str
    mode: OperatingMode
    note: str = ""


class LLMDecision(StrictModel):
    """Thesis and approve/skip only. Never sets OCC, qty, limit, account, or order action."""

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
    executed_at: datetime | None = None


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


class OrderState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    QUOTED = "quoted"
    PREVIEW = "preview"
    FINAL_GATE = "final_gate"
    SUBMIT = "submit"
    ACK = "ack"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"
    UNKNOWN_SUBMIT = "unknown_submit"
    FLAT_RECONCILED = "flat_reconciled"


class OrderPayload(FrozenModel):
    """Immutable broker payload. preview is the only submit-time flag."""

    signal_id: str
    option_symbol: str
    side: Literal["buy_to_open"] = "buy_to_open"
    quantity: int = 1
    limit_price: Decimal
    tag: str
    option_class: Literal["option"] = "option"
    order_type: Literal["limit"] = "limit"
    duration: Literal["day"] = "day"


class OrderTicket(StrictModel):
    ticket_id: str
    signal_id: str
    state: OrderState
    payload: OrderPayload
    payload_hash: str
    broker_order_id: str | None = None
    previewed: bool = False
    created_ts: datetime
    updated_ts: datetime
    note: str = ""
    gate_passed_ts: datetime | None = None
    gate_max_quote_age_seconds: float | None = None
