"""sit_match freshness: UW option-trades ``executed_at`` is the print clock.

Helsinki ``ws_tape.py`` (not in this git tree) fires ``sit_match`` from Unusual
Whales ``option-trades`` rows. Those rows linger in UW's rolling feed for hours
and can re-wake the desk after Tradier ask has moved. Debounce is ~90s per OCC
and is not a freshness gate.

Fail closed: missing or unparseable ``executed_at`` must not emit or consume a
``sit_match``. Do not substitute ``created_at`` or ``timestamp``. Age must be
≤ ``SIT_MATCH_MAX_AGE_SEC`` (default 60). Non-finite limits (inf/NaN) fail
closed. This module is the in-repo source of truth for that gate. Apply the
same check in the live ``ws_tape`` sit_match branch; ``install_helsinki.sh``
does not copy ``ws_tape.py``. The append-only flow ledger
(``groktrading.flow_ledger``) may store stale or clock-less prints for
research; emission still uses this gate.

Emitter/inbox stay on this module. The live final gate also requires
``candidate.executed_at`` (same clock, no ``created_at`` / ``timestamp``
substitute). Quote freshness remains a separate Tradier quote-gate check.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from groktrading.timeutil import UTC, as_utc, is_future_ts, is_stale, quote_age_seconds

SIT_MATCH_EVENT = "sit_match"
SIT_MATCH_MAX_AGE_ENV = "SIT_MATCH_MAX_AGE_SEC"
DEFAULT_SIT_MATCH_MAX_AGE_SEC = 60.0

REASON_MISSING = "sit_match_missing_executed_at"
REASON_UNPARSEABLE = "sit_match_unparseable_executed_at"
REASON_STALE = "sit_match_stale"
REASON_FUTURE = "sit_match_future_executed_at"
REASON_INVALID_MAX_AGE = "sit_match_invalid_max_age"


@dataclass(frozen=True)
class SitMatchFreshness:
    allow: bool
    reason: str | None
    executed_at: datetime | None
    age_seconds: float | None
    executed_at_iso: str | None
    max_age_sec: float | None


def _finite_max_age(value: object) -> float | None:
    """Accept a non-negative finite age. inf / NaN / junk → None (fail closed)."""
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def sit_match_max_age_sec(env: Mapping[str, str] | None = None) -> float | None:
    """Return configured max age, default 60. None if the env value is invalid."""
    source = os.environ if env is None else env
    raw = source.get(SIT_MATCH_MAX_AGE_ENV)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_SIT_MATCH_MAX_AGE_SEC
    return _finite_max_age(str(raw).strip())


def resolve_sit_match_max_age(
    max_age_sec: float | None = None,
    env: Mapping[str, str] | None = None,
) -> float | None:
    """Resolve an explicit arg or env. Non-finite / negative → None."""
    if max_age_sec is not None:
        return _finite_max_age(max_age_sec)
    return sit_match_max_age_sec(env)


def executed_at_iso(value: datetime) -> str:
    """UTC ISO-8601 with Z. Payload form for sit_match webhooks."""
    return as_utc(value).isoformat().replace("+00:00", "Z")


def parse_executed_at(value: object) -> datetime | None:
    """Parse ISO-8601 Z or offset. Naive / missing / junk → None (fail closed)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return as_utc(value)
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return None
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


def extract_executed_at(payload: Mapping[str, Any]) -> object:
    """Top-level ``executed_at``, else nested ``candidate.executed_at``."""
    raw = payload.get("executed_at")
    if raw not in (None, ""):
        return raw
    candidate = payload.get("candidate")
    if isinstance(candidate, Mapping):
        return candidate.get("executed_at")
    return None


def evaluate_sit_match_freshness(
    executed_at: object,
    now: datetime,
    *,
    max_age_sec: float | None = None,
    env: Mapping[str, str] | None = None,
) -> SitMatchFreshness:
    """Allow only when ``executed_at`` parses and age ≤ max (default 60s).

    ``executed_at`` is the only execution clock. Callers must not pass
    ``created_at`` / ``timestamp`` as a substitute. Missing/unparseable
    ``executed_at`` fail closed. Non-finite ``max_age_sec`` (inf/NaN) is
    rejected in both the explicit arg and env parsing.
    """
    resolved = resolve_sit_match_max_age(max_age_sec, env)
    if resolved is None:
        return SitMatchFreshness(
            allow=False,
            reason=REASON_INVALID_MAX_AGE,
            executed_at=None,
            age_seconds=None,
            executed_at_iso=None,
            max_age_sec=None,
        )
    limit = resolved

    if executed_at is None or (isinstance(executed_at, str) and not executed_at.strip()):
        return SitMatchFreshness(
            allow=False,
            reason=REASON_MISSING,
            executed_at=None,
            age_seconds=None,
            executed_at_iso=None,
            max_age_sec=limit,
        )

    parsed = parse_executed_at(executed_at)
    if parsed is None:
        return SitMatchFreshness(
            allow=False,
            reason=REASON_UNPARSEABLE,
            executed_at=None,
            age_seconds=None,
            executed_at_iso=None,
            max_age_sec=limit,
        )

    age = quote_age_seconds(parsed, now)
    iso = executed_at_iso(parsed)
    if is_future_ts(parsed, now):
        return SitMatchFreshness(
            allow=False,
            reason=REASON_FUTURE,
            executed_at=parsed,
            age_seconds=age,
            executed_at_iso=iso,
            max_age_sec=limit,
        )
    if is_stale(parsed, now, limit):
        return SitMatchFreshness(
            allow=False,
            reason=REASON_STALE,
            executed_at=parsed,
            age_seconds=age,
            executed_at_iso=iso,
            max_age_sec=limit,
        )
    return SitMatchFreshness(
        allow=True,
        reason=None,
        executed_at=parsed,
        age_seconds=age,
        executed_at_iso=iso,
        max_age_sec=limit,
    )


def evaluate_sit_match_payload(
    payload: Mapping[str, Any],
    now: datetime,
    *,
    max_age_sec: float | None = None,
    env: Mapping[str, str] | None = None,
) -> SitMatchFreshness:
    return evaluate_sit_match_freshness(
        extract_executed_at(payload),
        now,
        max_age_sec=max_age_sec,
        env=env,
    )


def attach_executed_at(
    payload: Mapping[str, Any],
    decision: SitMatchFreshness,
) -> dict[str, Any]:
    """Copy payload and set ``executed_at`` (and nested candidate) to parsed ISO."""
    if decision.executed_at_iso is None:
        raise ValueError("cannot attach executed_at without a parsed timestamp")
    out = dict(payload)
    out["executed_at"] = decision.executed_at_iso
    candidate = out.get("candidate")
    if isinstance(candidate, dict):
        nested = dict(candidate)
        nested["executed_at"] = decision.executed_at_iso
        out["candidate"] = nested
    return out
