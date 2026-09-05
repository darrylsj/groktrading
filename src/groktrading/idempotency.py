"""Durable inbox/outbox idempotency (SQLite WAL).

Helsinki's live emitter currently uses an in-memory ~90s debounce. That lets
the same digest fan out across a weekend restart. This module is the package
replacement for both the Helsinki webhook emitter (outbox) and the Grok
consumer (inbox).

RTH: exact idempotency_key uniqueness plus an optional short debounce.
After-hours / weekend: coalesce by digest so AH spam does not fan out.

No secrets are stored. Tests use a temp file or :memory:.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from groktrading.timeutil import UTC, as_utc, market_session_kind, should_coalesce_digest

Scope = Literal["inbox", "outbox"]
RTH_DEBOUNCE = timedelta(seconds=90)


def payload_digest(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class IdempotencyDecision:
    accept: bool
    reason: str
    scope: Scope
    idempotency_key: str
    digest: str
    count: int
    session_kind: str


class DurableIdempotency:
    """SQLite WAL keyed inbox/outbox."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                scope TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                digest TEXT NOT NULL,
                event_type TEXT NOT NULL,
                first_seen_ts TEXT NOT NULL,
                last_seen_ts TEXT NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY (scope, idempotency_key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_idem_digest
            ON idempotency (scope, event_type, digest)
            """
        )
        self._conn.commit()

    def decide(
        self,
        *,
        scope: Scope,
        idempotency_key: str,
        payload: dict[str, Any],
        event_type: str,
        now: datetime,
        clock_state: str | None = None,
        rth_debounce: timedelta = RTH_DEBOUNCE,
    ) -> IdempotencyDecision:
        stamp = as_utc(now)
        digest = payload_digest(payload)
        kind = market_session_kind(stamp, clock_state)

        existing_key = self._fetch_key(scope, idempotency_key)
        if existing_key is not None:
            self._bump(scope, idempotency_key, stamp)
            return IdempotencyDecision(
                accept=False,
                reason="idempotent_replay",
                scope=scope,
                idempotency_key=idempotency_key,
                digest=digest,
                count=int(existing_key["count"]) + 1,
                session_kind=kind,
            )

        if should_coalesce_digest(stamp, clock_state):
            twin = self._fetch_digest(scope, event_type, digest)
            if twin is not None:
                self._bump(scope, str(twin["idempotency_key"]), stamp)
                return IdempotencyDecision(
                    accept=False,
                    reason="weekend_or_ah_digest_coalesce",
                    scope=scope,
                    idempotency_key=idempotency_key,
                    digest=digest,
                    count=int(twin["count"]) + 1,
                    session_kind=kind,
                )

        last_event = self._last_event(scope, event_type)
        if last_event is not None and kind == "rth":
            last_ts = datetime.fromisoformat(str(last_event["last_seen_ts"]))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=UTC)
            if stamp - last_ts < rth_debounce:
                return IdempotencyDecision(
                    accept=False,
                    reason="rth_debounce",
                    scope=scope,
                    idempotency_key=idempotency_key,
                    digest=digest,
                    count=1,
                    session_kind=kind,
                )

        self._insert(scope, idempotency_key, digest, event_type, stamp)
        return IdempotencyDecision(
            accept=True,
            reason="accepted",
            scope=scope,
            idempotency_key=idempotency_key,
            digest=digest,
            count=1,
            session_kind=kind,
        )

    def claim_inbox(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        event_type: str,
        now: datetime,
        clock_state: str | None = None,
    ) -> IdempotencyDecision:
        return self.decide(
            scope="inbox",
            idempotency_key=idempotency_key,
            payload=payload,
            event_type=event_type,
            now=now,
            clock_state=clock_state,
        )

    def claim_outbox(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        event_type: str,
        now: datetime,
        clock_state: str | None = None,
    ) -> IdempotencyDecision:
        return self.decide(
            scope="outbox",
            idempotency_key=idempotency_key,
            payload=payload,
            event_type=event_type,
            now=now,
            clock_state=clock_state,
        )

    def _fetch_key(self, scope: Scope, key: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT * FROM idempotency WHERE scope=? AND idempotency_key=?",
                (scope, key),
            ).fetchone(),
        )

    def _fetch_digest(self, scope: Scope, event_type: str, digest: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT * FROM idempotency WHERE scope=? AND event_type=? AND digest=?",
                (scope, event_type, digest),
            ).fetchone(),
        )

    def _last_event(self, scope: Scope, event_type: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                """
                SELECT * FROM idempotency
                WHERE scope=? AND event_type=?
                ORDER BY last_seen_ts DESC LIMIT 1
                """,
                (scope, event_type),
            ).fetchone(),
        )

    def _insert(
        self,
        scope: Scope,
        key: str,
        digest: str,
        event_type: str,
        stamp: datetime,
    ) -> None:
        iso = stamp.isoformat()
        self._conn.execute(
            """
            INSERT INTO idempotency (
                scope, idempotency_key, digest, event_type, first_seen_ts, last_seen_ts, count
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (scope, key, digest, event_type, iso, iso),
        )
        self._conn.commit()

    def _bump(self, scope: Scope, key: str, stamp: datetime) -> None:
        self._conn.execute(
            """
            UPDATE idempotency
            SET last_seen_ts=?, count=count+1
            WHERE scope=? AND idempotency_key=?
            """,
            (stamp.isoformat(), scope, key),
        )
        self._conn.commit()
