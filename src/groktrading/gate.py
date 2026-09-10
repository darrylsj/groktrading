"""Deterministic live/paper gate.

WebSocket events never directly trigger live orders. The final gate rechecks a
fresh Tradier production option quote (provider timestamps, OCC, delayed flag)
and derives sit / already-run / duplicate / position from durable session facts
plus a fresh broker snapshot. Candidate-supplied booleans cannot pass live
alone. Quantity is exactly 1. Cash/equity floor is ≥20% (max deploy 80%).
12:30 PT is a new-entry cutoff only — overnight longs stay allowed.

Sit-2 remains the I2 lean bar (hard reject when sit < 2). ``must_trade_small``
skips only that reject and records ``must_trade_small_exception``. It does not
relax freshness, matching ask, cash floor, qty=1, BTO-only, entry cutoff, or
already-run. The ~11:00 PT daily-lot clock is Continual15 (not encoded here).

Live requires ``candidate.executed_at`` (print clock) age ≤
``SIT_MATCH_MAX_AGE_SEC`` (default 60s). Missing/unparseable/stale fails
closed. Do not substitute ``created_ts`` / ``created_at`` / ``timestamp``.
"""

from __future__ import annotations

from decimal import Decimal

from groktrading.models import (
    Candidate,
    GateContext,
    GateReason,
    GateResult,
    MarketState,
    SessionFacts,
)
from groktrading.modes import OperatingMode
from groktrading.policy import MUST_TRADE_SMALL_ASK_CAP, breaches_cash_floor
from groktrading.quote_gate import normalize_occ, validate_candidate_quote
from groktrading.sit_match import (
    REASON_FUTURE,
    REASON_MISSING,
    REASON_STALE,
    REASON_UNPARSEABLE,
    evaluate_sit_match_freshness,
)
from groktrading.timeutil import is_stale, past_entry_cutoff

CONTRACT_MULTIPLIER = Decimal("100")
_INFORMATIONAL_REASONS = frozenset({GateReason.MUST_TRADE_SMALL_EXCEPTION})


def _normalized_set(symbols: list[str]) -> set[str]:
    return {normalize_occ(symbol) for symbol in symbols}


def _derived_session_flags(
    candidate: Candidate, facts: SessionFacts | None, *, live: bool
) -> tuple[int, bool, bool, list[GateReason]]:
    """Conservative union: session facts win; candidate cannot clear a block."""
    extra: list[GateReason] = []
    if facts is None:
        if live:
            extra.append(GateReason.SESSION_FACTS_REQUIRED)
        return candidate.sit_confirmations, candidate.already_run, candidate.is_first_red, extra

    sit = min(candidate.sit_confirmations, facts.sit_confirmations)
    occ = normalize_occ(candidate.option_symbol)
    already = (
        candidate.already_run
        or candidate.underlying.upper() in {u.upper() for u in facts.already_run_underlyings}
        or occ in _normalized_set(facts.already_run_option_symbols)
    )
    first_red = candidate.is_first_red or occ in _normalized_set(facts.first_red_option_symbols)
    return sit, already, first_red, extra


def _live_print_reasons(candidate: Candidate, ctx: GateContext, *, live: bool) -> list[GateReason]:
    """Live executor: ``executed_at`` only. No created_at/timestamp substitute."""
    if not live:
        return []
    decision = evaluate_sit_match_freshness(candidate.executed_at, ctx.now)
    if decision.allow:
        return []
    if decision.reason == REASON_MISSING:
        return [GateReason.MISSING_EXECUTED_AT]
    if decision.reason == REASON_UNPARSEABLE:
        return [GateReason.UNPARSEABLE_EXECUTED_AT]
    if decision.reason in {REASON_STALE, REASON_FUTURE}:
        return [GateReason.STALE_PRINT]
    return [GateReason.STALE_PRINT]


