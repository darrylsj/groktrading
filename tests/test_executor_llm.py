from __future__ import annotations

import pytest

from groktrading.errors import LiveGatingError
from groktrading.executor import Executor, RecordingSink
from groktrading.llm import StaticSkipLLM, assert_no_broker_attr
from groktrading.models import AssembledFacts, GateReason
from groktrading.modes import OperatingMode
from helpers import morning_pt, passing_candidate, passing_context


def test_websocket_never_places_live() -> None:
    exe = Executor(mode=OperatingMode.LIVE, live_explicitly_enabled=True, sink=RecordingSink())
    with pytest.raises(LiveGatingError, match="websocket"):
        exe.on_websocket_event(passing_candidate(), passing_context(mode=OperatingMode.LIVE))
    assert exe.sink.submissions == []  # type: ignore[union-attr]


def test_signals_only_stub_records_no_orders() -> None:
    sink = RecordingSink()
    exe = Executor(mode=OperatingMode.SIGNALS_ONLY, sink=sink)
    result = exe.maybe_submit(passing_candidate(), passing_context())
    assert result.allowed is False
    assert GateReason.SIGNALS_ONLY in result.reasons
    assert sink.submissions == []


def test_paper_submit_requires_gate_pass() -> None:
    sink = RecordingSink()
    exe = Executor(mode=OperatingMode.PAPER, sink=sink)
    ctx = passing_context(mode=OperatingMode.PAPER, preview_ok=True)
    exe.maybe_submit(passing_candidate(), ctx)
    assert len(sink.submissions) == 1
    assert sink.submissions[0][1] is True


def test_llm_skip_has_no_broker() -> None:
    llm = StaticSkipLLM()
    assert_no_broker_attr(llm)
    facts = AssembledFacts(
        signal_id="sig-1",
        underlying="SPY",
        option_symbol="SPY260903C00600000",
        ask="1.25",
        bid="1.20",
        sit_confirmations=2,
        as_of=morning_pt(),
    )
    decision = llm.decide(facts)
    assert decision.action == "skip"
    assert "invent" in decision.thesis.lower() or "skip" in decision.thesis.lower()
