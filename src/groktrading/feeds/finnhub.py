"""Finnhub stock trades WebSocket and REST status probe.

Official WS: wss://ws.finnhub.io (token query param; never log the URL unredacted).
REST quote/news/earnings/fundamentals/sentiment are plan-entitled. Finnhub does
not provide option NBBO. See docs/API_MATRIX.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from groktrading.errors import TimeoutFailClosedError, WatchlistBoundError
from groktrading.models import FinnhubTrade, HealthSnapshot
from groktrading.redaction import redact_string
from groktrading.timeutil import UTC, as_utc, is_stale

FINNHUB_WS_URL = "wss://ws.finnhub.io"
FINNHUB_REST_BASE = "https://finnhub.io/api/v1"
DEFAULT_WATCHLIST_BOUND = 16
WATCH_WIDEN_CAP_LO = 16
WATCH_WIDEN_CAP_HI = 40
DEFAULT_WATCH_WIDEN_CAP = 32
DEFAULT_NEWS_PER_SYMBOL = 5
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_BACKOFF_MAX = 60.0
FINNHUB_NOT_NBBO_NOTE = (
    "Finnhub is stock last prints / company news only. Not option NBBO. "
    "Never gate option limits on Finnhub ticks. Never places orders."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class HttpProbe(Protocol):
    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        ...


@dataclass
class FinnhubWatchlist:
    bound: int = DEFAULT_WATCHLIST_BOUND
    symbols: list[str] = field(default_factory=list)

    def add(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        if symbol in self.symbols:
            return
        if len(self.symbols) >= self.bound:
            raise WatchlistBoundError(f"watchlist bound {self.bound} exceeded")
        self.symbols.append(symbol)

    def subscribe_messages(self) -> list[str]:
        return [json.dumps({"type": "subscribe", "symbol": symbol}) for symbol in self.symbols]


def clamp_watch_widen_cap(cap: int) -> int:
    if cap < WATCH_WIDEN_CAP_LO:
        return WATCH_WIDEN_CAP_LO
    if cap > WATCH_WIDEN_CAP_HI:
        return WATCH_WIDEN_CAP_HI
    return cap


def widen_watchlist(
    watch: FinnhubWatchlist,
    extras: Iterable[str],
    *,
    cap: int = DEFAULT_WATCH_WIDEN_CAP,
) -> list[str]:
    """Bounded expand for open-risk / fresh-flow names. Cap 16–40.

    Raises the watch bound up to ``cap`` (clamped). Existing names stay.
    Extra symbols that do not fit are skipped (not an error).
    """
    limit = clamp_watch_widen_cap(cap)
    if watch.bound < limit:
        watch.bound = limit
    added: list[str] = []
    for raw in extras:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in watch.symbols:
            continue
        if len(watch.symbols) >= watch.bound:
            break
        watch.symbols.append(symbol)
        added.append(symbol)
    return added


def widen_for_risk_and_flow(
    watch: FinnhubWatchlist,
    *,
    open_risk: Iterable[str] = (),
    fresh_flow: Iterable[str] = (),
    cap: int = DEFAULT_WATCH_WIDEN_CAP,
) -> list[str]:
    """Open-risk names first, then fresh-flow underlyings. Same 16–40 cap."""
    extras: list[str] = []
    seen: set[str] = {s.upper() for s in watch.symbols}
    for raw in list(open_risk) + list(fresh_flow):
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        extras.append(symbol)
    return widen_watchlist(watch, extras, cap=cap)


def backoff_seconds(
    attempt: int,
    *,
    base: float = DEFAULT_BACKOFF_BASE,
    factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay: float = DEFAULT_BACKOFF_MAX,
) -> float:
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    delay = base * (factor**attempt)
    return min(max_delay, delay)


def parse_finnhub_message(raw: str | bytes) -> list[FinnhubTrade]:
    """Parse a Finnhub WS frame. Unknown types yield an empty list (not an error)."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return []
    if payload.get("type") != "trade":
        return []
    rows = payload.get("data") or []
    trades: list[FinnhubTrade] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("s")
        price = row.get("p")
        ts = row.get("t")
        volume = row.get("v", 0)
        if symbol is None or price is None or ts is None:
            continue
        conditions = row.get("c") or []
        if not isinstance(conditions, list):
            conditions = []
        trades.append(
            FinnhubTrade(
                symbol=str(symbol).upper(),
                price=float(price),
                volume=float(volume),
                trade_ts_ms=int(ts),
                conditions=[str(c) for c in conditions],
            )
        )
    return trades


def public_ws_url(token_present: bool) -> str:
    """Return a redacted description of the WS URL. Never embed a token."""
    if token_present:
        return redact_string(f"{FINNHUB_WS_URL}?token=placeholder")
    return FINNHUB_WS_URL


