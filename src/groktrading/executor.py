"""Signals-only executor stub with explicit live gating.

Default mode never places orders. WebSocket callbacks cannot reach live
placement. Paper and live paths require explicit OperatingMode and, for
live, live_explicitly_enabled plus a passed gate. Live submit is never
driven by a WebSocket tick alone; the final gate rechecks a fresh quote.

P0.3 order lifecycle lives in `order_fsm.OrderMachine` (preview exact
payload → refresh + rerun gate → submit same payload with preview=false).
This stub still previews first and does not auto-submit live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from groktrading.brokers.protocol import Broker
from groktrading.errors import LiveGatingError
from groktrading.gate import evaluate_gate
from groktrading.models import Candidate, GateContext, GateResult
from groktrading.modes import OperatingMode
from groktrading.order_fsm import payload_from_candidate, tradier_form


class OrderSink(Protocol):
    def submit(self, candidate: Candidate, preview: bool) -> dict[str, Any]:
        ...


class RecordingSink:
    def __init__(self) -> None:
        self.submissions: list[tuple[Candidate, bool]] = []

    def submit(self, candidate: Candidate, preview: bool) -> dict[str, Any]:
        self.submissions.append((candidate, preview))
        return {"status": "recorded", "preview": preview, "signal_id": candidate.signal_id}


class BrokerSink:
    """OrderSink adapter over the venue-aware Broker protocol.

    Phase A still uses the existing Tradier form body so preview/submit
    stay byte-compatible with OrderMachine.
    """

    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    def submit(self, candidate: Candidate, preview: bool) -> dict[str, Any]:
        form = tradier_form(payload_from_candidate(candidate), preview=preview)
        if preview:
            return self.broker.preview_option_order(form)
        return self.broker.submit_option_order(form)


@dataclass
class Executor:
    mode: OperatingMode = OperatingMode.SIGNALS_ONLY
    live_explicitly_enabled: bool = False
    sink: OrderSink | None = None
    signals: list[GateResult] = field(default_factory=list)

    def on_websocket_event(self, candidate: Candidate, ctx: GateContext) -> GateResult:
        """WS path: never live. Candidate is marked from_websocket."""
        marked = candidate.model_copy(update={"from_websocket": True})
        result = evaluate_gate(marked, ctx)
        self.signals.append(result)
        if ctx.mode == OperatingMode.LIVE or self.mode == OperatingMode.LIVE:
            raise LiveGatingError("websocket events must never directly trigger live orders")
        return result

    def evaluate(self, candidate: Candidate, ctx: GateContext) -> GateResult:
        merged = ctx.model_copy(
            update={
                "mode": self.mode,
                "live_explicitly_enabled": self.live_explicitly_enabled,
            }
        )
        result = evaluate_gate(candidate, merged)
        self.signals.append(result)
        return result

    def maybe_submit(self, candidate: Candidate, ctx: GateContext) -> GateResult:
        result = self.evaluate(candidate, ctx)
        if self.mode == OperatingMode.SIGNALS_ONLY:
            return result
        if not result.allowed:
            return result
        if self.mode == OperatingMode.LIVE:
            if not self.live_explicitly_enabled:
                raise LiveGatingError("live placement requires live_explicitly_enabled")
            if candidate.from_websocket:
                raise LiveGatingError("websocket events must never directly trigger live orders")
        if self.sink is None:
            raise LiveGatingError("no order sink configured")
        preview = True
        self.sink.submit(candidate, preview=preview)
        if self.mode == OperatingMode.PAPER:
            return result
        # Live still previews first; placement is OrderMachine.submit after a refreshed gate.
        return result


__all__ = ["BrokerSink", "Executor", "OrderSink", "RecordingSink"]
