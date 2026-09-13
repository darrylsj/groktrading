"""Fail-closed Tradier one-lot submit/close policy.

Grok Bot (Helsinki host) hot-patched this on the box only; GitHub ``main``
was BTO-only at submit, so ``close_with_audit`` reused entry submit and
could not STC. This module is the in-repo equivalent.

Never POSTs. Builds a Tradier form + audit record. The operator / Bot
must still call a separate HTTP client.

Entry (``intent=entry`` / ``buy_to_open``):
  - thesis required
  - 12:30 PT new-entry cutoff
  - cash debit check (limit × 100 × qty) when cash is provided
  - credit / ``sell_to_open`` banned by **exact** side and strategy
    (not a free-text substring scan — that false-positives on STC)
  - tag alphanumeric (Tradier)

Exit (``take_gain_exit`` and other exit strategies):
  - ``sell_to_close`` / ``buy_to_close`` allowed
  - skip 12:30 cutoff and cash debit
  - thesis required (refuse STC without one)
  - cannot be reused as a BTO re-entry
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from groktrading.quote_gate import normalize_occ
from groktrading.timeutil import UTC, as_utc, past_entry_cutoff, session_date_pt
from tools.live_order_gate.carry import (
    carry_fields_from_mapping,
    carry_gate_document,
    overnight_carry_notes_required,
    parse_carry_dte,
    parse_carry_text,
    parse_overnight_carry,
    resolve_falsifier,
    stamp_thesis_artifacts,
    validate_carry_fields,
)

Side = Literal["buy_to_open", "sell_to_close", "buy_to_close"]
Intent = Literal["entry", "exit"]

ENTRY_SIDES: frozenset[str] = frozenset({"buy_to_open"})
EXIT_SIDES: frozenset[str] = frozenset({"sell_to_close", "buy_to_close"})
ALLOWED_SIDES: frozenset[str] = ENTRY_SIDES | EXIT_SIDES

# Exact names only. Do not substring-match thesis text ("do not sell credit").
BANNED_ENTRY_SIDES: frozenset[str] = frozenset(
    {"sell_to_open", "sell", "credit", "credit_spread", "sto"}
)
BANNED_ENTRY_STRATEGIES: frozenset[str] = frozenset(
    {
        "credit",
        "credit_spread",
        "short_put",
        "short_call",
        "iron_condor",
        "sell_to_open",
        "sto",
        "naked_short",
        "credit_put",
        "credit_call",
    }
)

EXIT_STRATEGIES: frozenset[str] = frozenset(
    {
        "take_gain_exit",
        "dead_thesis_exit",
        "falsifier_exit",
        "stop_exit",
        "manual_exit",
        "time_stop_exit",
    }
)

ENTRY_STRATEGIES: frozenset[str] = frozenset(
    {
        "must_trade_small",
        "sit2",
        "i1",
        "i2",
        "discretionary_entry",
    }
)

TAG_RE = re.compile(r"^[A-Za-z0-9]+$")
CONTRACT_MULTIPLIER = Decimal("100")
# Entry thesis must be same PT session and not older than this. Exits skip.
DEFAULT_ENTRY_THESIS_MAX_AGE_SEC = 8 * 3600.0
DEFAULT_QTY = 1


class PolicyError(ValueError):
    """Fail-closed live_order_gate reject. ``code`` is the stable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class Thesis:
    signal_id: str
    option_symbol: str
    side: str
    quantity: int
    limit: Decimal
    strategy: str
    thesis: str
    written_at: datetime
    intent: Intent
    tag: str
    underlying: str = ""
    parent_signal_id: str | None = None
    falsifier: str | None = None
    duration: str = "day"
    order_type: str = "limit"
    option_class: str = "option"
    overnight_carry: bool | None = None
    carry_dte: str | int | None = None
    carry_event_risk: str | None = None
    carry_rationale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "option_symbol": self.option_symbol,
            "side": self.side,
            "quantity": self.quantity,
            "limit": str(self.limit),
            "strategy": self.strategy,
            "thesis": self.thesis,
            "written_at": _iso(self.written_at),
            "intent": self.intent,
            "tag": self.tag,
            "underlying": self.underlying,
            "parent_signal_id": self.parent_signal_id,
            "falsifier": self.falsifier,
            "how_it_dies": self.falsifier,
            "duration": self.duration,
            "order_type": self.order_type,
            "option_class": self.option_class,
            "overnight_carry": self.overnight_carry,
            "carry_dte": self.carry_dte,
            "carry_event_risk": self.carry_event_risk,
            "carry_rationale": self.carry_rationale,
        }

    def carry_gate(self) -> dict[str, Any]:
        return carry_gate_document(
            overnight_carry=self.overnight_carry,
            carry_dte=self.carry_dte,
            carry_event_risk=self.carry_event_risk,
            carry_rationale=self.carry_rationale,
        )


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...]
    intent: Intent
    form: dict[str, str] | None
    thesis: Thesis | None
    note: str