@dataclass
class FinnhubStreamState:
    watchlist: FinnhubWatchlist
    clock: Clock = field(default_factory=UtcClock)
    last_event_ts: datetime | None = None
    connected: bool = False
    reconnect_attempt: int = 0
    freshness_ttl_seconds: float = 30.0

    def mark_connected(self) -> None:
        self.connected = True
        self.reconnect_attempt = 0
        self.last_event_ts = self.clock.now()

    def mark_disconnected(self) -> None:
        self.connected = False
        self.reconnect_attempt += 1

    def on_trades(self, trades: Iterable[FinnhubTrade]) -> list[FinnhubTrade]:
        accepted = [t for t in trades if t.symbol in self.watchlist.symbols]
        if accepted:
            self.last_event_ts = self.clock.now()
        return accepted

    def next_backoff(self) -> float:
        return backoff_seconds(max(0, self.reconnect_attempt - 1))

    def health(self) -> HealthSnapshot:
        now = self.clock.now()
        stale = True
        if self.last_event_ts is not None:
            stale = is_stale(self.last_event_ts, now, self.freshness_ttl_seconds)
        return HealthSnapshot(
            connected=self.connected,
            last_event_ts=self.last_event_ts,
            watchlist=list(self.watchlist.symbols),
            stale=stale or not self.connected,
            detail="ok" if self.connected and not stale else "stale_or_disconnected",
        )

    def tape_document(self, trades: list[FinnhubTrade]) -> dict[str, Any]:
        now = as_utc(self.clock.now())
        return {
            "source": "finnhub_ws_trades",
            "note": "Stock last prints only. Not option NBBO. Never triggers live orders.",
            "as_of": now.isoformat(),
            "watchlist": list(self.watchlist.symbols),
            "connected": self.connected,
            "trades": [t.model_dump() for t in trades],
        }


def probe_quote(
    http: HttpProbe,
    symbol: str,
    *,
    token: str,
    timeout_note: str = "timeout",
) -> tuple[int, dict[str, Any]]:
    """REST quote probe. Caller supplies token from env; never persist it."""
    url = f"{FINNHUB_REST_BASE}/quote?symbol={symbol}"
    try:
        status, body = http.get_json(url, headers={"X-Finnhub-Token": token})
    except TimeoutError as exc:
        raise TimeoutFailClosedError(timeout_note) from exc
    return status, body


def probe_company_news(
    http: HttpProbe,
    symbol: str,
    *,
    token: str,
    from_date: str,
    to_date: str,
    timeout_note: str = "timeout",
) -> tuple[int, list[dict[str, Any]]]:
    """Documented ``GET /company-news``. Not option NBBO. Token not persisted."""
    url = (
        f"{FINNHUB_REST_BASE}/company-news?symbol={symbol}"
        f"&from={from_date}&to={to_date}"
    )
    try:
        status, body = http.get_json(url, headers={"X-Finnhub-Token": token})
    except TimeoutError as exc:
        raise TimeoutFailClosedError(timeout_note) from exc
    rows: list[dict[str, Any]] = []
    if isinstance(body, list):
        rows = [row for row in body if isinstance(row, dict)]
    elif isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            rows = [row for row in data if isinstance(row, dict)]
    return status, rows


def overnight_news_batch(
    http: HttpProbe,
    symbols: Iterable[str],
    *,
    token: str,
    from_date: str,
    to_date: str,
    cap: int = DEFAULT_WATCH_WIDEN_CAP,
    per_symbol: int = DEFAULT_NEWS_PER_SYMBOL,
) -> dict[str, Any]:
    """Company-news REST for the widened watch only. No 10k spray.

    Finnhub ≠ option NBBO. Timeouts fail closed for that symbol (skip).
    """
    limit = clamp_watch_widen_cap(cap)
    names: list[str] = []
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in names:
            continue
        names.append(symbol)
        if len(names) >= limit:
            break
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for symbol in names:
        try:
            status, rows = probe_company_news(
                http, symbol, token=token, from_date=from_date, to_date=to_date
            )
        except TimeoutFailClosedError as exc:
            errors[symbol] = str(exc)
            continue
        if status >= 400:
            errors[symbol] = f"finnhub_news_http_{status}"
            continue
        slim: list[dict[str, Any]] = []
        for row in rows[:per_symbol]:
            item: dict[str, Any] = {}
            for key in ("datetime", "headline", "source", "id"):
                if row.get(key) not in (None, ""):
                    item[key] = row[key]
            if item:
                slim.append(item)
        by_symbol[symbol] = slim
    return {
        "source": "finnhub_company_news",
        "note": FINNHUB_NOT_NBBO_NOTE,
        "from": from_date,
        "to": to_date,
        "symbols": names,
        "news": by_symbol,
        "errors": errors,
        "places_orders": False,
        "option_nbbo": False,
    }


class ReconnectingFinnhubClient:
    """Reconnect loop with backoff. Transport is injected for tests.

    WebSocket ticks update tape/health only. They must never call a broker.
    """

    def __init__(
        self,
        state: FinnhubStreamState,
        recv: Callable[[], str],
        on_trades: Callable[[list[FinnhubTrade]], None] | None = None,
    ) -> None:
        self.state = state
        self._recv = recv
        self._on_trades = on_trades

    def pump_once(self) -> list[FinnhubTrade]:
        raw = self._recv()
        trades = self.state.on_trades(parse_finnhub_message(raw))
        if self._on_trades is not None:
            self._on_trades(trades)
        return trades
