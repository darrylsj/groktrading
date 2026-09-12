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

``print_age_sec`` is derived from ``executed_at`` vs wall clock at POST. A
payload field that claims 1–10s while ``executed_at`` is minutes old is a
lie — never use it as the freshness clock. Call
``prepare_sit_match_outbound`` immediately before HTTP POST (not at match
detect / enqueue). Stamp ``emitted_at``. Live Helsinki producer (2026-09-11):
OCC-only debounce plus ``SIT_MATCH_MIN_INTERVAL_SEC`` (default **60**) so
one OCC cannot firehose (~20+/min POSTs queued Cursor wakes to p50 ~16m;
HTTP was always ~0.5–0.7s). Mute with ``SIT_MATCH_WEBHOOK=0`` and/or
``/opt/trading-desk/state/sit_match_webhook_muted``.

Emitter/inbox stay on this module. The live final gate also requires
``candidate.executed_at`` (same clock, no ``created_at`` / ``timestamp``
substitute). Quote freshness remains a separate Tradier quote-gate check.

Hunt architecture (2026-09-12): ``sit_match`` POSTs are **not** the
selection loop. Prefer ``SIT_MATCH_WEBHOOK`` off for hunt (optional rare
alert mode only). ``SIT_MATCH_MIN_INTERVAL_SEC`` is a Cursor wake bandage
— default hunt must not depend on it and must not raise
``SIT_MATCH_MAX_AGE_SEC`` to match it. Continual15 pulls
``shortlist.json`` (``groktrading.shortlist``). See
``docs/REALTIME_PLANES.md``.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from groktrading.timeutil import UTC, as_utc, is_future_ts, is_stale, quote_age_seconds

SIT_MATCH_EVENT = "sit_match"
SIT_MATCH_MAX_AGE_ENV = "SIT_MATCH_MAX_AGE_SEC"
DEFAULT_SIT_MATCH_MAX_AGE_SEC = 60.0
SIT_MATCH_MIN_INTERVAL_ENV = "SIT_MATCH_MIN_INTERVAL_SEC"
DEFAULT_SIT_MATCH_MIN_INTERVAL_SEC = 60.0
SIT_MATCH_WEBHOOK_ENV = "SIT_MATCH_WEBHOOK"
DEFAULT_SIT_MATCH_MUTE_FILE = "/opt/trading-desk/state/sit_match_webhook_muted"
# Hunt path prefers webhooks off. Unset still means the optional alert
# producer may emit unless muted — hunt must not depend on that.
HUNT_SIT_MATCH_WEBHOOK_DEFAULT = False

REASON_MISSING = "sit_match_missing_executed_at"
REASON_UNPARSEABLE = "sit_match_unparseable_executed_at"
REASON_STALE = "sit_match_stale"
REASON_STALE_AT_POST = "sit_match_stale_at_post"
REASON_FUTURE = "sit_match_future_executed_at"
REASON_INVALID_MAX_AGE = "sit_match_invalid_max_age"
REASON_INVALID_MIN_INTERVAL = "sit_match_invalid_min_interval"
REASON_PRINT_AGE_CONTRADICTS = "sit_match_print_age_contradicts"
REASON_OCC_DEBOUNCE = "sit_match_occ_debounce"
REASON_MIN_INTERVAL = "sit_match_min_interval"
REASON_MUTED = "sit_match_webhook_muted"
PRINT_AGE_SLACK_SEC = 2.0
# OCC aliases match flow_ledger; sit_match must not import the ledger.
OCC_ALIAS_KEYS: tuple[str, ...] = ("occ", "option_symbol", "option_chain_id", "option_chain")


@dataclass(frozen=True)
class SitMatchFreshness:
    allow: bool
    reason: str | None
    executed_at: datetime | None
    age_seconds: float | None
    executed_at_iso: str | None
    max_age_sec: float | None


@dataclass(frozen=True)
class SitMatchOutbound:
    """POST-time decision. ``payload`` is set only when ``allow`` is True."""

    allow: bool
    reason: str | None
    freshness: SitMatchFreshness
    payload: dict[str, Any] | None
    print_age_sec: float | None
    emitted_at: str | None
    print_key: str | None
    occ: str | None = None

    def log_fields(self) -> dict[str, Any]:
        """Secret-free hop log shape for ``trading-desk-tape`` journalctl."""
        hop = None
        if self.payload is not None:
            raw_hop = self.payload.get("hop")
            hop = raw_hop if isinstance(raw_hop, dict) else None
        return {
            "event": SIT_MATCH_EVENT,
            "allow": self.allow,
            "reason": self.reason,
            "executed_at": self.freshness.executed_at_iso,
            "print_age_sec": self.print_age_sec,
            "emitted_at": self.emitted_at,
            "print_key": self.print_key,
            "occ": self.occ,
            "hop": hop,
        }


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


