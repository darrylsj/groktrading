"""Signals-only executor stub with explicit live gating.

Default mode never places orders. WebSocket callbacks cannot reach live
placement. Paper and live paths require explicit OperatingMode and, for
live, live_explicitly_enabled plus a passed gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from groktrading.errors import LiveGatingError
from groktrading.gate import evaluate_gate
from groktrading.models import Candidate, GateContext, GateResult
from groktrading.modes import OperatingMode


class OrderSink(Protocol):
    def submit(self, candidate: Candidate, preview: bool) -> dict[str, Any]:
        ...


class RecordingSink:
    def __init__(self) -> None:
        self.submissions: list[tuple[Candidate, bool]] = []

    def submit(self, candidate: Candidate, preview: bool) -> dict[str, Any]:
        self.submissions.append((candidate, preview))
        return {"status": "recorded", "preview": preview, "signal_id": candidate.signal_id}


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
        # Live still previews first; actual placement is out of this stub by design.
        return result
