"""Thin ranker (plane 2): no LLM. Rate-limit candidates, not the tape.

Helsinki hot sensors keep writing the ledger/tape continuously. This module
selects ≤1–3 OCCs that already pass deterministic filters and writes
schema-stable ``shortlist.json`` for Continual15 to pull. It does **not**
wake Grok per print, does **not** emit ``sit_match``, and does **not**
place orders.

Print freshness is UW ``executed_at`` age ≤ ``SIT_MATCH_MAX_AGE_SEC``
(default 60s, I1). Do **not** raise that cap to match
``SIT_MATCH_MIN_INTERVAL_SEC`` (Cursor wake bandage, host often 300s).
Optional lift tighten: ``SHORTLIST_MAX_AGE_SEC`` in 15–30s. A configured
age above the I1 cap is clamped down (never widened).

Host path (ops fact, not a deploy claim):
``/opt/trading-desk/state/shortlist.json``. Cadence 5–15s (default 10).
``live_tape.json`` shape is host-owned and not in this tree — inputs are a
JSON list of UW-like rows, optional tape keys, or ``flow_ledger``.
Offline skeleton writes an empty document when no input exists.

Hunt prefers ``SIT_MATCH_WEBHOOK`` off. Merge ≠ Helsinki restart.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from groktrading.cadence import CadenceError, clamp_seconds, env_seconds
from groktrading.io_atomic import write_json_atomic
from groktrading.policy import MUST_TRADE_SMALL_ASK_CAP
from groktrading.quote_gate import normalize_occ
from groktrading.sit_match import (
    DEFAULT_SIT_MATCH_MAX_AGE_SEC,
    evaluate_sit_match_freshness,
    executed_at_iso,
    extract_executed_at,
    extract_occ,
    parse_executed_at,
    resolve_sit_match_max_age,
    sit_match_max_age_sec,
    sit_match_occ_key,
)
from groktrading.timeutil import UTC, as_utc, quote_age_seconds

SCHEMA_ID = "groktrading.shortlist.v1"
SHORTLIST_KIND = "shortlist"
HOST_SHORTLIST_PATH = "/opt/trading-desk/state/shortlist.json"
DEFAULT_SHORTLIST_PATH = "shortlist.json"
DEFAULT_CADENCE_SEC = 10.0
CADENCE_LO_SEC = 5.0
CADENCE_HI_SEC = 15.0
DEFAULT_STALE_SEC = 30.0
MAX_CANDIDATES = 3
# Documented I1 cheap band (policy / profitability audit). Not invented fills.
PREMIUM_BAND_LO = Decimal("0.80")
PREMIUM_BAND_HI = MUST_TRADE_SMALL_ASK_CAP
HARD_SKIP_UNDERLYINGS: frozenset[str] = frozenset({"META", "NET", "MU", "AMD"})
NO_REOPEN_UNDERLYINGS: frozenset[str] = frozenset({"SPCX"})
INTC_PUT_UNDERLYING = "INTC"
LIFT_TIGHTEN_AGE_LO_SEC = 15.0
LIFT_TIGHTEN_AGE_HI_SEC = 30.0

SHORTLIST_MAX_AGE_ENV = "SHORTLIST_MAX_AGE_SEC"
SHORTLIST_CADENCE_ENV = "SHORTLIST_CADENCE_SEC"
SHORTLIST_STALE_ENV = "SHORTLIST_STALE_SEC"
SHORTLIST_PATH_ENV = "SHORTLIST_PATH"

REASON_STALE_SHORTLIST = "shortlist_stale"
REASON_EMPTY = "shortlist_empty"
REASON_MISSING_RANKED_AT = "shortlist_missing_ranked_at"
REASON_UNPARSEABLE_RANKED_AT = "shortlist_unparseable_ranked_at"
REASON_SCHEMA = "shortlist_schema"
REASON_IN_POSITION_CLEARED = "shortlist_in_position_cleared"
REASON_INVALID_STALE_LIMIT = "shortlist_invalid_stale_limit"

SKIP_MISSING_EXECUTED_AT = "missing_executed_at"
SKIP_UNPARSEABLE_EXECUTED_AT = "unparseable_executed_at"
SKIP_STALE_PRINT = "stale_print"
SKIP_FUTURE = "future_executed_at"
SKIP_INVALID_MAX_AGE = "invalid_max_age"
SKIP_MISSING_OCC = "missing_occ"
SKIP_MISSING_UNDERLYING = "missing_underlying"
SKIP_HARD = "hard_skip_underlying"
SKIP_SPCX = "spcx_reopen"
SKIP_INTC_PUT = "intc_put"
SKIP_PREMIUM = "premium_out_of_band"
SKIP_UNPARSEABLE_PREMIUM = "unparseable_premium"
SKIP_ALREADY_RUN = "already_run"
SKIP_IN_POSITION = "in_position"

# Per-share ask/print only. UW dollar ``premium`` is notional (often ≥10k).
_PREMIUM_KEYS: tuple[str, ...] = ("nbbo_ask", "ask", "print", "price")
_OCC_RIGHT = re.compile(r"^([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})$")
_TAPE_LIST_KEYS: tuple[str, ...] = (
    "prints",
    "option_trades",
    "rows",
    "tape",
    "candidates",
    "items",
    "data",
    "flow",
)
EmptyReason = Literal["no_input", "no_fresh_prints", "all_filtered"] | None


@dataclass(frozen=True)
class SessionFilters:
    """Already-run / in-position when the caller can detect them.

    Missing filters are not invented: undetectable already-run does not skip.
    """

    already_run_underlyings: frozenset[str] = frozenset()
    already_run_occs: frozenset[str] = frozenset()
    in_position_underlyings: frozenset[str] = frozenset()
    in_position_occs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ShortlistCandidate:
    occ: str
    underlying: str
    option_type: Literal["call", "put"]
    executed_at: str
    print_age_sec: float
    premium: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "occ": self.occ,
            "underlying": self.underlying,
            "option_type": self.option_type,
            "executed_at": self.executed_at,
            "print_age_sec": self.print_age_sec,
            "premium": self.premium,
            "source": self.source,
        }


@dataclass
class ShortlistDocument:
    ranked_at: datetime
    max_print_age_sec: float
    cadence_sec: float
    candidates: list[ShortlistCandidate] = field(default_factory=list)
    skipped_count: int = 0
    skip_tally: dict[str, int] = field(default_factory=dict)
    empty_reason: EmptyReason = None
    premium_lo: Decimal = PREMIUM_BAND_LO
    premium_hi: Decimal = PREMIUM_BAND_HI
    max_candidates: int = MAX_CANDIDATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_ID,
            "kind": SHORTLIST_KIND,
            "ranked_at": executed_at_iso(self.ranked_at),
            "max_print_age_sec": self.max_print_age_sec,
            "cadence_sec": self.cadence_sec,
            "max_candidates": self.max_candidates,
            "premium_lo": format(self.premium_lo, "f"),
            "premium_hi": format(self.premium_hi, "f"),
            "emit_sit_match": False,
            "candidates": [row.as_dict() for row in self.candidates],
            "skipped_count": self.skipped_count,
            "skip_tally": dict(sorted(self.skip_tally.items())),
            "empty_reason": self.empty_reason,
        }


@dataclass(frozen=True)
class ShortlistConsume:
    """Continual15 pull gate. Stale / empty / schema-bad → do not hunt."""

    allow: bool
    reason: str | None
    ranked_at: datetime | None
    age_seconds: float | None
    candidates: tuple[ShortlistCandidate, ...]
    stale_limit_sec: float | None


def _finite_positive(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def shortlist_cadence_sec(env: Mapping[str, str] | None = None) -> float:
    """Timer cadence. Documented window 5–15s. Default 10. Out of range clamps."""
    return env_seconds(
        env,
        SHORTLIST_CADENCE_ENV,
        default=DEFAULT_CADENCE_SEC,
        lo=CADENCE_LO_SEC,
        hi=CADENCE_HI_SEC,
    )


def shortlist_stale_sec(
    env: Mapping[str, str] | None = None,
    *,
    cadence_sec: float | None = None,
) -> float | None:
    """Document freshness for Continual15. Default 30s (~2–3 cadences).

    This is **not** print age and must not be raised to 300s to match
    ``SIT_MATCH_MIN_INTERVAL_SEC``.
    """
    source = os.environ if env is None else env
    raw = source.get(SHORTLIST_STALE_ENV)
    if raw is None or str(raw).strip() == "":
        cadence = cadence_sec if cadence_sec is not None else shortlist_cadence_sec(env)
        return max(DEFAULT_STALE_SEC, 2.0 * cadence)
    return _finite_positive(str(raw).strip())


def shortlist_max_print_age_sec(
    env: Mapping[str, str] | None = None,
    *,
    max_age_sec: float | None = None,
) -> float | None:
    """Print-age cap. Default I1 60s. Optional tighten; never widen past I1."""
    i1 = resolve_sit_match_max_age(env=env)
    if i1 is None:
        return None
    if max_age_sec is not None:
        parsed = _finite_positive(max_age_sec)
    else:
        source = os.environ if env is None else env
        raw = source.get(SHORTLIST_MAX_AGE_ENV)
        if raw is None or str(raw).strip() == "":
            return i1
        parsed = _finite_positive(str(raw).strip())
    if parsed is None:
        return None
    return min(parsed, i1)


def shortlist_output_path(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    raw = source.get(SHORTLIST_PATH_ENV)
    if raw is not None and str(raw).strip():
        return Path(str(raw).strip())
    return Path(DEFAULT_SHORTLIST_PATH)


def parse_premium(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if amount.is_nan() or amount.is_infinite() or amount < 0:
        return None
    return amount


def extract_premium(payload: Mapping[str, Any]) -> Decimal | None:
    """Per-share ask/print. Never UW dollar ``premium`` (notional)."""
    for key in _PREMIUM_KEYS:
        parsed = parse_premium(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def premium_in_band(
    amount: Decimal,
    *,
    lo: Decimal = PREMIUM_BAND_LO,
    hi: Decimal = PREMIUM_BAND_HI,
) -> bool:
    return lo <= amount <= hi


def parse_occ_right(occ: str) -> tuple[str, Literal["call", "put"]] | None:
    match = _OCC_RIGHT.match(normalize_occ(occ))
    if match is None:
        return None
    right: Literal["call", "put"] = "call" if match.group(3) == "C" else "put"
    return match.group(1), right


def extract_underlying(payload: Mapping[str, Any], occ: str | None) -> str | None:
    for key in ("ticker", "underlying", "ticker_symbol"):
        raw = payload.get(key)
        if raw not in (None, ""):
            text = str(raw).strip().upper()
            if text:
                return text
    if occ:
        parsed = parse_occ_right(occ)
        if parsed is not None:
            return parsed[0]
    return None


def extract_option_type(
    payload: Mapping[str, Any], occ: str | None
) -> Literal["call", "put"] | None:
    raw = payload.get("option_type") or payload.get("put_call") or payload.get("type")
    if raw not in (None, ""):
        text = str(raw).strip().lower()
        if text in {"c", "call", "calls"}:
            return "call"
        if text in {"p", "put", "puts"}:
            return "put"
    if occ:
        parsed = parse_occ_right(occ)
        if parsed is not None:
            return parsed[1]
    return None


def extract_source(payload: Mapping[str, Any]) -> str:
    raw = payload.get("source")
    if raw not in (None, ""):
        return str(raw).strip()
    return "option-trades"


def extract_prints(payload: object) -> list[Mapping[str, Any]]:
    """Best-effort print list. Unknown ``live_tape.json`` shapes → empty.

    Host tape schema is not in this git tree. Do not invent rows.
    """
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in _TAPE_LIST_KEYS:
        raw = payload.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return [row for row in raw if isinstance(row, Mapping)]
    if any(
        payload.get(key) not in (None, "")
        for key in ("occ", "option_symbol", "option_chain", "executed_at")
    ):
        return [payload]
    return []


def load_json_object(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _upper_set(values: Sequence[object]) -> frozenset[str]:
    out: set[str] = set()
    for raw in values:
        if raw in (None, ""):
            continue
        text = str(raw).strip().upper()
        if text:
            out.add(text)
    return frozenset(out)


def _occ_set(values: Sequence[object]) -> frozenset[str]:
    out: set[str] = set()
    for raw in values:
        key = sit_match_occ_key(str(raw) if raw not in (None, "") else None)
        if key:
            out.add(key)
    return frozenset(out)


def session_filters_from_mapping(
    already_run: Mapping[str, Any] | Sequence[object] | None = None,
    in_position: Mapping[str, Any] | Sequence[object] | None = None,
) -> SessionFilters:
    already_u: frozenset[str] = frozenset()
    already_o: frozenset[str] = frozenset()
    held_u: frozenset[str] = frozenset()
    held_o: frozenset[str] = frozenset()
    if isinstance(already_run, Sequence) and not isinstance(already_run, (str, bytes)):
        already_o = _occ_set(already_run)
    elif isinstance(already_run, Mapping):
        already_u = _upper_set(
            list(already_run.get("already_run_underlyings") or already_run.get("underlyings") or [])
        )
        already_o = _occ_set(
            list(
                already_run.get("already_run_option_symbols")
                or already_run.get("occs")
                or already_run.get("option_symbols")
                or []
            )
        )
    if isinstance(in_position, Sequence) and not isinstance(in_position, (str, bytes)):
        held_o = _occ_set(in_position)
    elif isinstance(in_position, Mapping):
        held_u = _upper_set(list(in_position.get("underlyings") or []))
        held_o = _occ_set(list(in_position.get("occs") or in_position.get("option_symbols") or []))
    return SessionFilters(
        already_run_underlyings=already_u,
        already_run_occs=already_o,
        in_position_underlyings=held_u,
        in_position_occs=held_o,
    )


def _truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def classify_print(
    payload: Mapping[str, Any],
    now: datetime,
    *,
    max_age_sec: float | None,
    session: SessionFilters | None = None,
    premium_lo: Decimal = PREMIUM_BAND_LO,
    premium_hi: Decimal = PREMIUM_BAND_HI,
) -> tuple[ShortlistCandidate | None, str | None]:
    """Return (candidate, None) or (None, skip_reason)."""
    freshness = evaluate_sit_match_freshness(
        extract_executed_at(payload),
        now,
        max_age_sec=max_age_sec,
    )
    if not freshness.allow:
        reason = freshness.reason or SKIP_STALE_PRINT
        if reason.endswith("missing_executed_at"):
            return None, SKIP_MISSING_EXECUTED_AT
        if reason.endswith("unparseable_executed_at"):
            return None, SKIP_UNPARSEABLE_EXECUTED_AT
        if reason.endswith("future_executed_at"):
            return None, SKIP_FUTURE
        if reason.endswith("invalid_max_age"):
            return None, SKIP_INVALID_MAX_AGE
        return None, SKIP_STALE_PRINT

    occ = sit_match_occ_key(extract_occ(payload))
    if occ is None:
        return None, SKIP_MISSING_OCC
    underlying = extract_underlying(payload, occ)
    if underlying is None:
        return None, SKIP_MISSING_UNDERLYING
    option_type = extract_option_type(payload, occ)
    if option_type is None:
        return None, SKIP_MISSING_OCC

    if underlying in HARD_SKIP_UNDERLYINGS:
        return None, SKIP_HARD
    if underlying in NO_REOPEN_UNDERLYINGS:
        return None, SKIP_SPCX
    if underlying == INTC_PUT_UNDERLYING and option_type == "put":
        return None, SKIP_INTC_PUT

    filters = session or SessionFilters()
    if (
        _truthy_flag(payload.get("already_run"))
        or underlying in filters.already_run_underlyings
        or occ in filters.already_run_occs
    ):
        return None, SKIP_ALREADY_RUN
    if underlying in filters.in_position_underlyings or occ in filters.in_position_occs:
        return None, SKIP_IN_POSITION

    premium = extract_premium(payload)
    if premium is None:
        return None, SKIP_UNPARSEABLE_PREMIUM
    if not premium_in_band(premium, lo=premium_lo, hi=premium_hi):
        return None, SKIP_PREMIUM

    assert freshness.executed_at_iso is not None
    assert freshness.age_seconds is not None
    return (
        ShortlistCandidate(
            occ=occ,
            underlying=underlying,
            option_type=option_type,
            executed_at=freshness.executed_at_iso,
            print_age_sec=freshness.age_seconds,
            premium=format(premium, "f"),
            source=extract_source(payload),
        ),
        None,
    )


def rank_prints(
    prints: Sequence[Mapping[str, Any]],
    now: datetime,
    *,
    max_age_sec: float | None = None,
    cadence_sec: float = DEFAULT_CADENCE_SEC,
    session: SessionFilters | None = None,
    max_candidates: int = MAX_CANDIDATES,
    had_input: bool = True,
    env: Mapping[str, str] | None = None,
) -> ShortlistDocument:
    """Select newest unique OCCs that already pass plane-2 filters."""
    resolved_age = (
        max_age_sec
        if max_age_sec is not None
        else shortlist_max_print_age_sec(env)
    )
    if resolved_age is None:
        resolved_age = sit_match_max_age_sec(env)
    cadence = clamp_seconds(
        cadence_sec, lo=CADENCE_LO_SEC, hi=CADENCE_HI_SEC, field=SHORTLIST_CADENCE_ENV
    )
    stamp = as_utc(now)
    tally: Counter[str] = Counter()
    passed: list[ShortlistCandidate] = []
    for payload in prints:
        candidate, skip = classify_print(
            payload,
            stamp,
            max_age_sec=resolved_age,
            session=session,
        )
        if skip is not None:
            tally[skip] += 1
            continue
        if candidate is not None:
            passed.append(candidate)

    passed.sort(key=lambda row: (row.executed_at, row.occ), reverse=True)
    unique: list[ShortlistCandidate] = []
    seen: set[str] = set()
    for row in passed:
        if row.occ in seen:
            tally["duplicate_occ"] += 1
            continue
        seen.add(row.occ)
        unique.append(row)
        if len(unique) >= max_candidates:
            break

    empty: EmptyReason
    if unique:
        empty = None
    elif not had_input:
        empty = "no_input"
    elif not prints:
        empty = "no_fresh_prints"
    elif tally.get(SKIP_STALE_PRINT) == len(prints):
        empty = "no_fresh_prints"
    else:
        empty = "all_filtered"

    age_out = resolved_age if resolved_age is not None else DEFAULT_SIT_MATCH_MAX_AGE_SEC
    return ShortlistDocument(
        ranked_at=stamp,
        max_print_age_sec=age_out,
        cadence_sec=cadence,
        candidates=unique,
        skipped_count=sum(tally.values()),
        skip_tally=dict(sorted(tally.items())),
        empty_reason=empty,
        max_candidates=max_candidates,
    )


def candidate_from_mapping(raw: Mapping[str, Any]) -> ShortlistCandidate | None:
    occ = sit_match_occ_key(extract_occ(raw))
    if occ is None:
        return None
    underlying = extract_underlying(raw, occ)
    option_type = extract_option_type(raw, occ)
    executed = parse_executed_at(raw.get("executed_at"))
    premium = parse_premium(raw.get("premium"))
    age = _finite_positive(raw.get("print_age_sec"))
    if underlying is None or option_type is None or executed is None or premium is None:
        return None
    if age is None:
        return None
    source = extract_source(raw)
    return ShortlistCandidate(
        occ=occ,
        underlying=underlying,
        option_type=option_type,
        executed_at=executed_at_iso(executed),
        print_age_sec=age,
        premium=format(premium, "f"),
        source=source,
    )


def parse_shortlist_document(payload: Mapping[str, Any]) -> ShortlistDocument | None:
    if payload.get("schema") != SCHEMA_ID or payload.get("kind") != SHORTLIST_KIND:
        return None
    ranked = parse_executed_at(payload.get("ranked_at"))
    max_age = _finite_positive(payload.get("max_print_age_sec"))
    cadence = _finite_positive(payload.get("cadence_sec"))
    if ranked is None or max_age is None or cadence is None:
        return None
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
        return None
    candidates: list[ShortlistCandidate] = []
    for row in raw_candidates:
        if not isinstance(row, Mapping):
            return None
        parsed = candidate_from_mapping(row)
        if parsed is None:
            return None
        candidates.append(parsed)
    empty_raw = payload.get("empty_reason")
    empty: EmptyReason
    if empty_raw in {None, ""}:
        empty = None
    elif empty_raw == "no_input":
        empty = "no_input"
    elif empty_raw == "no_fresh_prints":
        empty = "no_fresh_prints"
    elif empty_raw == "all_filtered":
        empty = "all_filtered"
    else:
        return None
    tally_raw = payload.get("skip_tally")
    tally = dict(tally_raw) if isinstance(tally_raw, Mapping) else {}
    skip_tally = {
        str(k): int(v)
        for k, v in tally.items()
        if v is not None and _finite_positive(v) is not None
    }
    lo = parse_premium(payload.get("premium_lo")) or PREMIUM_BAND_LO
    hi = parse_premium(payload.get("premium_hi")) or PREMIUM_BAND_HI
    max_n = payload.get("max_candidates")
    max_candidates = MAX_CANDIDATES
    if max_n is not None and _finite_positive(max_n) is not None:
        max_candidates = int(max_n)
    skipped = payload.get("skipped_count")
    skipped_count = 0
    if skipped is not None and _finite_positive(skipped) is not None:
        skipped_count = int(skipped)
    return ShortlistDocument(
        ranked_at=ranked,
        max_print_age_sec=max_age,
        cadence_sec=cadence,
        candidates=candidates,
        skipped_count=skipped_count,
        skip_tally=skip_tally,
        empty_reason=empty,
        premium_lo=lo,
        premium_hi=hi,
        max_candidates=max_candidates,
    )


def evaluate_shortlist_document(
    payload: Mapping[str, Any],
    now: datetime,
    *,
    env: Mapping[str, str] | None = None,
    stale_sec: float | None = None,
    session: SessionFilters | None = None,
) -> ShortlistConsume:
    """Continual15 consume gate. Stale document / empty / schema → no hunt."""
    doc = parse_shortlist_document(payload)
    if doc is None:
        return ShortlistConsume(
            allow=False,
            reason=REASON_SCHEMA,
            ranked_at=None,
            age_seconds=None,
            candidates=(),
            stale_limit_sec=None,
        )
    limit = stale_sec if stale_sec is not None else shortlist_stale_sec(
        env, cadence_sec=doc.cadence_sec
    )
    if limit is None:
        return ShortlistConsume(
            allow=False,
            reason=REASON_INVALID_STALE_LIMIT,
            ranked_at=doc.ranked_at,
            age_seconds=None,
            candidates=(),
            stale_limit_sec=None,
        )
    age = quote_age_seconds(doc.ranked_at, now)
    if age > limit:
        return ShortlistConsume(
            allow=False,
            reason=REASON_STALE_SHORTLIST,
            ranked_at=doc.ranked_at,
            age_seconds=age,
            candidates=(),
            stale_limit_sec=limit,
        )
    held = session or SessionFilters()
    remaining = [
        row
        for row in doc.candidates
        if row.occ not in held.in_position_occs
        and row.underlying not in held.in_position_underlyings
    ]
    if not remaining:
        reason = REASON_IN_POSITION_CLEARED if doc.candidates else REASON_EMPTY
        return ShortlistConsume(
            allow=False,
            reason=reason,
            ranked_at=doc.ranked_at,
            age_seconds=age,
            candidates=(),
            stale_limit_sec=limit,
        )
    return ShortlistConsume(
        allow=True,
        reason=None,
        ranked_at=doc.ranked_at,
        age_seconds=age,
        candidates=tuple(remaining),
        stale_limit_sec=limit,
    )


def evaluate_shortlist_file(
    path: Path,
    now: datetime,
    *,
    env: Mapping[str, str] | None = None,
    session: SessionFilters | None = None,
) -> ShortlistConsume:
    if not path.is_file():
        return ShortlistConsume(
            allow=False,
            reason=REASON_EMPTY,
            ranked_at=None,
            age_seconds=None,
            candidates=(),
            stale_limit_sec=None,
        )
    raw = load_json_object(path)
    if not isinstance(raw, Mapping):
        return ShortlistConsume(
            allow=False,
            reason=REASON_SCHEMA,
            ranked_at=None,
            age_seconds=None,
            candidates=(),
            stale_limit_sec=None,
        )
    return evaluate_shortlist_document(raw, now, env=env, session=session)


def write_shortlist(path: Path, document: ShortlistDocument) -> None:
    write_json_atomic(path, document.as_dict(), redact=True)


def prints_from_ledger(path: Path) -> list[Mapping[str, Any]]:
    """Map flow_ledger rows to ranker prints. Missing file → empty (no invent)."""
    if not path.is_file() and str(path) != ":memory:":
        return []
    from groktrading.flow_ledger import FlowLedger

    rows: list[Mapping[str, Any]] = []
    for row in FlowLedger(path).iter_recent(limit=200):
        payload: dict[str, Any] = {
            "occ": row.occ,
            "ticker": row.ticker,
            "print": row.print,
            "nbbo_ask": row.nbbo_ask,
            "option_type": row.option_type,
            "source": row.source,
        }
        if row.executed_at is not None:
            payload["executed_at"] = executed_at_iso(row.executed_at)
        rows.append(payload)
    return rows


def collect_prints(
    *,
    prints_path: Path | None = None,
    tape_path: Path | None = None,
    ledger_path: Path | None = None,
) -> tuple[list[Mapping[str, Any]], bool]:
    """Load prints from explicit files. Missing files are not invented."""
    collected: list[Mapping[str, Any]] = []
    had_input = False
    for path in (prints_path, tape_path):
        if path is None:
            continue
        had_input = True
        if not path.is_file():
            continue
        collected.extend(extract_prints(load_json_object(path)))
    if ledger_path is not None:
        had_input = True
        collected.extend(prints_from_ledger(ledger_path))
    return collected, had_input


def build_shortlist_from_files(
    now: datetime,
    *,
    prints_path: Path | None = None,
    tape_path: Path | None = None,
    ledger_path: Path | None = None,
    already_run: Mapping[str, Any] | Sequence[object] | None = None,
    in_position: Mapping[str, Any] | Sequence[object] | None = None,
    env: Mapping[str, str] | None = None,
) -> ShortlistDocument:
    prints, had_input = collect_prints(
        prints_path=prints_path,
        tape_path=tape_path,
        ledger_path=ledger_path,
    )
    return rank_prints(
        prints,
        now,
        session=session_filters_from_mapping(already_run, in_position),
        cadence_sec=shortlist_cadence_sec(env),
        max_age_sec=shortlist_max_print_age_sec(env),
        had_input=had_input,
        env=env,
    )


def _optional_json(path: Path | None) -> object | None:
    if path is None or not path.is_file():
        return None
    return load_json_object(path)


def main(argv: list[str] | None = None) -> int:
    """Offline-safe ranker CLI. Never places orders. Never emits sit_match."""
    parser = argparse.ArgumentParser(
        description=(
            "Thin ranker: write shortlist.json (≤1–3 OCCs). No LLM. "
            "No sit_match. Never places orders. Host path "
            f"{HOST_SHORTLIST_PATH} is ops documentation, not auto-deploy."
        )
    )
    parser.add_argument("--prints", default="", help="JSON list of UW-like rows")
    parser.add_argument("--tape", default="", help="Optional live_tape-like JSON")
    parser.add_argument("--ledger", default="", help="Optional flow_ledger sqlite")
    parser.add_argument("--already-run", default="", help="JSON session already-run")
    parser.add_argument("--in-position", default="", help="JSON in_position OCCs")
    parser.add_argument(
        "--out",
        default="",
        help=f"Output path (default ${SHORTLIST_PATH_ENV} or {DEFAULT_SHORTLIST_PATH})",
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional UTC ISO clock for offline tests. Default: wall clock.",
    )
    args = parser.parse_args(argv)
    env = dict(os.environ)
    max_age = shortlist_max_print_age_sec(env)
    if max_age is None:
        print("shortlist_ranker: invalid print max age (fail closed)", file=sys.stderr)
        return 2
    try:
        cadence = shortlist_cadence_sec(env)
    except CadenceError as exc:
        print(f"shortlist_ranker: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if str(args.out).strip() else shortlist_output_path(env)
    prints_path = Path(args.prints) if str(args.prints).strip() else None
    tape_path = Path(args.tape) if str(args.tape).strip() else None
    ledger_raw = str(args.ledger).strip() or env.get("FLOW_LEDGER_PATH", "").strip()
    if not ledger_raw and tape_path is None and prints_path is None:
        tape_env = env.get("LIVE_TAPE_PATH", "").strip()
        if tape_env:
            tape_path = Path(tape_env)
        ledger_env = env.get("FLOW_LEDGER_PATH", "").strip()
        if ledger_env:
            ledger_raw = ledger_env
    ledger_path = Path(ledger_raw) if ledger_raw else None
    already_raw = _optional_json(Path(args.already_run) if str(args.already_run).strip() else None)
    held_raw = _optional_json(Path(args.in_position) if str(args.in_position).strip() else None)

    def _filter_doc(raw: object) -> Mapping[str, Any] | Sequence[object] | None:
        if isinstance(raw, Mapping):
            return raw
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return raw
        return None

    already = _filter_doc(already_raw)
    held = _filter_doc(held_raw)
    if str(args.now).strip():
        parsed_now = parse_executed_at(str(args.now).strip())
        if parsed_now is None:
            print("shortlist_ranker: invalid --now (fail closed)", file=sys.stderr)
            return 2
        now = parsed_now
    else:
        now = datetime.now(tz=UTC)
    document = build_shortlist_from_files(
        now,
        prints_path=prints_path,
        tape_path=tape_path,
        ledger_path=ledger_path,
        already_run=already,
        in_position=held,
        env=env,
    )
    # Re-apply resolved cadence from this process (build already used env).
    document.cadence_sec = cadence
    document.max_print_age_sec = max_age
    write_shortlist(out, document)
    print(
        "shortlist_ranker "
        f"out={out} n={len(document.candidates)} "
        f"skipped={document.skipped_count} empty_reason={document.empty_reason} "
        f"cadence_sec={document.cadence_sec} max_print_age_sec={document.max_print_age_sec} "
        "emit_sit_match=False no_orders no_llm",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
