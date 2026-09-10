from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from groktrading.gate import evaluate_gate
from groktrading.models import AccountSnapshot, ClockSnapshot, GateReason, MarketState, OptionQuote
from groktrading.modes import OperatingMode
from groktrading.timeutil import PT
from helpers import morning_pt, passing_candidate, passing_context, passing_session_facts


def test_passing_paper_gate() -> None:
    result = evaluate_gate(passing_candidate(), passing_context())
    assert result.allowed is True
    assert result.reasons == [GateReason.OK]


def test_stale_quote() -> None:
    now = morning_pt()
    stale = now - timedelta(seconds=30)
    ctx = passing_context(
        now=now,
        quote=OptionQuote(
            option_symbol="SPY260903C00600000",
            bid=Decimal("1.20"),
            ask=Decimal("1.25"),
            quote_ts=stale,
            source="tradier_production",
            delayed=False,
            bid_date=stale,
            ask_date=stale,
            received_ts=now,
            provider_symbol="SPY260903C00600000",
        ),
        max_quote_age_seconds=5.0,
    )
    result = evaluate_gate(passing_candidate(created_ts=now), ctx)
    assert GateReason.STALE_QUOTE in result.reasons
    assert GateReason.QUOTE_PROVIDER_STALE in result.reasons
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
    assert result.allowed is False
    assert GateReason.SIT2_INCOMPLETE in result.reasons
    assert GateReason.MUST_TRADE_SMALL_EXCEPTION not in result.reasons


def test_must_trade_small_sit1_skips_only_sit2() -> None:
    result = evaluate_gate(
        passing_candidate(sit_confirmations=1, must_trade_small=True),
        passing_context(),
    )
    assert result.allowed is True
    assert GateReason.SIT2_INCOMPLETE not in result.reasons
    assert GateReason.MUST_TRADE_SMALL_EXCEPTION in result.reasons
    assert "must_trade_small_exception" in result.note


def test_must_trade_small_does_not_bypass_cash_qty_or_matching_ask() -> None:
    now = morning_pt()
    cash_account = AccountSnapshot(
        cash=Decimal("150"),
        buying_power=Decimal("150"),
        as_of=now,
        equity=Decimal("150"),
    )
    cash = evaluate_gate(
        passing_candidate(sit_confirmations=1, must_trade_small=True),
        passing_context(account=cash_account),
    )
    assert cash.allowed is False
    assert GateReason.CASH_RESERVE in cash.reasons
    assert GateReason.SIT2_INCOMPLETE not in cash.reasons
    assert GateReason.MUST_TRADE_SMALL_EXCEPTION in cash.reasons

    qty = evaluate_gate(
        passing_candidate(sit_confirmations=1, must_trade_small=True, quantity=2),
        passing_context(),
    )
    assert qty.allowed is False
    assert GateReason.QUANTITY_NOT_ONE in qty.reasons
    assert GateReason.SIT2_INCOMPLETE not in qty.reasons

    ask = evaluate_gate(
        passing_candidate(
            sit_confirmations=1,
            must_trade_small=True,
            proposed_limit=Decimal("1.24"),
        ),
        passing_context(matching_ask_tolerance=Decimal("0")),
    )
    assert ask.allowed is False
    assert GateReason.MATCHING_ASK_FAILED in ask.reasons
    assert GateReason.SIT2_INCOMPLETE not in ask.reasons


def test_must_trade_small_refuses_ask_above_small_band_unless_committed_i2() -> None:
    now = morning_pt()
    quote = OptionQuote(
        option_symbol="SPY260903C00600000",
        bid=Decimal("1.55"),
        ask=Decimal("1.60"),
        quote_ts=now,
        source="tradier_production",
        delayed=False,
        bid_date=now,
        ask_date=now,
        received_ts=now,
        provider_symbol="SPY260903C00600000",
    )
    blocked = evaluate_gate(
        passing_candidate(
            sit_confirmations=1,
            must_trade_small=True,
            proposed_limit=Decimal("1.60"),
            created_ts=now,
        ),
        passing_context(now=now, quote=quote),
    )
    assert blocked.allowed is False
    assert GateReason.ASK_ABOVE_SMALL_BAND in blocked.reasons
    assert GateReason.SIT2_INCOMPLETE not in blocked.reasons

    waived = evaluate_gate(
        passing_candidate(
            sit_confirmations=1,
            must_trade_small=True,
            committed_i2=True,
            proposed_limit=Decimal("1.60"),
            created_ts=now,
        ),
        passing_context(now=now, quote=quote),
    )
    assert waived.allowed is True
    assert GateReason.ASK_ABOVE_SMALL_BAND not in waived.reasons
    assert GateReason.MUST_TRADE_SMALL_EXCEPTION in waived.reasons


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


