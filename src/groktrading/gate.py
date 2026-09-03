"""Deterministic live/paper gate.

WebSocket events never directly trigger live orders. The gate rechecks a
fresh Tradier option quote and TTL, matching ask, buying power/cash,
quantity exactly 1, duplicate/working orders, market hours, and 12:30 PT
cash-up. Fail closed.
"""

from __future__ import annotations

from decimal import Decimal

from groktrading.models import (
    Candidate,
    GateContext,
    GateReason,
    GateResult,
    MarketState,
)
from groktrading.modes import OperatingMode
from groktrading.timeutil import is_stale, past_cash_up, quote_age_seconds

CONTRACT_MULTIPLIER = Decimal("100")


def evaluate_gate(candidate: Candidate, ctx: GateContext) -> GateResult:
    reasons: list[GateReason] = []

    if candidate.from_websocket and ctx.mode == OperatingMode.LIVE:
        reasons.append(GateReason.WS_DIRECT_LIVE_FORBIDDEN)

    if ctx.mode == OperatingMode.SIGNALS_ONLY:
        reasons.append(GateReason.SIGNALS_ONLY)

    if ctx.mode == OperatingMode.LIVE and not ctx.live_explicitly_enabled:
        reasons.append(GateReason.LIVE_NOT_ENABLED)

    if candidate.quantity != 1:
        reasons.append(GateReason.QUANTITY_NOT_ONE)

    if candidate.sit_confirmations < 2:
        reasons.append(GateReason.SIT2_INCOMPLETE)

    if candidate.already_run:
        reasons.append(GateReason.ALREADY_RUN)

    if candidate.is_first_red:
        reasons.append(GateReason.FIRST_RED)

    quote = ctx.quote
    age = quote_age_seconds(quote.quote_ts, ctx.now)
    if is_stale(quote.quote_ts, ctx.now, ctx.max_quote_age_seconds):
        reasons.append(GateReason.STALE_QUOTE)
    if is_stale(candidate.created_ts, ctx.now, candidate.ttl_seconds):
        reasons.append(GateReason.TTL_EXPIRED)
    if age < 0:
        reasons.append(GateReason.STALE_QUOTE)

    delta = abs(candidate.proposed_limit - quote.ask)
    if delta > ctx.matching_ask_tolerance:
        reasons.append(GateReason.MATCHING_ASK_FAILED)

    occ = candidate.option_symbol
    if occ in ctx.account.working_option_symbols:
        reasons.append(GateReason.DUPLICATE_OR_WORKING)

    premium = quote.ask * CONTRACT_MULTIPLIER * Decimal(candidate.quantity)
    if ctx.account.cash < premium and ctx.account.buying_power < premium:
        reasons.append(GateReason.INSUFFICIENT_CASH)

    if ctx.clock.state != MarketState.OPEN:
        reasons.append(GateReason.MARKET_CLOSED)

    if ctx.cash_up_enforced and past_cash_up(ctx.now):
        reasons.append(GateReason.PAST_CASH_UP)
        reasons.append(GateReason.OVERNIGHT_FORBIDDEN)

    if ctx.mode in (OperatingMode.PAPER, OperatingMode.LIVE) and not ctx.preview_ok:
        reasons.append(GateReason.PREVIEW_REQUIRED)

    allowed = not reasons
    note = "pass" if allowed else ",".join(r.value for r in reasons)
    return GateResult(
        allowed=allowed,
        reasons=reasons or [GateReason.OK],
        signal_id=candidate.signal_id,
        mode=ctx.mode,
        note=note,
    )