def extract_occ(payload: Mapping[str, Any]) -> str | None:
    """OCC from top-level aliases or nested ``candidate.option_symbol``."""
    for key in OCC_ALIAS_KEYS:
        raw = payload.get(key)
        if raw not in (None, ""):
            text = str(raw).strip()
            if text:
                return text
    candidate = payload.get("candidate")
    if isinstance(candidate, Mapping):
        for key in ("option_symbol", "occ"):
            raw = candidate.get(key)
            if raw not in (None, ""):
                text = str(raw).strip()
                if text:
                    return text
    return None


def extract_print_age_sec(payload: Mapping[str, Any]) -> float | None:
    """Inbound ``print_age_sec`` if finite and ≥0. Never a freshness clock."""
    raw = payload.get("print_age_sec")
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def print_age_contradicts(
    claimed: float,
    true_age: float,
    *,
    slack_sec: float = PRINT_AGE_SLACK_SEC,
) -> bool:
    """True when claimed print age is not the executed_at age."""
    return abs(claimed - true_age) > slack_sec


def sit_match_occ_key(occ: str | None) -> str | None:
    """OCC-only debounce identity. One hot name cannot firehose unique prints."""
    if not occ:
        return None
    text = occ.strip().upper()
    return text or None


def sit_match_min_interval_sec(env: Mapping[str, str] | None = None) -> float | None:
    """Seconds between sit_match POSTs. Default 60. None if env is invalid."""
    source = os.environ if env is None else env
    raw = source.get(SIT_MATCH_MIN_INTERVAL_ENV)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_SIT_MATCH_MIN_INTERVAL_SEC
    return _finite_max_age(str(raw).strip())


def sit_match_mute_path(
    env: Mapping[str, str] | None = None,
    mute_path: Path | str | None = None,
) -> Path:
    if mute_path is not None:
        return Path(mute_path)
    source = os.environ if env is None else env
    raw = source.get("SIT_MATCH_MUTE_FILE")
    if raw is not None and str(raw).strip():
        return Path(str(raw).strip())
    return Path(DEFAULT_SIT_MATCH_MUTE_FILE)


def sit_match_webhook_enabled(
    env: Mapping[str, str] | None = None,
    mute_path: Path | str | None = None,
) -> bool:
    """False when ``SIT_MATCH_WEBHOOK=0`` or the mute file exists.

    Hunt prefers this off (``HUNT_SIT_MATCH_WEBHOOK_DEFAULT``). Unset still
    allows the optional rare-alert producer unless muted. Continual15 +
    shortlist is the default hunt path.
    """
    path = sit_match_mute_path(env, mute_path)
    try:
        if path.is_file():
            return False
    except OSError:
        return False
    source = os.environ if env is None else env
    raw = source.get(SIT_MATCH_WEBHOOK_ENV)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class SitMatchEmitMemory:
    """In-process last-POST clocks. OCC-only; not OCC|executed_at."""

    last_any: datetime | None = None
    last_occ: dict[str, datetime] = field(default_factory=dict)

    def remember(self, occ: str, when: datetime) -> None:
        stamp = as_utc(when)
        self.last_any = stamp
        self.last_occ[occ] = stamp


def evaluate_sit_match_rate(
    occ: str | None,
    now: datetime,
    memory: SitMatchEmitMemory | None,
    *,
    env: Mapping[str, str] | None = None,
    min_interval_sec: float | None = None,
) -> str | None:
    """Return a skip reason when global or per-OCC interval has not elapsed."""
    resolved = min_interval_sec if min_interval_sec is not None else sit_match_min_interval_sec(env)
    if resolved is None:
        return REASON_INVALID_MIN_INTERVAL
    if memory is None:
        return None
    stamp = as_utc(now)
    key = sit_match_occ_key(occ)
    if key is not None:
        last_occ = memory.last_occ.get(key)
        if last_occ is not None and quote_age_seconds(last_occ, stamp) < resolved:
            return REASON_OCC_DEBOUNCE
    if memory.last_any is not None and quote_age_seconds(memory.last_any, stamp) < resolved:
        return REASON_MIN_INTERVAL
    return None


def _extract_optional_ts(payload: Mapping[str, Any], *keys: str) -> object:
    hop = payload.get("hop")
    hop_map = hop if isinstance(hop, Mapping) else {}
    for key in keys:
        raw = payload.get(key)
        if raw not in (None, ""):
            return raw
        nested = hop_map.get(key)
        if nested not in (None, ""):
            return nested
    return None


