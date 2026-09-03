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
from groktrading.timeutil import is_stale

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
        bid = Decimal(str(row.get("bid", "0")))
        ask = Decimal(str(row.get("ask", "0")))
        now = self.clock.now()
        self.last_quote_ts = now
        return OptionQuote(
            option_symbol=option_symbol,
            bid=bid,
            ask=ask,
            quote_ts=now,
            source="tradier_production" if self.env == "production" else "tradier_sandbox",
            delayed=self.env == "sandbox",
        )

    def balances(self) -> AccountSnapshot:
        body = self._get(f"/accounts/{self.account_id}/balances")
        balances = (body or {}).get("balances") or {}
        cash = Decimal(str(balances.get("total_cash", balances.get("cash", "0"))))
        option_bp = balances.get("option_buying_power", balances.get("stock_buying_power", cash))
        bp = Decimal(str(option_bp))
        return AccountSnapshot(
            cash=cash,
            buying_power=bp,
            as_of=self.clock.now(),
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

    def require_fresh_quote(self) -> None:
        now = self.clock.now()
        if self.last_quote_ts is None or is_stale(
            self.last_quote_ts, now, self.freshness_ttl_seconds
        ):
            raise StaleDataError("tradier_quote_stale")
