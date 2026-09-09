"""Append-only UW flow ledger (SQLite WAL).

Helsinki is a sensor farm: listen always, decide never. This module stores
Unusual Whales option-trades (and later flow-alerts) rows on the hot disk
window. It does **not** place orders and does **not** emit webhooks.

``sit_match`` emission stays fail-closed in ``groktrading.sit_match``:
``executed_at`` age ≤ ``SIT_MATCH_MAX_AGE_SEC`` (default 60s). Stale prints
may still be **stored** here for research; they must not wake Grok.

No secrets. Tests use a temp file or ``:memory:``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from groktrading.redaction import redact_mapping
from groktrading.sit_match import SitMatchFreshness, evaluate_sit_match_freshness, parse_executed_at
from groktrading.timeutil import UTC, as_utc

FlowSource = Literal["option-trades", "flow-alerts"]
FLOW_SOURCES: frozenset[str] = frozenset({"option-trades", "flow-alerts"})
OPTION_TYPES: frozenset[str] = frozenset({"call", "put"})


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


@dataclass(frozen=True)
class FlowRow:
    """One UW flow print. ``raw_digest`` is a hash, never the raw payload."""

    executed_at: datetime
    ticker: str
    occ: str
    print: str
    nbbo_ask: str
    option_type: Literal["call", "put"]
    ingested_at: datetime
    source: FlowSource
    raw_digest: str
    row_id: int | None = None


class FlowLedgerError(ValueError):
    """Fail-closed ledger input (missing clock, bad source, junk prices)."""


def flow_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 of redacted canonical JSON. Secrets never enter the digest input."""
    body = json.dumps(
        redact_mapping(dict(payload)),
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _require_text(value: object, field: str) -> str:
    if value is None:
        raise FlowLedgerError(f"missing_{field}")
    text = str(value).strip()
    if not text:
        raise FlowLedgerError(f"missing_{field}")
    return text


def _require_price(value: object, field: str) -> str:
    text = _require_text(value, field)
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise FlowLedgerError(f"unparseable_{field}") from exc
    if amount < 0:
        raise FlowLedgerError(f"negative_{field}")
    return format(amount, "f")


def _require_option_type(value: object) -> Literal["call", "put"]:
    text = _require_text(value, "option_type").lower()
    if text in {"c", "call", "calls"}:
        return "call"
    if text in {"p", "put", "puts"}:
        return "put"
    raise FlowLedgerError("invalid_option_type")


def _require_source(value: object) -> FlowSource:
    text = _require_text(value, "source")
    if text not in FLOW_SOURCES:
        raise FlowLedgerError("invalid_source")
    return cast(FlowSource, text)


def _first(payload: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        raw = payload.get(key)
        if raw not in (None, ""):
            return raw
    return None


def draft_from_uw_row(
    payload: Mapping[str, Any],
    *,
    ingested_at: datetime,
    source: FlowSource = "option-trades",
) -> FlowRow:
    """Map a documented UW option-trades (or later flow-alerts) row.

    Required: parseable ``executed_at``, ticker, OCC, print, nbbo ask, call/put.
    Does not invent missing fields. Stale ``executed_at`` is allowed to store.
    """
    executed = parse_executed_at(
        _first(payload, "executed_at", "timestamp", "created_at")
    )
    if executed is None:
        raise FlowLedgerError("sit_match_missing_or_unparseable_executed_at")
    ticker = _require_text(
        _first(payload, "ticker", "underlying", "ticker_symbol"), "ticker"
    ).upper()
    occ = _require_text(
        _first(payload, "occ", "option_symbol", "option_chain_id"), "occ"
    ).upper()
    print_px = _require_price(
        _first(payload, "print", "price", "trade_price", "avg_price"), "print"
    )
    ask = _require_price(_first(payload, "nbbo_ask", "ask"), "nbbo_ask")
    option_type = _require_option_type(_first(payload, "option_type", "put_call", "type"))
    src = _require_source(source)
    return FlowRow(
        executed_at=executed,
        ticker=ticker,
        occ=occ,
        print=print_px,
        nbbo_ask=ask,
        option_type=option_type,
        ingested_at=as_utc(ingested_at),
        source=src,
        raw_digest=flow_digest(payload),
    )


def evaluate_row_sit_match(
    row: FlowRow,
    now: datetime,
    *,
    max_age_sec: float | None = None,
    env: Mapping[str, str] | None = None,
) -> SitMatchFreshness:
    """sit_match gate for a stored row. Stale storage ≠ sit_match emit."""
    return evaluate_sit_match_freshness(
        row.executed_at,
        now,
        max_age_sec=max_age_sec,
        env=env,
    )


def _iso(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_stored_ts(value: str) -> datetime:
    parsed = parse_executed_at(value)
    if parsed is None:
        raise FlowLedgerError("corrupt_ledger_timestamp")
    return parsed


class FlowLedger:
    """SQLite WAL keyed by ``(source, raw_digest)``. Append-only; purge is explicit."""

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
            CREATE TABLE IF NOT EXISTS flow_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                executed_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                occ TEXT NOT NULL,
                print TEXT NOT NULL,
                nbbo_ask TEXT NOT NULL,
                option_type TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_digest TEXT NOT NULL,
                UNIQUE (source, raw_digest)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_ingested_at ON flow_rows (ingested_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_executed_at ON flow_rows (executed_at)"
        )
        self._conn.commit()

    def append_row(
        self,
        payload: Mapping[str, Any] | FlowRow,
        *,
        source: FlowSource | None = None,
        ingested_at: datetime | None = None,
    ) -> FlowRow:
        """Insert one row. Duplicate ``(source, raw_digest)`` returns the existing row."""
        if isinstance(payload, FlowRow):
            row = payload
            if source is not None and source != row.source:
                raise FlowLedgerError("source_mismatch")
        else:
            stamp = as_utc(ingested_at or self.clock.now())
            src: FlowSource = source or "option-trades"
            row = draft_from_uw_row(payload, ingested_at=stamp, source=src)
        existing = self._fetch_digest(row.source, row.raw_digest)
        if existing is not None:
            return existing
        cur = self._conn.execute(
            """
            INSERT INTO flow_rows (
                executed_at, ticker, occ, print, nbbo_ask, option_type,
                ingested_at, source, raw_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _iso(row.executed_at),
                row.ticker,
                row.occ,
                row.print,
                row.nbbo_ask,
                row.option_type,
                _iso(row.ingested_at),
                row.source,
                row.raw_digest,
            ),
        )
        self._conn.commit()
        inserted = cur.lastrowid
        if inserted is None:
            raise FlowLedgerError("insert_missing_row_id")
        return FlowRow(
            executed_at=row.executed_at,
            ticker=row.ticker,
            occ=row.occ,
            print=row.print,
            nbbo_ask=row.nbbo_ask,
            option_type=row.option_type,
            ingested_at=row.ingested_at,
            source=row.source,
            raw_digest=row.raw_digest,
            row_id=int(inserted),
        )

    def iter_recent(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        source: FlowSource | None = None,
    ) -> Iterator[FlowRow]:
        """Newest ingested first. ``since`` filters ``ingested_at`` (inclusive)."""
        if limit < 1:
            raise FlowLedgerError("limit_must_be_positive")
        sql = "SELECT * FROM flow_rows"
        params: list[object] = []
        clauses: list[str] = []
        if since is not None:
            clauses.append("ingested_at >= ?")
            params.append(_iso(since))
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ingested_at DESC, id DESC LIMIT ?"
        params.append(limit)
        for raw in self._conn.execute(sql, params):
            yield self._from_sql(raw)

    def purge_older_than(self, days: int, *, now: datetime | None = None) -> int:
        """Delete rows whose ``ingested_at`` is older than ``days``.

        Intended after a verified Box cold-rotate of the closed day pack.
        ``days`` must be ≥ 1. This is the only delete path.
        """
        if days < 1:
            raise FlowLedgerError("purge_days_must_be_positive")
        stamp = as_utc(now or self.clock.now())
        cutoff = stamp - timedelta(days=days)
        cur = self._conn.execute(
            "DELETE FROM flow_rows WHERE ingested_at < ?",
            (_iso(cutoff),),
        )
        self._conn.commit()
        return int(cur.rowcount)

    def _fetch_digest(self, source: str, digest: str) -> FlowRow | None:
        raw = self._conn.execute(
            "SELECT * FROM flow_rows WHERE source=? AND raw_digest=?",
            (source, digest),
        ).fetchone()
        if raw is None:
            return None
        return self._from_sql(cast(sqlite3.Row, raw))

    def _from_sql(self, raw: sqlite3.Row) -> FlowRow:
        option_type = str(raw["option_type"])
        if option_type not in OPTION_TYPES:
            raise FlowLedgerError("corrupt_option_type")
        source = str(raw["source"])
        if source not in FLOW_SOURCES:
            raise FlowLedgerError("corrupt_source")
        return FlowRow(
            row_id=int(raw["id"]),
            executed_at=_parse_stored_ts(str(raw["executed_at"])),
            ticker=str(raw["ticker"]),
            occ=str(raw["occ"]),
            print=str(raw["print"]),
            nbbo_ask=str(raw["nbbo_ask"]),
            option_type=cast(Literal["call", "put"], option_type),
            ingested_at=_parse_stored_ts(str(raw["ingested_at"])),
            source=cast(FlowSource, source),
            raw_digest=str(raw["raw_digest"]),
        )
