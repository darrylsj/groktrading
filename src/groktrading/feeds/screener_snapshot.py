"""Thin RTH UW option-screener snapshot for Grok to pull.

Documented path: ``GET /api/screener/option-contracts``.
Cadence 5–15 minutes (``SCREENER_POLL_SEC``, default 600) during RTH
only. Writes ``screener_state.json``. Does **not** emit sit_match for
every row — this is a pull snapshot, not a webhook spray.

No LLM. No orders. Transport is injected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from groktrading.cadence import env_seconds
from groktrading.feeds.unusual_whales import (
    UW_SCREENER_PATH,
    UnusualWhalesClient,
    uw_data_rows,
)
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC, as_utc, market_session_kind

SCREENER_POLL_ENV = "SCREENER_POLL_SEC"
DEFAULT_SCREENER_POLL_SEC = 600.0
SCREENER_POLL_LO = 300.0
SCREENER_POLL_HI = 900.0
SCREENER_ROW_CAP = 40
SCREENER_FIELDS = (
    "ticker_symbol",
    "ticker",
    "option_symbol",
    "type",
    "strike",
    "expiry",
    "ask_side_volume",
    "bid_side_volume",
    "volume",
    "open_interest",
    "avg_price",
    "premium",
    "implied_volatility",
)
NEVER_ORDERS_NOTE = (
    "Thin RTH option-screener snapshot for Grok to pull. "
    "Do not spray sit_match for every row. Never places orders."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def screener_poll_sec(env: Mapping[str, str] | None = None) -> float:
    return env_seconds(
        env,
        SCREENER_POLL_ENV,
        default=DEFAULT_SCREENER_POLL_SEC,
        lo=SCREENER_POLL_LO,
        hi=SCREENER_POLL_HI,
    )


def _pick_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SCREENER_FIELDS:
        raw = row.get(key)
        if raw not in (None, ""):
            out[key] = raw
    return out


@dataclass(frozen=True)
class ScreenerSnapshot:
    as_of: datetime
    cadence_sec: float
    rth: bool
    wrote: bool
    rows: tuple[dict[str, Any], ...]
    skipped_reason: str | None


def fetch_screener_snapshot(
    client: UnusualWhalesClient,
    *,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
    rth_only: bool = True,
    clock_state: str | None = None,
) -> ScreenerSnapshot:
    stamp = as_utc(now or client.clock.now())
    cadence = screener_poll_sec(env)
    kind = market_session_kind(stamp, clock_state)
    rth = kind == "rth"
    if rth_only and not rth:
        return ScreenerSnapshot(
            as_of=stamp,
            cadence_sec=cadence,
            rth=False,
            wrote=False,
            rows=(),
            skipped_reason="not_rth",
        )
    _status, body = client.get_documented_path(
        UW_SCREENER_PATH, params={"limit": str(SCREENER_ROW_CAP)}
    )
    rows = tuple(_pick_fields(row) for row in uw_data_rows(body)[:SCREENER_ROW_CAP])
    return ScreenerSnapshot(
        as_of=stamp,
        cadence_sec=cadence,
        rth=rth,
        wrote=True,
        rows=rows,
        skipped_reason=None,
    )


def screener_document(snap: ScreenerSnapshot) -> dict[str, Any]:
    return {
        "source": "uw_option_screener",
        "note": NEVER_ORDERS_NOTE,
        "as_of": snap.as_of.isoformat(),
        "cadence_sec": snap.cadence_sec,
        "path": UW_SCREENER_PATH,
        "rth": snap.rth,
        "wrote": snap.wrote,
        "skipped_reason": snap.skipped_reason,
        "row_count": len(snap.rows),
        "row_cap": SCREENER_ROW_CAP,
        "rows": list(snap.rows),
        "emits_sit_match": False,
        "places_orders": False,
    }


def write_screener_state(
    client: UnusualWhalesClient,
    path: Path,
    *,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
    rth_only: bool = True,
    clock_state: str | None = None,
) -> dict[str, Any]:
    snap = fetch_screener_snapshot(
        client, now=now, env=env, rth_only=rth_only, clock_state=clock_state
    )
    doc = screener_document(snap)
    if snap.wrote:
        write_json_atomic(Path(path), doc)
    return doc
