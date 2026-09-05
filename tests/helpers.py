"""Shared builders for gate tests. Default is paper with a passing setup."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from groktrading.models import (
    AccountSnapshot,
    Candidate,
    ClockSnapshot,
    GateContext,
    MarketState,
    OptionQuote,
    SessionFacts,
)
from groktrading.modes import OperatingMode

PT = ZoneInfo("America/Los_Angeles")


def morning_pt() -> datetime:
    return datetime(2026, 9, 3, 7, 30, tzinfo=PT)


def passing_candidate(**kwargs: object) -> Candidate:
    now = morning_pt()
    data: dict[str, object] = {
        "signal_id": "sig-1",
        "underlying": "SPY",
        "option_symbol": "SPY260903C00600000",
        "quantity": 1,
        "proposed_limit": Decimal("1.25"),
        "sit_confirmations": 2,
        "is_first_red": False,
        "already_run": False,
        "created_ts": now,
        "ttl_seconds": 15.0,
        "from_websocket": False,
    }
    data.update(kwargs)
    return Candidate.model_validate(data)


def passing_quote(now: datetime | None = None, **kwargs: object) -> OptionQuote:
    stamp = now or morning_pt()
    data: dict[str, object] = {
        "option_symbol": "SPY260903C00600000",
        "bid": Decimal("1.20"),
        "ask": Decimal("1.25"),
        "quote_ts": stamp,
        "source": "tradier_production",
        "delayed": False,
        "bid_date": stamp,
        "ask_date": stamp,
        "received_ts": stamp,
        "provider_symbol": "SPY260903C00600000",
    }
    data.update(kwargs)
    return OptionQuote.model_validate(data)


def passing_session_facts(now: datetime | None = None, **kwargs: object) -> SessionFacts:
    stamp = now or morning_pt()
    data: dict[str, object] = {
        "sit_confirmations": 2,
        "already_run_underlyings": [],
        "already_run_option_symbols": [],
        "first_red_option_symbols": [],
        "as_of": stamp,
    }
    data.update(kwargs)
    return SessionFacts.model_validate(data)


def passing_context(**kwargs: object) -> GateContext:
    raw_now = kwargs.get("now", morning_pt())
    now = raw_now if isinstance(raw_now, datetime) else morning_pt()
    quote = kwargs.get("quote", passing_quote(now))
    account = kwargs.get(
        "account",
        AccountSnapshot(
            cash=Decimal("600"),
            buying_power=Decimal("600"),
            working_option_symbols=[],
            open_position_symbols=[],
            as_of=now,
            equity=Decimal("600"),
        ),
    )
    clock = kwargs.get("clock", ClockSnapshot(state=MarketState.OPEN, as_of=now))
    session = kwargs.get("session_facts", passing_session_facts(now))
    data: dict[str, object] = {
        "now": now,
        "quote": quote,
        "account": account,
        "clock": clock,
        "mode": OperatingMode.PAPER,
        "live_explicitly_enabled": False,
        "preview_ok": True,
        "matching_ask_tolerance": Decimal("0"),
        "max_quote_age_seconds": 5.0,
        "cash_up_enforced": True,
        "cash_equity_floor": Decimal("0.20"),
        "max_deploy_ratio": Decimal("0.80"),
        "session_facts": session,
    }
    data.update(kwargs)
    return GateContext.model_validate(data)