def evaluate_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    reasons: list[GateReason] = []
    live = ctx.mode == OperatingMode.LIVE

    if candidate.from_websocket and live:
        reasons.append(GateReason.WS_DIRECT_LIVE_FORBIDDEN)

    if ctx.mode == OperatingMode.SIGNALS_ONLY:
        reasons.append(GateReason.SIGNALS_ONLY)

    if live and not ctx.live_explicitly_enabled:
        reasons.append(GateReason.LIVE_NOT_ENABLED)

    reasons.extend(_live_print_reasons(candidate, ctx, live=live))

    if candidate.quantity != 1:
        reasons.append(GateReason.QUANTITY_NOT_ONE)

    sit, already_run, first_red, session_reasons = _derived_session_flags(
        candidate, ctx.session_facts, live=live
    )
    reasons.extend(session_reasons)
    if sit < 2 and not candidate.must_trade_small:
        reasons.append(GateReason.SIT2_INCOMPLETE)
    if candidate.must_trade_small:
        reasons.append(GateReason.MUST_TRADE_SMALL_EXCEPTION)
    if already_run:
        reasons.append(GateReason.ALREADY_RUN)
    if first_red:
        reasons.append(GateReason.FIRST_RED)

    quote_reasons = validate_candidate_quote(
        candidate,
        ctx.quote,
        ctx.now,
        live=live,
        max_age_seconds=ctx.max_quote_age_seconds,
        max_spread=ctx.max_quote_spread,
        max_spread_frac=ctx.max_quote_spread_frac,
        matching_ask_tolerance=ctx.matching_ask_tolerance,
    )
    reasons.extend(quote_reasons)

    if is_stale(candidate.created_ts, ctx.now, candidate.ttl_seconds):
        reasons.append(GateReason.TTL_EXPIRED)

    delta = abs(candidate.proposed_limit - ctx.quote.ask)
    if delta > ctx.matching_ask_tolerance:
        reasons.append(GateReason.MATCHING_ASK_FAILED)

    if (
        candidate.must_trade_small
        and not candidate.committed_i2
        and (
            ctx.quote.ask > MUST_TRADE_SMALL_ASK_CAP
            or candidate.proposed_limit > MUST_TRADE_SMALL_ASK_CAP
        )
    ):
        reasons.append(GateReason.ASK_ABOVE_SMALL_BAND)

    occ = normalize_occ(candidate.option_symbol)
    working = _normalized_set(ctx.account.working_option_symbols)
    open_pos = _normalized_set(ctx.account.open_position_symbols)
    if occ in working:
        reasons.append(GateReason.DUPLICATE_OR_WORKING)
    if occ in open_pos:
        reasons.append(GateReason.IN_POSITION)
        if GateReason.DUPLICATE_OR_WORKING not in reasons:
            reasons.append(GateReason.DUPLICATE_OR_WORKING)

    premium = ctx.quote.ask * CONTRACT_MULTIPLIER * Decimal(candidate.quantity)
    equity = ctx.account.equity_for_reserve()
    if ctx.account.cash < premium and ctx.account.buying_power < premium:
        reasons.append(GateReason.INSUFFICIENT_CASH)
    if breaches_cash_floor(
        ctx.account.cash,
        equity,
        premium,
        floor=ctx.cash_equity_floor,
        max_deploy=ctx.max_deploy_ratio,
    ):
        if GateReason.INSUFFICIENT_CASH not in reasons:
            reasons.append(GateReason.CASH_RESERVE)

    if ctx.clock.state != MarketState.OPEN:
        reasons.append(GateReason.MARKET_CLOSED)

    if ctx.cash_up_enforced and past_entry_cutoff(ctx.now):
        reasons.append(GateReason.ENTRY_CUTOFF)
        reasons.append(GateReason.PAST_CASH_UP)
        # Overnight longs are allowed. Do not emit OVERNIGHT_FORBIDDEN.

    if ctx.mode in (OperatingMode.PAPER, OperatingMode.LIVE) and not ctx.preview_ok:
        reasons.append(GateReason.PREVIEW_REQUIRED)

    # Deduplicate while preserving order.
    seen: set[GateReason] = set()
    unique: list[GateReason] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    reasons = unique

    blocking = [r for r in reasons if r not in _INFORMATIONAL_REASONS]
    allowed = not blocking
    if allowed and not reasons:
        note = "pass"
        out_reasons = [GateReason.OK]
    else:
        note = ",".join(r.value for r in reasons)
        out_reasons = reasons
    return GateResult(
        allowed=allowed,
        reasons=out_reasons,
        signal_id=candidate.signal_id,
        mode=ctx.mode,
        note=note,
    )
