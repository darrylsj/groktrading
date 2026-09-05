"""P0.1 Tradier production option-quote validation before entry.

Live path requires a fresh production NBBO. HTTP receive time is not enough:
provider bid_date/ask_date are the age source. Sandbox and synthetic quotes
cannot pass live. Fail closed on missing fields, crossed markets, future
timestamps, wide spreads, and OCC mismatch after normalize.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from groktrading.models import Candidate, GateReason, OptionQuote
from groktrading.timeutil import is_future_ts, is_stale, quote_age_seconds


def normalize_occ(symbol: str) -> str:
    return "".join(symbol.split()).replace("-", "").upper()


def occ_symbols_match(left: str, right: str) -> bool:
    return normalize_occ(left) == normalize_occ(right)


def _missing_quote_fields(quote: OptionQuote) -> list[str]:
    missing: list[str] = []
    if not quote.option_symbol:
        missing.append("option_symbol")
    if quote.bid is None:
        missing.append("bid")
    if quote.ask is None:
        missing.append("ask")
    if quote.bid_date is None:
        missing.append("bid_date")
    if quote.ask_date is None:
        missing.append("ask_date")
    if quote.source is None:
        missing.append("source")
    return missing


def validate_entry_quote(
    quote: OptionQuote,
    expected_occ: str,
    now: datetime,
    *,
    live: bool,
    max_age_seconds: float,
    max_spread: Decimal,
    max_spread_frac: Decimal,
    proposed_limit: Decimal | None = None,
    matching_ask_tolerance: Decimal = Decimal("0"),
) -> list[GateReason]:
    """Return gate reasons that block using this quote for an entry."""
    reasons: list[GateReason] = []
    missing = _missing_quote_fields(quote)
    if missing:
        reasons.append(GateReason.QUOTE_MISSING_FIELDS)
        return reasons

    provider_symbol = quote.provider_symbol or quote.option_symbol
    if not occ_symbols_match(expected_occ, quote.option_symbol) or not occ_symbols_match(
        expected_occ, provider_symbol
    ):
        reasons.append(GateReason.QUOTE_OCC_MISMATCH)

    if live and quote.source == "tradier_sandbox":
        reasons.append(GateReason.QUOTE_SANDBOX)
    if live and quote.source == "synthetic":
        reasons.append(GateReason.QUOTE_SYNTHETIC)
    if live and quote.source != "tradier_production":
        if GateReason.QUOTE_SANDBOX not in reasons and GateReason.QUOTE_SYNTHETIC not in reasons:
            reasons.append(GateReason.QUOTE_SANDBOX)
    if quote.delayed or (live and quote.source != "tradier_production"):
        if GateReason.QUOTE_DELAYED not in reasons:
            reasons.append(GateReason.QUOTE_DELAYED)

    if quote.ask <= 0:
        reasons.append(GateReason.QUOTE_ASK_NOT_POSITIVE)
    if quote.bid < 0:
        reasons.append(GateReason.QUOTE_CROSSED)
    if quote.bid > quote.ask:
        reasons.append(GateReason.QUOTE_CROSSED)

    timestamps = [quote.quote_ts, quote.bid_date, quote.ask_date, quote.received_ts]
    for ts in timestamps:
        if ts is not None and is_future_ts(ts, now):
            reasons.append(GateReason.QUOTE_FUTURE_TS)
            break

    assert quote.bid_date is not None
    assert quote.ask_date is not None
    provider_age = max(
        quote_age_seconds(quote.bid_date, now),
        quote_age_seconds(quote.ask_date, now),
    )
    if provider_age < 0:
        if GateReason.QUOTE_FUTURE_TS not in reasons:
            reasons.append(GateReason.QUOTE_FUTURE_TS)
    if is_stale(quote.bid_date, now, max_age_seconds) or is_stale(
        quote.ask_date, now, max_age_seconds
    ):
        reasons.append(GateReason.QUOTE_PROVIDER_STALE)
        reasons.append(GateReason.STALE_QUOTE)

    if quote.ask > 0:
        spread = quote.ask - quote.bid
        frac = spread / quote.ask
        if spread > max_spread or frac > max_spread_frac:
            reasons.append(GateReason.QUOTE_SPREAD)

    if proposed_limit is not None and quote.ask > proposed_limit + matching_ask_tolerance:
        reasons.append(GateReason.NO_CHASE)

    return reasons


def validate_candidate_quote(
    candidate: Candidate,
    quote: OptionQuote,
    now: datetime,
    *,
    live: bool,
    max_age_seconds: float,
    max_spread: Decimal,
    max_spread_frac: Decimal,
    matching_ask_tolerance: Decimal = Decimal("0"),
) -> list[GateReason]:
    return validate_entry_quote(
        quote,
        candidate.option_symbol,
        now,
        live=live,
        max_age_seconds=max_age_seconds,
        max_spread=max_spread,
        max_spread_frac=max_spread_frac,
        proposed_limit=candidate.proposed_limit,
        matching_ask_tolerance=matching_ask_tolerance,
    )
