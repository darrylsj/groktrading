"""Tradier account-events WebSocket helper — position truth only.

Hard rule: this feed **never places orders**. It records fills, cancels, and
other position-relevant order events so Helsinki ``in_position`` does not
stay stale after a flatten. Grok Bot remains the only place that decides
or submits.

Session: POST ``/v1/accounts/events/session``, then
``wss://ws.tradier.com/v1/accounts/events`` (sandbox: ``sandbox-ws``).
Subscribe: ``{"events":["order"],"sessionid":"…"}``. Heartbeats keep the
socket alive and are not material.

Reconnect/backoff matches the Finnhub helper (1s, ×2, cap 60s). Transport
is injected. Tests must never open a live Tradier socket.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.finnhub import backoff_seconds
from groktrading.feeds.tradier import TradierEnv, account_events_ws, rest_base
from groktrading.models import HealthSnapshot
from groktrading.redaction import REDACTED, redact_mapping
from groktrading.sit_match import parse_executed_at
from groktrading.timeutil import UTC, as_utc, is_stale

ACCOUNT_EVENTS_WS_PATH = "/v1/accounts/events"
NEVER_ORDERS_NOTE = (
    "Tradier account-events are position truth only. "
    "WebSocket never places orders. Grok Bot is the only submit path."
)

MATERIAL_STATUSES = frozenset(
    {
        "filled",
        "partially_filled",
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }
)
OPEN_STATUSES = frozenset({"open", "pending", "partially_filled", "pending_cancel", "held"})
CLOSING_SIDES = frozenset({"sell_to_close", "sell", "buy_to_close"})
OPENING_SIDES = frozenset({"buy_to_open", "buy", "sell_to_open"})

AccountEventKind = Literal[
    "heartbeat",
    "order",
    "error",
    "unknown",
]
MaterialKind = Literal[
    "fill",
    "partial_fill",
    "cancel",
    "reject",
    "expire",
    "refresh",
]


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class HttpJson(Protocol):
    def post_form(
        self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        ...


def public_account_events_ws(env: TradierEnv) -> str:
    """Documented WS URL. Never embed a session id or token."""
    return f"{account_events_ws(env)}{ACCOUNT_EVENTS_WS_PATH}"


def subscribe_payload(session_id_present: bool) -> dict[str, Any]:
    """Shape sent after connect. Session id is never returned to logs."""
    return {
        "events": ["order"],
        "sessionid": REDACTED if session_id_present else "",
        "excludeAccounts": [],
    }


def event_digest(payload: Mapping[str, Any]) -> str:
    body = json.dumps(
        redact_mapping(dict(payload)),
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _material_kind(status: str | None) -> MaterialKind | None:
    if status == "filled":
        return "fill"
    if status == "partially_filled":
        return "partial_fill"
    if status in {"canceled", "cancelled"}:
        return "cancel"
    if status == "rejected":
        return "reject"
    if status == "expired":
        return "expire"
    return None


@dataclass(frozen=True)
class AccountEvent:
    """Parsed account-stream frame. Account numbers are not stored."""

    kind: AccountEventKind
    status: str | None
    order_id: str | None
    symbol: str | None
    side: str | None
    tag: str | None
    exec_quantity: str | None
    remaining_quantity: str | None
    transaction_date: datetime | None
    material: bool
    material_kind: MaterialKind | None
    needs_rest_refresh: bool
    raw_digest: str
    detail: str


@dataclass
class PositionTruth:
    """Local symbol set used to keep ``in_position`` honest after flatten."""

    open_symbols: set[str] = field(default_factory=set)
    working_order_ids: set[str] = field(default_factory=set)
    last_material_kind: MaterialKind | None = None
    needs_rest_refresh: bool = False

    def apply(self, event: AccountEvent) -> bool:
        """Update local truth. Returns True when a webhook consumer should wake."""
        if not event.material:
            if event.kind == "order" and event.order_id and event.status in OPEN_STATUSES:
                self.working_order_ids.add(event.order_id)
            return False
        self.last_material_kind = event.material_kind
        if event.needs_rest_refresh:
            self.needs_rest_refresh = True
        if event.order_id and event.material_kind in {"cancel", "reject", "expire", "fill"}:
            self.working_order_ids.discard(event.order_id)
        symbol = event.symbol
        if symbol is None:
            self.needs_rest_refresh = True
            return True
        side = (event.side or "").lower()
        if event.material_kind == "fill":
            if side in CLOSING_SIDES:
                self.open_symbols.discard(symbol)
            elif side in OPENING_SIDES:
                self.open_symbols.add(symbol)
            else:
                self.needs_rest_refresh = True
            return True
        if event.material_kind == "partial_fill":
            if side in OPENING_SIDES:
                self.open_symbols.add(symbol)
            self.needs_rest_refresh = True
            return True
        if event.material_kind in {"cancel", "reject", "expire"}:
            return True
        return True


def parse_account_event(raw: str | bytes) -> AccountEvent | None:
    """Parse one WS frame. Junk / non-object JSON → None (fail closed, no invent)."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    event_name = str(payload.get("event") or "").lower()
    digest = event_digest(payload)
    if event_name == "heartbeat":
        return AccountEvent(
            kind="heartbeat",
            status=None,
            order_id=None,
            symbol=None,
            side=None,
            tag=None,
            exec_quantity=None,
            remaining_quantity=None,
            transaction_date=None,
            material=False,
            material_kind=None,
            needs_rest_refresh=False,
            raw_digest=digest,
            detail="heartbeat",
        )
    if payload.get("error") not in (None, ""):
        return AccountEvent(
            kind="error",
            status=None,
            order_id=None,
            symbol=None,
            side=None,
            tag=None,
            exec_quantity=None,
            remaining_quantity=None,
            transaction_date=None,
            material=False,
            material_kind=None,
            needs_rest_refresh=False,
            raw_digest=digest,
            detail="stream_error",
        )
    if event_name != "order":
        return AccountEvent(
            kind="unknown",
            status=None,
            order_id=None,
            symbol=None,
            side=None,
            tag=None,
            exec_quantity=None,
            remaining_quantity=None,
            transaction_date=None,
            material=False,
            material_kind=None,
            needs_rest_refresh=False,
            raw_digest=digest,
            detail="unknown_event",
        )
    status = _text(payload.get("status"))
    if status is not None:
        status = status.lower()
    order_id = _text(payload.get("id"))
    symbol = _text(payload.get("option_symbol") or payload.get("symbol"))
    if symbol is not None:
        symbol = symbol.upper()
    side = _text(payload.get("side") or payload.get("instruction"))
    if side is not None:
        side = side.lower()
    kind = _material_kind(status)
    material = kind is not None
    needs_refresh = material and symbol is None
    txn = parse_executed_at(payload.get("transaction_date") or payload.get("create_date"))
    return AccountEvent(
        kind="order",
        status=status,
        order_id=order_id,
        symbol=symbol,
        side=side,
        tag=_text(payload.get("tag")),
        exec_quantity=_text(
            payload.get("exec_quantity") or payload.get("executed_quantity")
        ),
        remaining_quantity=_text(payload.get("remaining_quantity")),
        transaction_date=txn,
        material=material,
        material_kind=kind,
        needs_rest_refresh=needs_refresh,
        raw_digest=digest,
        detail="order",
    )


