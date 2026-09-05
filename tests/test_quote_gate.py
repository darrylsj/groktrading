from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from groktrading.models import GateReason, OptionQuote
from groktrading.quote_gate import normalize_occ, validate_entry_quote
from helpers import morning_pt, passing_quote


def _reasons(quote: OptionQuote, **kwargs: object) -> list[GateReason]:
    now = morning_pt()
    return validate_entry_quote(
        quote,
        str(kwargs.pop("expected_occ", "SPY260903C00600000")),
        now,
        live=bool(kwargs.pop("live", True)),
        max_age_seconds=float(kwargs.pop("max_age_seconds", 5.0)),
        max_spread=Decimal(str(kwargs.pop("max_spread", "0.50"))),
        max_spread_frac=Decimal(str(kwargs.pop("max_spread_frac", "0.25"))),
        proposed_limit=Decimal(str(kwargs.pop("proposed_limit", "1.25"))),
    )


def test_normalize_occ_strips_space_and_dash() -> None:
    assert normalize_occ("spy 260903C00600000") == "SPY260903C00600000"
    assert normalize_occ("SPY-260903C00600000") == "SPY260903C00600000"


def test_wrong_occ_rejected() -> None:
    quote = passing_quote(
        option_symbol="AAPL260903C00200000",
        provider_symbol="AAPL260903C00200000",
    )
    reasons = _reasons(quote)
    assert GateReason.QUOTE_OCC_MISMATCH in reasons


def test_sandbox_cannot_pass_live() -> None:
    quote = passing_quote(source="tradier_sandbox", delayed=False)
    reasons = _reasons(quote, live=True)
    assert GateReason.QUOTE_SANDBOX in reasons
    assert GateReason.QUOTE_DELAYED in reasons


def test_synthetic_cannot_pass_live() -> None:
    quote = passing_quote(source="synthetic", delayed=False)
    reasons = _reasons(quote, live=True)
    assert GateReason.QUOTE_SYNTHETIC in reasons


def test_zero_ask_rejected() -> None:
    quote = passing_quote(ask=Decimal("0"))
    reasons = _reasons(quote)
    assert GateReason.QUOTE_ASK_NOT_POSITIVE in reasons


def test_crossed_market_rejected() -> None:
    quote = passing_quote(bid=Decimal("1.40"), ask=Decimal("1.25"))
    reasons = _reasons(quote)
    assert GateReason.QUOTE_CROSSED in reasons


def test_stale_provider_dates_rejected() -> None:
    now = morning_pt()
    stale = now - timedelta(seconds=30)
    quote = passing_quote(now, bid_date=stale, ask_date=stale, quote_ts=stale, received_ts=now)
    reasons = _reasons(quote)
    assert GateReason.QUOTE_PROVIDER_STALE in reasons
    assert GateReason.STALE_QUOTE in reasons


def test_future_provider_timestamp_rejected() -> None:
    now = morning_pt()
    future = now + timedelta(seconds=30)
    quote = passing_quote(now, bid_date=future, ask_date=future, quote_ts=future)
    reasons = _reasons(quote)
    assert GateReason.QUOTE_FUTURE_TS in reasons


def test_missing_provider_fields_rejected() -> None:
    quote = OptionQuote(
        option_symbol="SPY260903C00600000",
        bid=Decimal("1.20"),
        ask=Decimal("1.25"),
        quote_ts=morning_pt(),
        source="tradier_production",
        delayed=False,
    )
    reasons = _reasons(quote)
    assert GateReason.QUOTE_MISSING_FIELDS in reasons


def test_http_time_fresh_but_provider_stale_still_fails() -> None:
    now = morning_pt()
    stale = now - timedelta(seconds=45)
    quote = passing_quote(now, bid_date=stale, ask_date=stale, quote_ts=now, received_ts=now)
    reasons = _reasons(quote)
    assert GateReason.QUOTE_PROVIDER_STALE in reasons


def test_wide_spread_and_no_chase() -> None:
    quote = passing_quote(bid=Decimal("0.10"), ask=Decimal("1.80"))
    reasons = _reasons(quote, proposed_limit=Decimal("1.25"))
    assert GateReason.QUOTE_SPREAD in reasons
    assert GateReason.NO_CHASE in reasons


def test_production_fresh_quote_passes() -> None:
    reasons = _reasons(passing_quote())
    assert reasons == []
