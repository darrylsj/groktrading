from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from groktrading.errors import LiveGatingError
from groktrading.models import OrderState
from groktrading.modes import OperatingMode
from groktrading.order_fsm import (
    MemoryOrderStore,
    OrderMachine,
    RecordingOrderBroker,
    SqliteOrderStore,
    payload_from_candidate,
    payload_hash,
    tradier_form,
)
from helpers import morning_pt, passing_candidate, passing_context


def _machine(
    mode: OperatingMode = OperatingMode.PAPER,
    store: MemoryOrderStore | SqliteOrderStore | None = None,
    broker: RecordingOrderBroker | None = None,
) -> tuple[OrderMachine, RecordingOrderBroker]:
    sink = broker or RecordingOrderBroker()
    machine = OrderMachine(
        store=store or MemoryOrderStore(),
        broker=sink,
        mode=mode,
        live_explicitly_enabled=mode == OperatingMode.LIVE,
    )
    return machine, sink


def test_preview_submit_same_payload_and_ack() -> None:
    machine, broker = _machine()
    now = morning_pt()
    candidate = passing_candidate()
    ticket = machine.receive(candidate, now)
    assert ticket.state == OrderState.RECEIVED
    ticket = machine.validate(ticket.ticket_id, now)
    ticket = machine.attach_quote(ticket.ticket_id, now)
    ticket, preview = machine.preview(ticket.ticket_id, now)
    assert ticket.previewed is True
    assert preview["preview"] is True
    assert broker.previews[0]["preview"] == "true"
    assert broker.previews[0]["tag"] == candidate.signal_id
    ticket, result = machine.final_gate(ticket.ticket_id, candidate, passing_context(), now)
    assert result.allowed is True
    assert ticket.state == OrderState.FINAL_GATE
    ticket, body = machine.submit(ticket.ticket_id, now)
    assert ticket.state == OrderState.ACK
    assert ticket.broker_order_id == "brk-1"
    assert broker.submits[0]["preview"] == "false"
    preview_core = {k: v for k, v in broker.previews[0].items() if k != "preview"}
    submit_core = {k: v for k, v in broker.submits[0].items() if k != "preview"}
    assert preview_core == submit_core
    assert body["id"] == "brk-1"
    ticket = machine.mark_filled(ticket.ticket_id, now)
    ticket = machine.reconcile_flat(ticket.ticket_id, now)
    assert ticket.state == OrderState.FLAT_RECONCILED


def test_payload_is_immutable_and_hashed() -> None:
    candidate = passing_candidate()
    payload = payload_from_candidate(candidate)
    digest = payload_hash(payload)
    with pytest.raises(ValidationError):
        payload.quantity = 2  # type: ignore[misc]
    form = tradier_form(payload, preview=True)
    assert form["tag"] == candidate.signal_id
    assert payload_hash(payload) == digest


def test_unknown_submit_queries_broker_never_blind_retries() -> None:
    broker = RecordingOrderBroker()
    broker.submit_acks = False
    machine, _ = _machine(broker=broker)
    now = morning_pt()
    candidate = passing_candidate()
    ticket = machine.receive(candidate, now)
    ticket = machine.validate(ticket.ticket_id, now)
    ticket = machine.attach_quote(ticket.ticket_id, now)
    ticket, _ = machine.preview(ticket.ticket_id, now)
    ticket, _ = machine.final_gate(ticket.ticket_id, candidate, passing_context(), now)
    ticket, _ = machine.submit(ticket.ticket_id, now)
    assert ticket.state == OrderState.UNKNOWN_SUBMIT
    assert len(broker.submits) == 1
    queried = machine.query_unknown_submit(ticket.ticket_id, now)
    assert queried.state == OrderState.UNKNOWN_SUBMIT
    assert len(broker.submits) == 1
    broker.known_by_tag[candidate.signal_id] = {"id": "found-9", "tag": candidate.signal_id}
    acked = machine.query_unknown_submit(ticket.ticket_id, now)
    assert acked.state == OrderState.ACK
    assert acked.broker_order_id == "found-9"
    assert len(broker.submits) == 1


def test_sqlite_store_persists_signal_and_hash(tmp_path: Path) -> None:
    store = SqliteOrderStore(tmp_path / "orders.sqlite")
    machine, _ = _machine(store=store)
    now = morning_pt()
    candidate = passing_candidate()
    ticket = machine.receive(candidate, now)
    again = SqliteOrderStore(tmp_path / "orders.sqlite")
    loaded = again.get(ticket.ticket_id)
    assert loaded is not None
    assert loaded.signal_id == candidate.signal_id
    assert loaded.payload_hash == ticket.payload_hash
    assert again.get_by_signal(candidate.signal_id) is not None


def test_live_websocket_blocked_on_final_gate() -> None:
    machine, broker = _machine(mode=OperatingMode.LIVE)
    now = morning_pt()
    candidate = passing_candidate(from_websocket=True)
    ticket = machine.receive(candidate, now)
    ticket = machine.validate(ticket.ticket_id, now)
    ticket = machine.attach_quote(ticket.ticket_id, now)
    ticket, _ = machine.preview(ticket.ticket_id, now)
    with pytest.raises(LiveGatingError, match="websocket"):
        machine.final_gate(ticket.ticket_id, candidate, passing_context(), now)
    assert broker.submits == []


def test_submit_refuses_after_gate_passed_ttl() -> None:
    machine, broker = _machine()
    now = morning_pt()
    candidate = passing_candidate()
    ticket = machine.receive(candidate, now)
    ticket = machine.validate(ticket.ticket_id, now)
    ticket = machine.attach_quote(ticket.ticket_id, now)
    ticket, _ = machine.preview(ticket.ticket_id, now)
    ticket, result = machine.final_gate(ticket.ticket_id, candidate, passing_context(), now)
    assert result.allowed is True
    assert ticket.state == OrderState.FINAL_GATE
    assert ticket.gate_passed_ts == now
    later = now + timedelta(seconds=6)
    with pytest.raises(LiveGatingError, match="gate_passed_stale"):
        machine.submit(ticket.ticket_id, later)
    rejected = machine.store.get(ticket.ticket_id)
    assert rejected is not None
    assert rejected.state == OrderState.REJECTED
    assert rejected.note == "gate_passed_stale"
    assert broker.submits == []


def test_signals_only_cannot_submit() -> None:
    machine, _ = _machine(mode=OperatingMode.SIGNALS_ONLY)
    now = morning_pt()
    candidate = passing_candidate()
    ticket = machine.receive(candidate, now)
    ticket = machine.validate(ticket.ticket_id, now)
    ticket = machine.attach_quote(ticket.ticket_id, now)
    ticket, _ = machine.preview(ticket.ticket_id, now)
    with pytest.raises(LiveGatingError, match="signals_only"):
        machine.submit(ticket.ticket_id, now)