def _iso(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _norm_strategy(value: object) -> str:
    return str(value or "").strip().lower()


def is_exit_strategy(strategy: object) -> bool:
    """True for take_gain_exit and the other named exit strategies."""
    return _norm_strategy(strategy) in EXIT_STRATEGIES


def is_alphanumeric_tag(tag: object) -> bool:
    text = str(tag or "").strip()
    return bool(text) and TAG_RE.fullmatch(text) is not None


def infer_intent(side: str, strategy: str, intent: object | None) -> Intent:
    if intent in {"entry", "exit"}:
        return intent
    if is_exit_strategy(strategy) or side in EXIT_SIDES:
        return "exit"
    return "entry"


def thesis_from_mapping(raw: Mapping[str, Any]) -> Thesis:
    if not raw:
        raise PolicyError("thesis_required", "thesis mapping is empty")
    signal_id = str(raw.get("signal_id") or "").strip()
    if not signal_id:
        raise PolicyError("signal_id_required")
    option_symbol = normalize_occ(str(raw.get("option_symbol") or raw.get("occ") or ""))
    if not option_symbol:
        raise PolicyError("option_symbol_required")
    side = str(raw.get("side") or "").strip().lower()
    if not side:
        raise PolicyError("side_required")
    strategy = _norm_strategy(raw.get("strategy"))
    if not strategy:
        raise PolicyError("strategy_required")
    intent = infer_intent(side, strategy, raw.get("intent"))
    tag = str(raw.get("tag") or signal_id).strip()
    written = _parse_dt(raw.get("written_at"))
    if written is None:
        raise PolicyError("written_at_required", "thesis.written_at must be timezone-aware ISO")
    qty_raw = raw.get("quantity", DEFAULT_QTY)
    try:
        quantity = int(qty_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PolicyError("quantity_not_one") from None
    limit = _parse_decimal(raw.get("limit") or raw.get("price") or raw.get("proposed_limit"))
    if limit is None:
        raise PolicyError("limit_required")
    parent = raw.get("parent_signal_id")
    parent_id = str(parent).strip() if parent not in (None, "") else None
    thesis_text = str(raw.get("thesis") or raw.get("note") or "")
    falsifier_raw = raw.get("falsifier") if raw.get("falsifier") not in (None, "") else raw.get(
        "how_it_dies"
    )
    carry = carry_fields_from_mapping(raw)
    if carry.get("error"):
        raise PolicyError(str(carry["error"]))
    return Thesis(
        signal_id=signal_id,
        option_symbol=option_symbol,
        side=side,
        quantity=quantity,
        limit=limit,
        strategy=strategy,
        thesis=thesis_text,
        written_at=written,
        intent=intent,
        tag=tag,
        underlying=str(raw.get("underlying") or "").strip().upper(),
        parent_signal_id=parent_id,
        falsifier=str(falsifier_raw).strip() if falsifier_raw else None,
        duration=str(raw.get("duration") or "day").strip().lower(),
        order_type=str(raw.get("order_type") or raw.get("type") or "limit").strip().lower(),
        option_class=str(raw.get("option_class") or raw.get("class") or "option").strip().lower(),
        overnight_carry=carry.get("overnight_carry"),  # type: ignore[arg-type]
        carry_dte=carry.get("carry_dte"),  # type: ignore[arg-type]
        carry_event_risk=carry.get("carry_event_risk"),  # type: ignore[arg-type]
        carry_rationale=carry.get("carry_rationale"),  # type: ignore[arg-type]
    )


def load_thesis(path: Path | str) -> Thesis:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise PolicyError("thesis_required", "thesis file must be a JSON object")
    return thesis_from_mapping(doc)


def write_thesis(
    *,
    signal_id: str,
    option_symbol: str,
    side: str,
    limit: Decimal | str | float,
    strategy: str,
    thesis: str,
    written_at: datetime,
    intent: Intent | None = None,
    tag: str | None = None,
    quantity: int = DEFAULT_QTY,
    underlying: str = "",
    parent_signal_id: str | None = None,
    falsifier: str | None = None,
    how_it_dies: str | None = None,
    overnight_carry: bool | None = None,
    carry_dte: str | int | None = None,
    carry_event_risk: str | None = None,
    carry_rationale: str | None = None,
    require_overnight_carry: bool = False,
    path: Path | str | None = None,
    receipt_path: Path | str | None = None,
    evidence_path: Path | str | None = None,
    thinking_path: Path | str | None = None,
) -> Thesis:
    """Write a thesis. Exit sides are allowed; credit ban is structural, not text.

    ``how_it_dies`` / ``falsifier`` is required. Overnight carry notes are soft
    unless ``overnight_carry`` or ``require_overnight_carry`` is true. Does not
    auto-flatten, change the cash floor, or lift the credit/STO ban.
    """
    falsifier_text, falsifier_err = resolve_falsifier(falsifier, how_it_dies)
    if falsifier_err:
        raise PolicyError(
            falsifier_err,
            "how_it_dies / falsifier required on every thesis"
            if falsifier_err == "falsifier_required"
            else falsifier_err,
        )
    carry_flag, carry_flag_err = parse_overnight_carry(overnight_carry)
    if carry_flag_err:
        raise PolicyError(carry_flag_err)
    if overnight_carry_notes_required(
        carry_flag, require_overnight_carry=require_overnight_carry
    ):
        carry_flag = True
    dte, dte_err = parse_carry_dte(carry_dte)
    if dte_err:
        raise PolicyError(dte_err)
    event_risk = parse_carry_text(carry_event_risk)
    rationale = parse_carry_text(carry_rationale)
    carry_err = validate_carry_fields(
        overnight_carry=carry_flag,
        carry_dte=dte,
        carry_event_risk=event_risk,
        carry_rationale=rationale,
        require_overnight_carry=require_overnight_carry,
    )
    if carry_err:
        raise PolicyError(carry_err)
    raw: dict[str, Any] = {
        "signal_id": signal_id,
        "option_symbol": option_symbol,
        "side": side,
        "quantity": quantity,
        "limit": str(limit),
        "strategy": strategy,
        "thesis": thesis,
        "written_at": _iso(written_at),
        "tag": tag or signal_id,
        "underlying": underlying,
        "parent_signal_id": parent_signal_id,
        "falsifier": falsifier_text,
        "how_it_dies": falsifier_text,
        "overnight_carry": carry_flag,
        "carry_dte": dte,
        "carry_event_risk": event_risk,
        "carry_rationale": rationale,
    }
    if intent is not None:
        raw["intent"] = intent
    built = thesis_from_mapping(raw)
    _assert_credit_ban(built)
    _assert_tag(built)
    if built.quantity != DEFAULT_QTY:
        raise PolicyError("quantity_not_one")
    if path is not None:
        Path(path).write_text(
            json.dumps(built.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if receipt_path or evidence_path or thinking_path:
        stamp_thesis_artifacts(
            built.to_dict(),
            carry=built.carry_gate(),
            receipt_path=receipt_path,
            evidence_path=evidence_path,
            thinking_path=thinking_path,
            now=written_at,
        )
    return built


def build_tradier_form_from_thesis(
    thesis: Thesis | Mapping[str, Any],
    *,
    preview: bool = True,
) -> dict[str, str]:
    """Exact Tradier form body. ``preview`` is the only submit-time mutation."""
    ticket = thesis if isinstance(thesis, Thesis) else thesis_from_mapping(thesis)
    if ticket.side not in ALLOWED_SIDES:
        raise PolicyError("side_not_allowed", f"side {ticket.side!r} is not BTO/STC/BTC")
    if ticket.option_class != "option":
        raise PolicyError("class_not_option")
    if ticket.order_type != "limit":
        raise PolicyError("type_not_limit")
    if ticket.duration != "day":
        raise PolicyError("duration_not_day")
    return {
        "class": ticket.option_class,
        "symbol": ticket.option_symbol,
        "option_symbol": ticket.option_symbol,
        "side": ticket.side,
        "quantity": str(ticket.quantity),
        "type": ticket.order_type,
        "duration": ticket.duration,
        "price": str(ticket.limit),
        "tag": ticket.tag,
        "preview": "true" if preview else "false",
    }


def _assert_tag(thesis: Thesis) -> None:
    if not is_alphanumeric_tag(thesis.tag):
        raise PolicyError(
            "tag_not_alphanumeric",
            "Tradier tag must be A-Za-z0-9 only (no hyphen/underscore)",
        )


def _assert_credit_ban(thesis: Thesis) -> None:
    """Exact side/strategy only. Thesis prose is never scanned for 'credit'/'sell'."""
    if thesis.intent == "exit":
        return
    if thesis.side in BANNED_ENTRY_SIDES or thesis.side not in ENTRY_SIDES:
        raise PolicyError("credit_or_sto_banned", f"entry side {thesis.side!r} is banned")
    if thesis.strategy in BANNED_ENTRY_STRATEGIES:
        raise PolicyError(
            "credit_or_sto_banned",
            f"entry strategy {thesis.strategy!r} is banned",
        )


def _assert_common(thesis: Thesis, now: datetime) -> None:
    _assert_tag(thesis)
    if thesis.quantity != DEFAULT_QTY:
        raise PolicyError("quantity_not_one")
    if thesis.order_type != "limit" or thesis.duration != "day" or thesis.option_class != "option":
        raise PolicyError("form_shape_invalid")
    written = thesis.written_at
    if is_future_written(written, now):
        raise PolicyError("thesis_future_written_at")


def is_future_written(written_at: datetime, now: datetime, slack_seconds: float = 2.0) -> bool:
    return (as_utc(written_at) - as_utc(now)).total_seconds() > slack_seconds


def _entry_thesis_stale(
    thesis: Thesis,
    now: datetime,
    *,
    max_age_sec: float = DEFAULT_ENTRY_THESIS_MAX_AGE_SEC,
) -> str | None:
    if session_date_pt(thesis.written_at) != session_date_pt(now):
        return "thesis_prior_session"
    age = (as_utc(now) - as_utc(thesis.written_at)).total_seconds()
    if age > max_age_sec:
        return "thesis_ttl_expired"
    return None


def evaluate_submit_policy(
    thesis: Thesis | Mapping[str, Any] | None,
    *,
    now: datetime,
    cash: Decimal | None = None,
    closed_signal_ids: frozenset[str] | set[str] | None = None,
    max_age_sec: float = DEFAULT_ENTRY_THESIS_MAX_AGE_SEC,
    preview: bool = True,
) -> PolicyDecision:
    """BTO entry policy. Fail-closed. Exits must use evaluate_close_policy."""
    reasons: list[str] = []
    ticket: Thesis | None = None
    if thesis is None:
        reasons.append("thesis_required")
        return PolicyDecision(False, tuple(reasons), "entry", None, None, ",".join(reasons))
    try:
        ticket = thesis if isinstance(thesis, Thesis) else thesis_from_mapping(thesis)
        _assert_common(ticket, now)
        if ticket.intent != "entry" or is_exit_strategy(ticket.strategy):
            raise PolicyError("exit_thesis_not_for_submit")
        if ticket.side not in ENTRY_SIDES:
            raise PolicyError("entry_side_must_be_bto")
        _assert_credit_ban(ticket)
        stale = _entry_thesis_stale(ticket, now, max_age_sec=max_age_sec)
        if stale:
            raise PolicyError(stale)
        if past_entry_cutoff(now):
            raise PolicyError("entry_cutoff")
        if cash is None:
            raise PolicyError("cash_required")
        premium = ticket.limit * CONTRACT_MULTIPLIER * Decimal(ticket.quantity)
        if cash < premium:
            raise PolicyError("insufficient_cash")
        closed = closed_signal_ids or ()
        if ticket.signal_id in closed:
            raise PolicyError("reentry_same_signal")
        form = build_tradier_form_from_thesis(ticket, preview=preview)
    except PolicyError as exc:
        reasons.append(exc.code)
        return PolicyDecision(False, tuple(reasons), "entry", None, ticket, ",".join(reasons))
    return PolicyDecision(True, (), "entry", form, ticket, "ok")


def assert_submit_policy(
    thesis: Thesis | Mapping[str, Any] | None,
    *,
    now: datetime,
    cash: Decimal | None = None,
    closed_signal_ids: frozenset[str] | set[str] | None = None,
    max_age_sec: float = DEFAULT_ENTRY_THESIS_MAX_AGE_SEC,
    preview: bool = True,
) -> dict[str, str]:
    decision = evaluate_submit_policy(
        thesis,
        now=now,
        cash=cash,
        closed_signal_ids=closed_signal_ids,
        max_age_sec=max_age_sec,
        preview=preview,
    )
    if not decision.allowed or decision.form is None:
        raise PolicyError(decision.reasons[0] if decision.reasons else "submit_refused")
    return decision.form


def evaluate_close_policy(
    thesis: Thesis | Mapping[str, Any] | None,
    *,
    now: datetime,
    form: Mapping[str, Any] | None = None,
    closed_signal_ids: frozenset[str] | set[str] | None = None,
    preview: bool = True,
) -> PolicyDecision:
    """STC/BTC exit policy. Skips 12:30 cutoff and cash debit. Thesis required."""
    reasons: list[str] = []
    ticket: Thesis | None = None
    if thesis is None:
        reasons.append("thesis_required")
        return PolicyDecision(False, tuple(reasons), "exit", None, None, ",".join(reasons))
    try:
        ticket = thesis if isinstance(thesis, Thesis) else thesis_from_mapping(thesis)
        _assert_common(ticket, now)
        if ticket.intent != "exit" and not is_exit_strategy(ticket.strategy):
            raise PolicyError("exit_strategy_required")
        if not is_exit_strategy(ticket.strategy):
            raise PolicyError("exit_strategy_required")
        if ticket.side not in EXIT_SIDES:
            raise PolicyError("exit_side_must_be_stc_or_btc")
        if ticket.side in BANNED_ENTRY_SIDES:
            raise PolicyError("credit_or_sto_banned")
        if not ticket.parent_signal_id:
            raise PolicyError("parent_signal_id_required")
        closed = set(closed_signal_ids or ())
        if ticket.signal_id in closed or ticket.parent_signal_id in closed:
            raise PolicyError("already_closed")
        built = build_tradier_form_from_thesis(ticket, preview=preview)
        if form is not None:
            _assert_form_matches_thesis(form, built)
    except PolicyError as exc:
        reasons.append(exc.code)
        return PolicyDecision(False, tuple(reasons), "exit", None, ticket, ",".join(reasons))
    return PolicyDecision(True, (), "exit", built, ticket, "ok")


def _assert_form_matches_thesis(form: Mapping[str, Any], expected: Mapping[str, str]) -> None:
    for key in ("class", "option_symbol", "side", "quantity", "type", "duration", "price", "tag"):
        got = str(form.get(key) if form.get(key) is not None else form.get("symbol") or "")
        if key == "option_symbol":
            got = normalize_occ(str(form.get("option_symbol") or form.get("symbol") or ""))
        want = expected[key]
        if key == "price":
            got_dec = _parse_decimal(form.get("price") or form.get("limit"))
            want_dec = _parse_decimal(want)
            if got_dec != want_dec:
                raise PolicyError("form_thesis_mismatch")
            continue
        if got != want:
            raise PolicyError("form_thesis_mismatch")


def assert_close_policy(
    thesis: Thesis | Mapping[str, Any] | None,
    *,
    now: datetime,
    form: Mapping[str, Any] | None = None,
    closed_signal_ids: frozenset[str] | set[str] | None = None,
    preview: bool = True,
) -> dict[str, str]:
    decision = evaluate_close_policy(
        thesis,
        now=now,
        form=form,
        closed_signal_ids=closed_signal_ids,
        preview=preview,
    )
    if not decision.allowed or decision.form is None:
        raise PolicyError(decision.reasons[0] if decision.reasons else "close_refused")
    return decision.form


def close_with_audit(
    thesis: Thesis | Mapping[str, Any] | None,
    *,
    now: datetime,
    form: Mapping[str, Any] | None = None,
    closed_signal_ids: frozenset[str] | set[str] | None = None,
    preview: bool = True,
) -> dict[str, Any]:
    """Build (or validate) an STC form from the exit thesis. Does not POST."""
    decision = evaluate_close_policy(
        thesis,
        now=now,
        form=form,
        closed_signal_ids=closed_signal_ids,
        preview=preview,
    )
    audit = {
        "kind": "live_order_gate_close",
        "allowed": decision.allowed,
        "reasons": list(decision.reasons),
        "intent": decision.intent,
        "note": decision.note,
        "places_orders": False,
        "dry_run": True,
        "skipped_entry_cutoff": True,
        "skipped_cash_debit": True,
        "form": decision.form,
        "thesis": decision.thesis.to_dict() if decision.thesis is not None else None,
        "now": _iso(now),
    }
    if not decision.allowed:
        raise PolicyError(decision.reasons[0] if decision.reasons else "close_refused")
    return audit


def decision_document(decision: PolicyDecision, *, now: datetime, command: str) -> dict[str, Any]:
    return {
        "kind": f"live_order_gate_{command}",
        "allowed": decision.allowed,
        "reasons": list(decision.reasons),
        "intent": decision.intent,
        "note": decision.note,
        "places_orders": False,
        "dry_run": True,
        "form": decision.form,
        "thesis": decision.thesis.to_dict() if decision.thesis is not None else None,
        "now": _iso(now),
    }
