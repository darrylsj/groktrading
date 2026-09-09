"""Shadow minute-mark helper — quote marks only, never orders.

Given a list of OCC / shadow positions, poll Tradier quotes on a minute
cadence and append marks. Intended for a ≥10-name shadow book or an
external shadow lane. Helsinki listens; this is **not** a submit path.

Marks store bid/ask/quote_ts from the injected Tradier client. No
invented PnL. Production NBBO is pricing truth; sandbox is delayed.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from groktrading.cadence import env_seconds
from groktrading.errors import TimeoutFailClosedError
from groktrading.models import OptionQuote
from groktrading.sit_match import parse_executed_at
from groktrading.timeutil import UTC, as_utc

SHADOW_MARK_ENV = "SHADOW_MARK_SEC"
DEFAULT_SHADOW_MARK_SEC = 60.0
SHADOW_MARK_LO = 30.0
SHADOW_MARK_HI = 180.0
SHADOW_OCC_CAP = 64
NEVER_ORDERS_NOTE = (
    "Shadow minute marks from Tradier quotes. Never places orders. "
    "No invented PnL. Grok Bot is the only submit path."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class QuoteSource(Protocol):
    def quote_option(self, option_symbol: str) -> OptionQuote: ...


def shadow_mark_sec(env: Mapping[str, str] | None = None) -> float:
    return env_seconds(
        env,
        SHADOW_MARK_ENV,
        default=DEFAULT_SHADOW_MARK_SEC,
        lo=SHADOW_MARK_LO,
        hi=SHADOW_MARK_HI,
    )


def due(last: datetime | None, now: datetime, *, cadence_sec: float) -> bool:
    if last is None:
        return True
    return (as_utc(now) - as_utc(last)).total_seconds() >= cadence_sec


def normalize_occ(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if len(text) < 5 or not text.isalnum():
        return None
    return text


def bounded_occs(occs: Iterable[str], *, cap: int = SHADOW_OCC_CAP) -> list[str]:
    out: list[str] = []
    for raw in occs:
        occ = normalize_occ(raw)
        if occ is None or occ in out:
            continue
        out.append(occ)
        if len(out) >= cap:
            break
    return out


def _iso(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    parsed = parse_executed_at(value)
    if parsed is None:
        raise ShadowMarkError("corrupt_mark_timestamp")
    return parsed


class ShadowMarkError(ValueError):
    """Fail-closed shadow-mark input."""


@dataclass(frozen=True)
class ShadowMark:
    occ: str
    bid: str
    ask: str
    quote_ts: datetime
    marked_at: datetime
    delayed: bool
    source: str
    mark_id: int | None = None


class ShadowMarkBook:
    """Append-only SQLite marks. Purge is not implemented here (Box rotate)."""

    def __init__(self, path: Path | str, clock: Clock | None = None) -> None:
        self.path = str(path)
        self.clock = clock or UtcClock()
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occ TEXT NOT NULL,
                bid TEXT NOT NULL,
                ask TEXT NOT NULL,
                quote_ts TEXT NOT NULL,
                marked_at TEXT NOT NULL,
                delayed INTEGER NOT NULL,
                source TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_marked_at ON shadow_marks (marked_at)"
        )
        self._conn.commit()

    def append_quote(self, quote: OptionQuote, *, marked_at: datetime | None = None) -> ShadowMark:
        occ = normalize_occ(quote.option_symbol)
        if occ is None:
            raise ShadowMarkError("invalid_occ")
        stamp = as_utc(marked_at or self.clock.now())
        mark = ShadowMark(
            occ=occ,
            bid=format(quote.bid, "f"),
            ask=format(quote.ask, "f"),
            quote_ts=as_utc(quote.quote_ts),
            marked_at=stamp,
            delayed=bool(quote.delayed),
            source=str(quote.source),
        )
        cur = self._conn.execute(
            """
            INSERT INTO shadow_marks (
                occ, bid, ask, quote_ts, marked_at, delayed, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mark.occ,
                mark.bid,
                mark.ask,
                _iso(mark.quote_ts),
                _iso(mark.marked_at),
                1 if mark.delayed else 0,
                mark.source,
            ),
        )
        self._conn.commit()
        return ShadowMark(
            occ=mark.occ,
            bid=mark.bid,
            ask=mark.ask,
            quote_ts=mark.quote_ts,
            marked_at=mark.marked_at,
            delayed=mark.delayed,
            source=mark.source,
            mark_id=int(cur.lastrowid or 0) or None,
        )

    def iter_recent(self, *, limit: int = 100, occ: str | None = None) -> Iterator[ShadowMark]:
        if limit < 1:
            raise ShadowMarkError("limit_must_be_positive")
        sql = "SELECT * FROM shadow_marks"
        params: list[object] = []
        if occ is not None:
            sql += " WHERE occ = ?"
            params.append(occ)
        sql += " ORDER BY marked_at DESC, id DESC LIMIT ?"
        params.append(limit)
        for raw in self._conn.execute(sql, params):
            yield ShadowMark(
                mark_id=int(raw["id"]),
                occ=str(raw["occ"]),
                bid=str(raw["bid"]),
                ask=str(raw["ask"]),
                quote_ts=_parse_ts(str(raw["quote_ts"])),
                marked_at=_parse_ts(str(raw["marked_at"])),
                delayed=bool(raw["delayed"]),
                source=str(raw["source"]),
            )


def poll_shadow_marks(
    quotes: QuoteSource,
    book: ShadowMarkBook,
    occs: Iterable[str],
    *,
    now: datetime | None = None,
    last_poll: datetime | None = None,
    env: Mapping[str, str] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[ShadowMark]:
    """Poll due OCC quotes and append marks. Timeouts skip that OCC (fail-closed)."""
    stamp = as_utc(now or book.clock.now())
    cadence = shadow_mark_sec(env)
    if not due(last_poll, stamp, cadence_sec=cadence):
        return []
    marks: list[ShadowMark] = []
    for occ in bounded_occs(occs):
        try:
            quote = quotes.quote_option(occ)
        except (TimeoutFailClosedError, TimeoutError, ValueError) as exc:
            if on_error is not None:
                on_error(occ, exc)
            continue
        marks.append(book.append_quote(quote, marked_at=stamp))
    return marks


def marks_document(
    marks: list[ShadowMark],
    *,
    now: datetime,
    occ_count: int,
) -> dict[str, Any]:
    return {
        "source": "tradier_shadow_marks",
        "note": NEVER_ORDERS_NOTE,
        "as_of": as_utc(now).isoformat(),
        "cadence_sec": DEFAULT_SHADOW_MARK_SEC,
        "occ_count": occ_count,
        "mark_count": len(marks),
        "occs": sorted({m.occ for m in marks}),
        "places_orders": False,
        "pnl": None,
    }