def test_entry_cutoff_blocks_new_risk_not_overnight() -> None:
    now = datetime(2026, 9, 3, 12, 30, tzinfo=PT)
    result = evaluate_gate(
        passing_candidate(created_ts=now),
        passing_context(now=now, session_facts=passing_session_facts(now)),
    )
    assert result.allowed is False
    assert GateReason.ENTRY_CUTOFF in result.reasons
    assert GateReason.OVERNIGHT_FORBIDDEN not in result.reasons


def test_live_requires_session_facts() -> None:
    result = evaluate_gate(
        passing_candidate(),
        passing_context(
            mode=OperatingMode.LIVE,
            live_explicitly_enabled=True,
            session_facts=None,
        ),
    )
    assert GateReason.SESSION_FACTS_REQUIRED in result.reasons
    assert result.allowed is False


def test_session_facts_already_run_overrides_candidate() -> None:
    result = evaluate_gate(
        passing_candidate(already_run=False),
        passing_context(
            session_facts=passing_session_facts(already_run_underlyings=["SPY"])
        ),
    )
    assert GateReason.ALREADY_RUN in result.reasons


def test_broker_position_is_authoritative() -> None:
    now = morning_pt()
    account = AccountSnapshot(
        cash=Decimal("600"),
        buying_power=Decimal("600"),
        working_option_symbols=[],
        open_position_symbols=["SPY260903C00600000"],
        as_of=now,
        equity=Decimal("600"),
    )
    result = evaluate_gate(passing_candidate(), passing_context(account=account))
    assert GateReason.IN_POSITION in result.reasons
    assert GateReason.DUPLICATE_OR_WORKING in result.reasons


def test_cash_equity_floor_twenty_percent() -> None:
    now = morning_pt()
    account = AccountSnapshot(
        cash=Decimal("150"),
        buying_power=Decimal("150"),
        as_of=now,
        equity=Decimal("150"),
    )
    result = evaluate_gate(passing_candidate(), passing_context(account=account))
    assert result.allowed is False
    assert GateReason.CASH_RESERVE in result.reasons


def test_ws_direct_live_forbidden() -> None:
    result = evaluate_gate(
        passing_candidate(from_websocket=True),
        passing_context(mode=OperatingMode.LIVE, live_explicitly_enabled=True),
    )
    assert GateReason.WS_DIRECT_LIVE_FORBIDDEN in result.reasons


def test_live_missing_executed_at_rejected() -> None:
    now = morning_pt()
    result = evaluate_gate(
        passing_candidate(created_ts=now),
        passing_context(
            now=now,
            mode=OperatingMode.LIVE,
            live_explicitly_enabled=True,
        ),
    )
    assert result.allowed is False
    assert GateReason.MISSING_EXECUTED_AT in result.reasons
    assert "missing_executed_at" in result.note


def test_live_stale_executed_at_rejected_does_not_use_created_ts() -> None:
    now = morning_pt()
    result = evaluate_gate(
        passing_candidate(
            created_ts=now,
            executed_at=now - timedelta(seconds=61),
        ),
        passing_context(
            now=now,
            mode=OperatingMode.LIVE,
            live_explicitly_enabled=True,
        ),
    )
    assert result.allowed is False
    assert GateReason.STALE_PRINT in result.reasons
    assert "stale_print" in result.note
    assert GateReason.MISSING_EXECUTED_AT not in result.reasons


def test_live_fresh_executed_at_passes_other_gates() -> None:
    now = morning_pt()
    result = evaluate_gate(
        passing_candidate(created_ts=now, executed_at=now - timedelta(seconds=5)),
        passing_context(
            now=now,
            mode=OperatingMode.LIVE,
            live_explicitly_enabled=True,
        ),
    )
    assert result.allowed is True
    assert GateReason.OK in result.reasons
    assert GateReason.MISSING_EXECUTED_AT not in result.reasons
    assert GateReason.STALE_PRINT not in result.reasons

