"""Generic Tradier client (production vs sandbox).

Official bases (docs.tradier.com/docs/endpoints):
  Production REST: https://api.tradier.com/v1/
  Sandbox REST:    https://sandbox.tradier.com/v1/
  Production stream: https://stream.tradier.com/v1/
  Account events WS: wss://ws.tradier.com (sandbox: wss://sandbox-ws.tradier.com)

Sandbox market data is delayed (~15 minutes), has no market-data stream,
no Greeks, no indices, and no tick timesales. Account-event streaming is
available in sandbox. Production NBBO is pricing truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from groktrading.errors import StaleDataError, TimeoutFailClosedError
from groktrading.models import AccountSnapshot, ClockSnapshot, MarketState, OptionQuote
from groktrading.timeutil import UTC, is_stale

TradierEnv = Literal["production", "sandbox"]

PRODUCTION_REST = "https://api.tradier.com/v1"
SANDBOX_REST = "https://sandbox.tradier.com/v1"
PRODUCTION_STREAM = "https://stream.tradier.com/v1"
PRODUCTION_ACCOUNT_WS = "wss://ws.tradier.com"
SANDBOX_ACCOUNT_WS = "wss://sandbox-ws.tradier.com"


class HttpJson(Protocol):
    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        ...

    def post_form(
        self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


def rest_base(env: TradierEnv) -> str:
    return PRODUCTION_REST if env == "production" else SANDBOX_REST


def account_events_ws(env: TradierEnv) -> str:
    return PRODUCTION_ACCOUNT_WS if env == "production" else SANDBOX_ACCOUNT_WS


def _parse_tradier_ts(value: Any) -> datetime | None:
    """Parse Tradier bid_date/ask_date (epoch seconds or milliseconds)."""
    if value in (None, "", 0, "0"):
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 1e10:
        raw = raw / 1000.0
    return datetime.fromtimestamp(raw, tz=UTC)


@dataclass
class TradierClient:
    """Injectable Tradier adapter. Timeouts and stale quotes fail closed."""

    http: HttpJson
    clock: Clock
    token: str
    account_id: str
    env: TradierEnv
    freshness_ttl_seconds: float = 5.0
    last_quote_ts: datetime | None = None

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> Any:
        url = f"{rest_base(self.env)}{path}"
        try:
            status, body = self.http.get_json(url, headers=self.headers())
        except TimeoutError as exc:
            raise TimeoutFailClosedError("tradier_timeout") from exc
        if status >= 400:
            raise TimeoutFailClosedError(f"tradier_http_{status}")
        return body

    def quote_option(self, option_symbol: str) -> OptionQuote:
        """GET /markets/quotes — official quotes path (see Tradier market-data docs)."""
        body = self._get(f"/markets/quotes?symbols={option_symbol}&greeks=false")
        quotes = ((body or {}).get("quotes") or {}).get("quote")
        if isinstance(quotes, list):
            row = quotes[0] if quotes else {}
        else:
            row = quotes or {}
        if not isinstance(row, dict):
            row = {}
        bid = Decimal(str(row.get("bid", "0")))
        ask = Decimal(str(row.get("ask", "0")))
        now = self.clock.now()
        bid_date = _parse_tradier_ts(row.get("bid_date") or row.get("biddate"))
        ask_date = _parse_tradier_ts(row.get("ask_date") or row.get("askdate"))
        provider_symbol = str(row.get("symbol") or option_symbol)
        delayed_raw = row.get("delayed")
        delayed = bool(delayed_raw) if delayed_raw is not None else self.env == "sandbox"
        provider_ts = ask_date or bid_date or now
        self.last_quote_ts = provider_ts
        return OptionQuote(
            option_symbol=option_symbol,
            bid=bid,
            ask=ask,
            quote_ts=provider_ts,
            source="tradier_production" if self.env == "production" else "tradier_sandbox",
            delayed=delayed,
            bid_date=bid_date,
            ask_date=ask_date,
            received_ts=now,
            provider_symbol=provider_symbol,
        )

    def balances(self) -> AccountSnapshot:
        body = self._get(f"/accounts/{self.account_id}/balances")
        balances = (body or {}).get("balances") or {}
        cash = Decimal(str(balances.get("total_cash", balances.get("cash", "0"))))
        option_bp = balances.get("option_buying_power", balances.get("stock_buying_power", cash))
        bp = Decimal(str(option_bp))
        equity_raw = balances.get("total_equity", balances.get("equity"))
        equity = Decimal(str(equity_raw)) if equity_raw is not None else None
        return AccountSnapshot(
            cash=cash,
            buying_power=bp,
            as_of=self.clock.now(),
            equity=equity,
        )

    def position_symbols(self) -> list[str]:
        """GET /accounts/{id}/positions — used by the broker-authoritative final gate."""
        body = self._get(f"/accounts/{self.account_id}/positions")
        rows = ((body or {}).get("positions") or {}).get("position") or []
        if isinstance(rows, dict):
            rows = [rows]
        symbols: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("option_symbol") or row.get("symbol") or "")
            if symbol:
                symbols.append(symbol)
        return symbols

    def working_option_symbols(self) -> list[str]:
        """GET /accounts/{id}/orders — working entry symbols for duplicate checks."""
        body = self._get(f"/accounts/{self.account_id}/orders")
        rows = ((body or {}).get("orders") or {}).get("order") or []
        if isinstance(rows, dict):
            rows = [rows]
        symbols: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "")).lower()
            if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
                continue
            symbol = str(row.get("option_symbol") or row.get("symbol") or "")
            if symbol:
                symbols.append(symbol)
        return symbols

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None:
        """Query existing orders by tag=signal_id. Never blind-retry a submit."""
        body = self._get(f"/accounts/{self.account_id}/orders")
        rows = ((body or {}).get("orders") or {}).get("order") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if isinstance(row, dict) and str(row.get("tag") or "") == tag:
                return row
        return None

    def snapshot_account(self) -> AccountSnapshot:
        """Fresh balances + positions + working orders for the final gate."""
        snap = self.balances()
        return snap.model_copy(
            update={
                "working_option_symbols": self.working_option_symbols(),
                "open_position_symbols": self.position_symbols(),
            }
        )

    def market_clock(self) -> ClockSnapshot:
        body = self._get("/markets/clock")
        clock = (body or {}).get("clock") or {}
        raw_state = str(clock.get("state", "unknown")).lower()
        try:
            state = MarketState(raw_state)
        except ValueError:
            state = MarketState.UNKNOWN
        return ClockSnapshot(state=state, as_of=self.clock.now())

    def preview_option_order(self, payload: dict[str, str]) -> Any:
        """POST /accounts/{id}/orders with preview=true (official preview mechanism)."""
        data = dict(payload)
        data["preview"] = "true"
        url = f"{rest_base(self.env)}/accounts/{self.account_id}/orders"
        try:
            status, body = self.http.post_form(url, data, headers=self.headers())
        except TimeoutError as exc:
            raise TimeoutFailClosedError("tradier_preview_timeout") from exc
        if status >= 400:
            raise TimeoutFailClosedError(f"tradier_preview_http_{status}")
        return body

    def submit_option_order(self, payload: dict[str, str]) -> Any:
        """POST /accounts/{id}/orders with preview=false. Caller must have passed the gate."""
        data = dict(payload)
        data["preview"] = "false"
        url = f"{rest_base(self.env)}/accounts/{self.account_id}/orders"
        try:
            status, body = self.http.post_form(url, data, headers=self.headers())
        except TimeoutError as exc:
            raise TimeoutFailClosedError("tradier_submit_timeout") from exc
        if status >= 400:
            raise TimeoutFailClosedError(f"tradier_submit_http_{status}")
        return body

    def require_fresh_quote(self) -> None:
        now = self.clock.now()
        if self.last_quote_ts is None or is_stale(
            self.last_quote_ts, now, self.freshness_ttl_seconds
        ):
            raise StaleDataError("tradier_quote_stale")