def attach_sit_match_clocks(
    payload: Mapping[str, Any],
    decision: SitMatchFreshness,
    now: datetime,
    *,
    detected_at: object | None = None,
    enqueued_at: object | None = None,
) -> dict[str, Any]:
    """Stamp truthful ``print_age_sec`` + ``emitted_at``. Overwrite any lie."""
    if decision.age_seconds is None:
        raise ValueError("cannot attach sit_match clocks without a print age")
    out = attach_executed_at(payload, decision)
    stamp = as_utc(now)
    emitted_iso = executed_at_iso(stamp)
    out["print_age_sec"] = decision.age_seconds
    out["emitted_at"] = emitted_iso
    hop: dict[str, Any] = {}
    existing = out.get("hop")
    if isinstance(existing, Mapping):
        hop.update({k: v for k, v in existing.items() if k not in {"print_age_sec"}})
    detected_raw = detected_at if detected_at not in (None, "") else _extract_optional_ts(
        payload, "detected_at"
    )
    enqueued_raw = enqueued_at if enqueued_at not in (None, "") else _extract_optional_ts(
        payload, "enqueued_at"
    )
    detected = parse_executed_at(detected_raw)
    enqueued = parse_executed_at(enqueued_raw)
    if detected is not None:
        hop["detected_at"] = executed_at_iso(detected)
        hop["detect_to_emit_sec"] = quote_age_seconds(detected, stamp)
    if enqueued is not None:
        hop["enqueued_at"] = executed_at_iso(enqueued)
        hop["enqueue_to_emit_sec"] = quote_age_seconds(enqueued, stamp)
    hop["emitted_at"] = emitted_iso
    hop["print_age_sec"] = decision.age_seconds
    hop["executed_at_age_sec"] = decision.age_seconds
    out["hop"] = hop
    if detected is not None:
        out["detected_at"] = hop["detected_at"]
    if enqueued is not None:
        out["enqueued_at"] = hop["enqueued_at"]
    return out


def prepare_sit_match_outbound(
    payload: Mapping[str, Any],
    now: datetime,
    *,
    detected_at: object | None = None,
    enqueued_at: object | None = None,
    max_age_sec: float | None = None,
    env: Mapping[str, str] | None = None,
    stale_at_post: bool = False,
    memory: SitMatchEmitMemory | None = None,
    mute_path: Path | str | None = None,
    min_interval_sec: float | None = None,
    apply_rate_limits: bool = True,
) -> SitMatchOutbound:
    """Single POST gate. Call immediately before HTTP, not at match detect.

    Freshness is ``executed_at`` only. ``print_age_sec`` / ``created_at`` /
    ``timestamp`` / ``detected_at`` cannot pass a stale print. A claimed
    ``print_age_sec`` that looks fresh while ``executed_at`` is stale is
    ``sit_match_print_age_contradicts``. When ``stale_at_post`` is set, a
    late re-check uses ``sit_match_stale_at_post``.

    Live producer controls (Helsinki ``ws_tape.py`` 2026-09-11): mute via
    ``SIT_MATCH_WEBHOOK=0`` or the mute file; OCC-only debounce plus
    ``SIT_MATCH_MIN_INTERVAL_SEC`` (default 60). Inbox should pass
    ``apply_rate_limits=False`` so a delayed wake is freshness-only.
    """
    freshness = evaluate_sit_match_payload(
        payload, now, max_age_sec=max_age_sec, env=env
    )
    occ = sit_match_occ_key(extract_occ(payload))
    claimed = extract_print_age_sec(payload)
    lie = (
        claimed is not None
        and freshness.age_seconds is not None
        and print_age_contradicts(claimed, freshness.age_seconds)
    )
    if apply_rate_limits and not sit_match_webhook_enabled(env, mute_path):
        return SitMatchOutbound(
            allow=False,
            reason=REASON_MUTED,
            freshness=freshness,
            payload=None,
            print_age_sec=freshness.age_seconds,
            emitted_at=None,
            print_key=occ,
            occ=occ,
        )
    if not freshness.allow:
        reason = freshness.reason
        if stale_at_post and freshness.reason == REASON_STALE:
            # Enqueue-time print_age_sec becomes a "lie" after a queue delay;
            # the hop that failed is POST, not a forged inbound age.
            reason = REASON_STALE_AT_POST
        elif (
            lie
            and freshness.reason == REASON_STALE
            and freshness.max_age_sec is not None
            and claimed is not None
            and claimed <= freshness.max_age_sec
        ):
            reason = REASON_PRINT_AGE_CONTRADICTS
        return SitMatchOutbound(
            allow=False,
            reason=reason,
            freshness=freshness,
            payload=None,
            print_age_sec=freshness.age_seconds,
            emitted_at=None,
            print_key=occ,
            occ=occ,
        )
    if apply_rate_limits:
        rate_reason = evaluate_sit_match_rate(
            occ, now, memory, env=env, min_interval_sec=min_interval_sec
        )
        if rate_reason is not None:
            return SitMatchOutbound(
                allow=False,
                reason=rate_reason,
                freshness=freshness,
                payload=None,
                print_age_sec=freshness.age_seconds,
                emitted_at=None,
                print_key=occ,
                occ=occ,
            )
    outbound = attach_sit_match_clocks(
        payload,
        freshness,
        now,
        detected_at=detected_at,
        enqueued_at=enqueued_at,
    )
    if occ is None:
        occ = sit_match_occ_key(extract_occ(outbound))
    return SitMatchOutbound(
        allow=True,
        reason=None,
        freshness=freshness,
        payload=outbound,
        print_age_sec=freshness.age_seconds,
        emitted_at=outbound["emitted_at"],
        print_key=occ,
        occ=occ,
    )