def request_session_id(http: HttpJson, token: str, env: TradierEnv) -> str:
    """POST /accounts/events/session. Caller supplies token; never persist it."""
    url = f"{rest_base(env)}/accounts/events/session"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        status, body = http.post_form(url, {}, headers=headers)
    except TimeoutError as exc:
        raise TimeoutFailClosedError("tradier_account_events_session_timeout") from exc
    if status >= 400:
        raise TimeoutFailClosedError(f"tradier_account_events_session_http_{status}")
    stream = (body or {}).get("stream") if isinstance(body, dict) else None
    session = None
    if isinstance(stream, dict):
        session = stream.get("sessionid") or stream.get("session_id")
    if session in (None, "") and isinstance(body, dict):
        session = body.get("sessionid") or body.get("session_id")
    text = _text(session)
    if text is None:
        raise TimeoutFailClosedError("tradier_account_events_session_missing")
    return text


@dataclass
class AccountEventStreamState:
    clock: Clock = field(default_factory=UtcClock)
    positions: PositionTruth = field(default_factory=PositionTruth)
    last_event_ts: datetime | None = None
    last_material_ts: datetime | None = None
    connected: bool = False
    reconnect_attempt: int = 0
    freshness_ttl_seconds: float = 30.0
    last_event: AccountEvent | None = None

    def mark_connected(self) -> None:
        self.connected = True
        self.reconnect_attempt = 0
        self.last_event_ts = self.clock.now()

    def mark_disconnected(self) -> None:
        self.connected = False
        self.reconnect_attempt += 1

    def next_backoff(self) -> float:
        return backoff_seconds(max(0, self.reconnect_attempt - 1))

    def on_event(self, event: AccountEvent) -> bool:
        """Apply a parsed event. Returns True if material for webhook consumers."""
        self.last_event = event
        self.last_event_ts = self.clock.now()
        if event.kind == "heartbeat":
            return False
        material = self.positions.apply(event)
        if material:
            self.last_material_ts = self.last_event_ts
        return material

    def health(self) -> HealthSnapshot:
        now = self.clock.now()
        stale = True
        if self.last_event_ts is not None:
            stale = is_stale(self.last_event_ts, now, self.freshness_ttl_seconds)
        return HealthSnapshot(
            connected=self.connected,
            last_event_ts=self.last_event_ts,
            watchlist=[],
            stale=stale or not self.connected,
            detail="ok" if self.connected and not stale else "stale_or_disconnected",
        )

    def state_document(self) -> dict[str, Any]:
        now = as_utc(self.clock.now())
        event = self.last_event
        return {
            "source": "tradier_account_events",
            "note": NEVER_ORDERS_NOTE,
            "as_of": now.isoformat(),
            "connected": self.connected,
            "open_symbols": sorted(self.positions.open_symbols),
            "working_order_count": len(self.positions.working_order_ids),
            "needs_rest_refresh": self.positions.needs_rest_refresh,
            "last_material_kind": self.positions.last_material_kind,
            "last_event_kind": event.kind if event is not None else None,
            "last_event_material": event.material if event is not None else False,
            "places_orders": False,
        }


class ReconnectingAccountEventsClient:
    """Reconnect loop with backoff. Transport is injected. Never calls submit."""

    def __init__(
        self,
        state: AccountEventStreamState,
        recv: Callable[[], str],
        on_material: Callable[[AccountEvent], None] | None = None,
    ) -> None:
        self.state = state
        self._recv = recv
        self._on_material = on_material

    def pump_once(self) -> AccountEvent | None:
        raw = self._recv()
        event = parse_account_event(raw)
        if event is None:
            return None
        material = self.state.on_event(event)
        if material and self._on_material is not None:
            self._on_material(event)
        return event

    def listen_until(
        self,
        should_stop: Callable[[], bool],
        sleep: Callable[[float], None],
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        """Pump until ``should_stop``. Disconnects increment backoff; no orders."""
        while not should_stop():
            try:
                if not self.state.connected:
                    self.state.mark_connected()
                self.pump_once()
            except (TimeoutError, ConnectionError, OSError):
                self.state.mark_disconnected()
                if on_disconnect is not None:
                    on_disconnect()
                if should_stop():
                    return
                sleep(self.state.next_backoff())
