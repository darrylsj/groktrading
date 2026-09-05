"""P0.3 preview → final-gate → submit state machine (stub-safe).

Durable lifecycle. Payload is immutable. Preview and submit use the same
payload; only the preview flag changes. Live credentials are not required.
An unknown submit is never blindly retried — query the broker by tag first.

Design references (not vendored): LEAN Tradier preview/submit, Nautilus
reconciliation. Lumibot (GPL) and Optopsy (AGPL) are not imported.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from groktrading.errors import LiveGatingError
from groktrading.gate import evaluate_gate
from groktrading.models import (
    Candidate,
    GateContext,
    GateResult,
    OrderPayload,
    OrderState,
    OrderTicket,
)
from groktrading.modes import OperatingMode
from groktrading.timeutil import UTC

ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.RECEIVED: frozenset({OrderState.VALIDATED, OrderState.REJECTED}),
    OrderState.VALIDATED: frozenset({OrderState.QUOTED, OrderState.REJECTED}),
    OrderState.QUOTED: frozenset({OrderState.PREVIEW, OrderState.REJECTED}),
    OrderState.PREVIEW: frozenset({OrderState.FINAL_GATE, OrderState.REJECTED}),
    OrderState.FINAL_GATE: frozenset({OrderState.SUBMIT, OrderState.REJECTED}),
    OrderState.SUBMIT: frozenset(
        {OrderState.ACK, OrderState.UNKNOWN_SUBMIT, OrderState.REJECTED}
    ),
    OrderState.ACK: frozenset(
        {
            OrderState.FILLED,
            OrderState.PARTIAL,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.PARTIAL: frozenset(
        {OrderState.FILLED, OrderState.CANCELED, OrderState.EXPIRED, OrderState.FLAT_RECONCILED}
    ),
    OrderState.FILLED: frozenset({OrderState.FLAT_RECONCILED}),
    OrderState.REJECTED: frozenset({OrderState.FLAT_RECONCILED}),
    OrderState.CANCELED: frozenset({OrderState.FLAT_RECONCILED}),
    OrderState.EXPIRED: frozenset({OrderState.FLAT_RECONCILED}),
    OrderState.UNKNOWN_SUBMIT: frozenset(
        {OrderState.ACK, OrderState.REJECTED, OrderState.FLAT_RECONCILED}
    ),
    OrderState.FLAT_RECONCILED: frozenset(),
}


def payload_hash(payload: OrderPayload) -> str:
    body = json.dumps(payload.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def payload_from_candidate(candidate: Candidate) -> OrderPayload:
    return OrderPayload(
        signal_id=candidate.signal_id,
        option_symbol=candidate.option_symbol,
        side=candidate.side,
        quantity=candidate.quantity,
        limit_price=candidate.proposed_limit,
        tag=candidate.signal_id,
    )


def tradier_form(payload: OrderPayload, *, preview: bool) -> dict[str, str]:
    """Exact form body. preview is the only allowed mutation at submit time."""
    return {
        "class": payload.option_class,
        "symbol": payload.option_symbol,
        "option_symbol": payload.option_symbol,
        "side": payload.side,
        "quantity": str(payload.quantity),
        "type": payload.order_type,
        "duration": payload.duration,
        "price": str(payload.limit_price),
        "tag": payload.tag,
        "preview": "true" if preview else "false",
    }


class OrderBroker(Protocol):
    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]: ...

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]: ...

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None: ...


class RecordingOrderBroker:
    """In-memory stub. No network. No credentials."""

    def __init__(self) -> None:
        self.previews: list[dict[str, str]] = []
        self.submits: list[dict[str, str]] = []
        self.known_by_tag: dict[str, dict[str, Any]] = {}
        self.submit_acks: bool = True
        self.next_broker_id: str = "brk-1"

    def preview_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        self.previews.append(payload)
        return {"status": "ok", "preview": True, "tag": payload.get("tag")}

    def submit_option_order(self, payload: dict[str, str]) -> dict[str, Any]:
        self.submits.append(payload)
        if not self.submit_acks:
            return {"status": "unknown"}
        row = {"id": self.next_broker_id, "tag": payload.get("tag"), "status": "ok"}
        tag = payload.get("tag")
        if tag:
            self.known_by_tag[tag] = row
        return row

    def find_order_by_tag(self, tag: str) -> dict[str, Any] | None:
        return self.known_by_tag.get(tag)


class OrderStore(Protocol):
    def put(self, ticket: OrderTicket) -> None: ...

    def get(self, ticket_id: str) -> OrderTicket | None: ...

    def get_by_signal(self, signal_id: str) -> OrderTicket | None: ...

    def get_by_hash(self, payload_hash_value: str) -> OrderTicket | None: ...


class MemoryOrderStore:
    def __init__(self) -> None:
        self.tickets: dict[str, OrderTicket] = {}

    def put(self, ticket: OrderTicket) -> None:
        self.tickets[ticket.ticket_id] = ticket

    def get(self, ticket_id: str) -> OrderTicket | None:
        return self.tickets.get(ticket_id)

    def get_by_signal(self, signal_id: str) -> OrderTicket | None:
        for ticket in self.tickets.values():
            if ticket.signal_id == signal_id:
                return ticket
        return None

    def get_by_hash(self, payload_hash_value: str) -> OrderTicket | None:
        for ticket in self.tickets.values():
            if ticket.payload_hash == payload_hash_value:
                return ticket
        return None


class SqliteOrderStore:
    """SQLite WAL ticket store. Path ':memory:' is supported for tests."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_tickets (
                ticket_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_ts TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def put(self, ticket: OrderTicket) -> None:
        body = ticket.model_dump_json()
        self._conn.execute(
            """
            INSERT INTO order_tickets (ticket_id, signal_id, payload_hash, body, updated_ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                signal_id=excluded.signal_id,
                payload_hash=excluded.payload_hash,
                body=excluded.body,
                updated_ts=excluded.updated_ts
            """,
            (
                ticket.ticket_id,
                ticket.signal_id,
                ticket.payload_hash,
                body,
                ticket.updated_ts.isoformat(),
            ),
        )
        self._conn.commit()

    def get(self, ticket_id: str) -> OrderTicket | None:
        row = self._conn.execute(
            "SELECT body FROM order_tickets WHERE ticket_id=?", (ticket_id,)
        ).fetchone()
        if row is None:
            return None
        return OrderTicket.model_validate_json(row[0])

    def get_by_signal(self, signal_id: str) -> OrderTicket | None:
        row = self._conn.execute(
            "SELECT body FROM order_tickets WHERE signal_id=? ORDER BY updated_ts DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderTicket.model_validate_json(row[0])

    def get_by_hash(self, payload_hash_value: str) -> OrderTicket | None:
        row = self._conn.execute(
            "SELECT body FROM order_tickets WHERE payload_hash=? ORDER BY updated_ts DESC LIMIT 1",
            (payload_hash_value,),
        ).fetchone()
        if row is None:
            return None
        return OrderTicket.model_validate_json(row[0])


def _now(clock: datetime | None) -> datetime:
    return clock if clock is not None else datetime.now(tz=UTC)


@dataclass
class OrderMachine:
    store: OrderStore
    broker: OrderBroker
    mode: OperatingMode = OperatingMode.SIGNALS_ONLY
    live_explicitly_enabled: bool = False
    _last_gate: GateResult | None = field(default=None, init=False)

    def receive(self, candidate: Candidate, now: datetime | None = None) -> OrderTicket:
        stamp = _now(now)
        payload = payload_from_candidate(candidate)
        digest = payload_hash(payload)
        existing = self.store.get_by_signal(candidate.signal_id) or self.store.get_by_hash(digest)
        if existing is not None:
            return existing
        ticket = OrderTicket(
            ticket_id=str(uuid.uuid4()),
            signal_id=candidate.signal_id,
            state=OrderState.RECEIVED,
            payload=payload,
            payload_hash=digest,
            created_ts=stamp,
            updated_ts=stamp,
        )
        self.store.put(ticket)
        return ticket

    def _transition(self, ticket: OrderTicket, dest: OrderState, now: datetime) -> OrderTicket:
        allowed = ALLOWED_TRANSITIONS.get(ticket.state, frozenset())
        if dest not in allowed:
            raise LiveGatingError(f"illegal transition {ticket.state} -> {dest}")
        updated = ticket.model_copy(update={"state": dest, "updated_ts": now})
        self.store.put(updated)
        return updated

    def validate(self, ticket_id: str, now: datetime | None = None) -> OrderTicket:
        ticket = self._require(ticket_id)
        stamp = _now(now)
        if ticket.payload.quantity != 1:
            updated = self._transition(ticket, OrderState.REJECTED, stamp)
            return updated.model_copy(update={"note": "quantity_not_one"})
        return self._transition(ticket, OrderState.VALIDATED, stamp)

    def attach_quote(self, ticket_id: str, now: datetime | None = None) -> OrderTicket:
        ticket = self._require(ticket_id)
        return self._transition(ticket, OrderState.QUOTED, _now(now))

    def preview(
        self, ticket_id: str, now: datetime | None = None
    ) -> tuple[OrderTicket, dict[str, Any]]:
        ticket = self._require(ticket_id)
        form = tradier_form(ticket.payload, preview=True)
        if form["preview"] != "true":
            raise LiveGatingError("preview must send preview=true")
        if form["tag"] != ticket.signal_id:
            raise LiveGatingError("tag must equal signal_id")
        body = self.broker.preview_option_order(form)
        updated = self._transition(ticket, OrderState.PREVIEW, _now(now))
        updated = updated.model_copy(update={"previewed": True})
        self.store.put(updated)
        return updated, body

    def final_gate(
        self, ticket_id: str, candidate: Candidate, ctx: GateContext, now: datetime | None = None
    ) -> tuple[OrderTicket, GateResult]:
        ticket = self._require(ticket_id)
        if payload_hash(payload_from_candidate(candidate)) != ticket.payload_hash:
            raise LiveGatingError("candidate no longer matches immutable payload")
        if self.mode == OperatingMode.LIVE:
            if not self.live_explicitly_enabled:
                raise LiveGatingError("live placement requires live_explicitly_enabled")
            if candidate.from_websocket:
                raise LiveGatingError("websocket events must never directly trigger live orders")
        merged = ctx.model_copy(
            update={
                "mode": self.mode,
                "live_explicitly_enabled": self.live_explicitly_enabled,
                "preview_ok": ticket.previewed or ctx.preview_ok,
            }
        )
        result = evaluate_gate(candidate, merged)
        self._last_gate = result
        stamp = _now(now)
        if not result.allowed:
            updated = self._transition(ticket, OrderState.REJECTED, stamp)
            updated = updated.model_copy(update={"note": result.note})
            self.store.put(updated)
            return updated, result
        return self._transition(ticket, OrderState.FINAL_GATE, stamp), result

    def submit(
        self, ticket_id: str, now: datetime | None = None
    ) -> tuple[OrderTicket, dict[str, Any]]:
        ticket = self._require(ticket_id)
        if not ticket.previewed:
            raise LiveGatingError("preview-before-order is required")
        if self.mode == OperatingMode.SIGNALS_ONLY:
            raise LiveGatingError("signals_only cannot submit")
        form = tradier_form(ticket.payload, preview=False)
        if form["preview"] != "false":
            raise LiveGatingError("live/paper submit must send preview=false")
        if form["tag"] != ticket.signal_id:
            raise LiveGatingError("tag must equal signal_id")
        preview_form = tradier_form(ticket.payload, preview=True)
        if {k: v for k, v in preview_form.items() if k != "preview"} != {
            k: v for k, v in form.items() if k != "preview"
        }:
            raise LiveGatingError("submit payload drifted from preview payload")
        stamp = _now(now)
        submitted = self._transition(ticket, OrderState.SUBMIT, stamp)
        body = self.broker.submit_option_order(form)
        broker_id = body.get("id")
        if isinstance(broker_id, str) and broker_id:
            acked = self._transition(submitted, OrderState.ACK, stamp)
            acked = acked.model_copy(update={"broker_order_id": broker_id})
            self.store.put(acked)
            return acked, body
        unknown = self._transition(submitted, OrderState.UNKNOWN_SUBMIT, stamp)
        return unknown, body

    def query_unknown_submit(
        self, ticket_id: str, now: datetime | None = None
    ) -> OrderTicket:
        """Never blind-retry. Ask Tradier (or stub) by tag=signal_id first."""
        ticket = self._require(ticket_id)
        if ticket.state not in {OrderState.SUBMIT, OrderState.UNKNOWN_SUBMIT}:
            return ticket
        found = self.broker.find_order_by_tag(ticket.signal_id)
        stamp = _now(now)
        if found and found.get("id"):
            dest = OrderState.ACK if ticket.state == OrderState.UNKNOWN_SUBMIT else OrderState.ACK
            if ticket.state == OrderState.SUBMIT:
                updated = self._transition(ticket, OrderState.ACK, stamp)
            else:
                updated = self._transition(ticket, dest, stamp)
            updated = updated.model_copy(update={"broker_order_id": str(found["id"])})
            self.store.put(updated)
            return updated
        if ticket.state == OrderState.SUBMIT:
            return self._transition(ticket, OrderState.UNKNOWN_SUBMIT, stamp)
        return ticket

    def mark_filled(self, ticket_id: str, now: datetime | None = None) -> OrderTicket:
        return self._transition(self._require(ticket_id), OrderState.FILLED, _now(now))

    def mark_rejected(self, ticket_id: str, now: datetime | None = None) -> OrderTicket:
        return self._transition(self._require(ticket_id), OrderState.REJECTED, _now(now))

    def reconcile_flat(self, ticket_id: str, now: datetime | None = None) -> OrderTicket:
        return self._transition(self._require(ticket_id), OrderState.FLAT_RECONCILED, _now(now))

    def _require(self, ticket_id: str) -> OrderTicket:
        ticket = self.store.get(ticket_id)
        if ticket is None:
            raise LiveGatingError(f"unknown ticket {ticket_id}")
        return ticket


__all__ = [
    "ALLOWED_TRANSITIONS",
    "MemoryOrderStore",
    "OrderBroker",
    "OrderMachine",
    "RecordingOrderBroker",
    "SqliteOrderStore",
    "payload_from_candidate",
    "payload_hash",
    "tradier_form",
]
