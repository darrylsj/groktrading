"""Clamp poll cadences. Helsinki disk and rate limits are tight; no spray."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class CadenceError(ValueError):
    """Fail-closed cadence (unparseable or out of the documented window)."""


def parse_seconds(value: object, *, field: str) -> float:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        raise CadenceError(f"missing_{field}")
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CadenceError(f"unparseable_{field}") from exc
    if seconds != seconds or seconds <= 0:  # NaN or non-positive
        raise CadenceError(f"invalid_{field}")
    return seconds


def clamp_seconds(value: object, *, lo: float, hi: float, field: str) -> float:
    """Parse and clamp. Out-of-range is clamped, not invented from a default."""
    seconds = parse_seconds(value, field=field)
    if seconds < lo:
        return lo
    if seconds > hi:
        return hi
    return seconds


def env_seconds(
    env: Mapping[str, str] | None,
    key: str,
    *,
    default: float,
    lo: float,
    hi: float,
) -> float:
    """Read ``key`` from env. Missing/blank → default (then clamped)."""
    source: Mapping[str, Any] = {} if env is None else env
    raw = source.get(key)
    if raw is None or str(raw).strip() == "":
        return clamp_seconds(default, lo=lo, hi=hi, field=key)
    return clamp_seconds(raw, lo=lo, hi=hi, field=key)
