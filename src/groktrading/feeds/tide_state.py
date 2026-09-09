"""Slow UW market-tide + optional per-symbol net-prem state writer.

Documented paths only:
  ``GET /api/market/market-tide``
  ``GET /api/stock/{ticker}/net-prem-ticks``

Cadence 1–5 minutes (``TIDE_POLL_SEC``, default 180). Writes a small
``tide_state.json`` under STATE_DIR. Deterministic field copy. No LLM.
No sit_match spray. No orders.

Per-symbol net-prem is optional and bounded (default max 8 names).
Invalid tickers are skipped (fail-closed, no path injection).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from groktrading.cadence import env_seconds
from groktrading.errors import TimeoutFailClosedError
from groktrading.feeds.unusual_whales import (
    UW_MARKET_TIDE_PATH,
    UnusualWhalesClient,
    net_prem_ticks_path,
    sanitize_ticker,
    uw_data_rows,
)
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC, as_utc

TIDE_POLL_ENV = "TIDE_POLL_SEC"
DEFAULT_TIDE_POLL_SEC = 180.0
TIDE_POLL_LO = 60.0
TIDE_POLL_HI = 300.0
TIDE_ROW_CAP = 12
NET_PREM_ROW_CAP = 8
NET_PREM_SYMBOL_CAP = 8
TIDE_FIELDS = ("timestamp", "date", "net_call_premium", "net_put_premium", "net_volume")
NET_PREM_FIELDS = ("timestamp", "date", "net_call_premium", "net_put_premium", "net_volume")
NEVER_ORDERS_NOTE = (
    "Deterministic UW tide / net-prem copy. No LLM. Not sit_match. "
    "Never places orders."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def tide_poll_sec(env: Mapping[str, str] | None = None) -> float:
    return env_seconds(
        env,
        TIDE_POLL_ENV,
        default=DEFAULT_TIDE_POLL_SEC,
        lo=TIDE_POLL_LO,
        hi=TIDE_POLL_HI,
    )


def _pick_fields(row: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        raw = row.get(key)
        if raw not in (None, ""):
            out[key] = raw
    return out


def _bounded_symbols(symbols: Iterable[str], *, cap: int = NET_PREM_SYMBOL_CAP) -> list[str]:
    seen: list[str] = []
    for raw in symbols:
        clean = sanitize_ticker(raw)
        if clean is None or clean in seen:
            continue
        seen.append(clean)
        if len(seen) >= cap:
            break
    return seen


@dataclass(frozen=True)
class TideSnapshot:
    as_of: datetime
    cadence_sec: float
    tide: tuple[dict[str, Any], ...]
    net_prem: dict[str, tuple[dict[str, Any], ...]]
    skipped_tickers: tuple[str, ...]
    tide_ok: bool
    detail: str


def fetch_tide_snapshot(
    client: UnusualWhalesClient,
    *,
    now: datetime | None = None,
    net_prem_symbols: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
) -> TideSnapshot:
    """One slow poll. Timeouts fail closed; missing net-prem is skipped."""
    stamp = as_utc(now or client.clock.now())
    cadence = tide_poll_sec(env)
    _status, body = client.get_documented_path(UW_MARKET_TIDE_PATH)
    ticks = [_pick_fields(row, TIDE_FIELDS) for row in uw_data_rows(body)[-TIDE_ROW_CAP:]]
    net: dict[str, tuple[dict[str, Any], ...]] = {}
    skipped: list[str] = []
    for ticker in _bounded_symbols(net_prem_symbols):
        try:
            path = net_prem_ticks_path(ticker)
            _st, prem_body = client.get_documented_path(path)
        except (ValueError, TimeoutFailClosedError):
            skipped.append(ticker)
            continue
        rows = [_pick_fields(row, NET_PREM_FIELDS) for row in uw_data_rows(prem_body)]
        net[ticker] = tuple(rows[-NET_PREM_ROW_CAP:])
    return TideSnapshot(
        as_of=stamp,
        cadence_sec=cadence,
        tide=tuple(ticks),
        net_prem=net,
        skipped_tickers=tuple(skipped),
        tide_ok=True,
        detail="ok",
    )


def tide_document(snap: TideSnapshot) -> dict[str, Any]:
    return {
        "source": "uw_market_tide",
        "note": NEVER_ORDERS_NOTE,
        "as_of": snap.as_of.isoformat(),
        "cadence_sec": snap.cadence_sec,
        "path": UW_MARKET_TIDE_PATH,
        "tick_count": len(snap.tide),
        "row_cap": TIDE_ROW_CAP,
        "ticks": list(snap.tide),
        "net_prem": {k: list(v) for k, v in snap.net_prem.items()},
        "net_prem_symbol_cap": NET_PREM_SYMBOL_CAP,
        "skipped_tickers": list(snap.skipped_tickers),
        "places_orders": False,
        "emits_sit_match": False,
    }


def write_tide_state(
    client: UnusualWhalesClient,
    path: Path,
    *,
    now: datetime | None = None,
    net_prem_symbols: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    snap = fetch_tide_snapshot(
        client, now=now, net_prem_symbols=net_prem_symbols, env=env
    )
    doc = tide_document(snap)
    write_json_atomic(Path(path), doc)
    return doc
