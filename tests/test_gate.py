from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from groktrading.gate import evaluate_gate
from groktrading.models import AccountSnapshot, ClockSnapshot, GateReason, MarketState, OptionQuote
from groktrading.modes import OperatingMode
from helpers import morning_pt, passing_candidate, passing_context


def test_passing_paper_gate() -> None:
    result = evaluate_gate(passing_candidate(), passing_context())
    assert result.allowed is True
    assert result.reasons == [GateReason.OK]


def test_stale_quote() -> None:
    now = morning_pt()
    ctx = passing_context(
        now=now,
        quote=OptionQuote(
            option_symbol="SPY260903C00600000",
            bid=Decimal("1.20"),
            ask=Decimal("1.25"),
            quote_ts=now - timedelta(seconds=30),
            source="tradier_production",
            delayed=False,
        ),
        max_quote_age_seconds=5.0,
    )
    result = evaluate_gate(passing_candidate(created_ts=now), ctx)
    assert GateReason.STALE_QUOTE in result.reasons
    assert result.allowed is False


def test_matching_ask_threshold() -> None:
    result = evaluate_gate(
        passing_candidate(proposed_limit=Decimal("1.24")),
        passing_context(matching_ask_tolerance=Decimal("0")),
    )
    assert GateReason.MATCHING_ASK_FAILED in result.reasons
    ok = evaluate_gate(
        passing_candidate(proposed_limit=Decimal("1.26")),
        passing_context(matching_ask_tolerance=Decimal("0.02")),
    )
    assert ok.allowed is True


def test_sit2() -> None:
    result = evaluate_gate(passing_candidate(sit_confirmations=1), passing_context())
    assert GateReason.SIT2_INCOMPLETE in result.reasons


def test_already_run() -> None:
    result = evaluate_gate(passing_candidate(already_run=True), passing_context())
    assert GateReason.ALREADY_RUN in result.reasons


def test_first_red() -> None:
    result = evaluate_gate(passing_candidate(is_first_red=True), passing_context())
    assert GateReason.FIRST_RED in result.reasons


def test_quantity_must_be_one() -> None:
    result = evaluate_gate(passing_candidate(quantity=2), passing_context())
    assert GateReason.QUANTITY_NOT_ONE in result.reasons


def test_duplicate_working_order() -> None:
    now = morning_pt()
    account = AccountSnapshot(
        cash=Decimal("600"),
        buying_power=Decimal("600"),
        working_option_symbols=["SPY260903C00600000"],
        as_of=now,
    )
    result = evaluate_gate(passing_candidate(), passing_context(account=account))
    assert GateReason.DUPLICATE_OR_WORKING in result.reasons


def test_insufficient_cash() -> None:
    now = morning_pt()
    account = AccountSnapshot(
        cash=Decimal("10"),
        buying_power=Decimal("10"),
        as_of=now,
    )
    result = evaluate_gate(passing_candidate(), passing_context(account=account))
    assert GateReason.INSUFFICIENT_CASH in result.reasons


def test_clock_closed() -> None:
    now = morning_pt()
    clock = ClockSnapshot(state=MarketState.CLOSED, as_of=now)
    result = evaluate_gate(passing_candidate(), passing_context(clock=clock))
    assert GateReason.MARKET_CLOSED in result.reasons


def test_ttl_expired() -> None:
    now = morning_pt()
    result = evaluate_gate(
        passing_candidate(created_ts=now - timedelta(seconds=60), ttl_seconds=15.0),
        passing_context(now=now),
    )
    assert GateReason.TTL_EXPIRED in result.reasons


def test_signals_only_never_allows() -> None:
    result = evaluate_gate(
        passing_candidate(),
        passing_context(mode=OperatingMode.SIGNALS_ONLY),
    )
    assert result.allowed is False
    assert GateReason.SIGNALS_ONLY in result.reasons
