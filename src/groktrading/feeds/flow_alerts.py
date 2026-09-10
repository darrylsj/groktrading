"""UW flow-alerts REST poller — append-only ledger, emit on new alert id.

Helsinki listens; Grok Bot decides. This helper polls the documented
``GET /api/option-trades/flow-alerts`` path (unusualwhales.com/skill.md).
It does **not** invent unofficial aliases and does **not** place orders.

Cadence: 15–30s (``FLOW_ALERTS_POLL_SEC``, default 20). Every poll may
append parseable rows to ``flow_ledger`` with ``source=flow-alerts``.
A webhook / material callback fires only on a **new alert id**, not on
every poll of the same rolling window.

If a row is sit_match-shaped (has ``executed_at`` / OCC / print), reuse
``groktrading.sit_match`` freshness before treating it as a sit_match
emit. Stale rows may still be stored. Missing alert id → no emit
(fail-closed; digest-only store is allowed).

No live HTTP in CI. Transport is injected.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from groktrading.cadence import env_seconds
from groktrading.feeds.unusual_whales import (
    UW_FLOW_ALERTS_PATH,
    UnusualWhalesClient,
    uw_data_rows,
)
from groktrading.flow_ledger import (
    EXECUTION_CLOCK_KEY,
    OCC_ALIAS_KEYS,
    FlowLedger,
    FlowLedgerError,
    FlowRow,
)
from groktrading.io_atomic import write_json_atomic
from groktrading.sit_match import (
    SIT_MATCH_EVENT,
    SitMatchFreshness,
    evaluate_sit_match_freshness,
    evaluate_sit_match_payload,
)
from groktrading.timeutil import UTC, as_utc

FLOW_ALERT_EVENT = "flow_alert"
FLOW_ALERTS_POLL_ENV = "FLOW_ALERTS_POLL_SEC"
DEFAULT_FLOW_ALERTS_POLL_SEC = 20.0
FLOW_ALERTS_POLL_LO = 15.0
FLOW_ALERTS_POLL_HI = 30.0
DEFAULT_ALERT_LIMIT = "50"
NEVER_ORDERS_NOTE = (
    "UW flow-alerts poller appends to the hot ledger and emits material "
    "only on a new alert id. Never places orders. Grok Bot decides."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def flow_alerts_poll_sec(env: Mapping[str, str] | None = None) -> float:
    return env_seconds(
        env,
        FLOW_ALERTS_POLL_ENV,
        default=DEFAULT_FLOW_ALERTS_POLL_SEC,
        lo=FLOW_ALERTS_POLL_LO,
        hi=FLOW_ALERTS_POLL_HI,
    )


def extract_alert_id(payload: Mapping[str, Any]) -> str | None:
    """Documented / common UW id keys. Empty → None (no invent)."""
    for key in ("id", "alert_id", "flow_id"):
        raw = payload.get(key)
        if raw in (None, ""):
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def is_sit_match_shaped(payload: Mapping[str, Any]) -> bool:
    """True when the row looks like a sit_match print (freshness applies).

    OCC aliases include live UW ``option_chain``. The execution clock is
    ``executed_at`` only — ``created_at`` / ``timestamp`` do not count.
    """
    event = str(payload.get("event") or "").strip().lower()
    if event == SIT_MATCH_EVENT:
        return True
    if payload.get("sit_confirmations") not in (None, "", 0, "0"):
        return True
    has_print = any(payload.get(k) not in (None, "") for k in ("print", "price", "avg_price"))
    has_ask = any(payload.get(k) not in (None, "") for k in ("nbbo_ask", "ask"))
    has_occ = any(payload.get(k) not in (None, "") for k in OCC_ALIAS_KEYS)
    has_ts = payload.get(EXECUTION_CLOCK_KEY) not in (None, "")
    return bool(has_print and has_ask and has_occ and has_ts)


@dataclass
class SeenAlertStore:
    """Idempotency for emit: remember alert ids. Optional atomic JSON persist."""

    path: Path | None = None
    _ids: set[str] = field(default_factory=set)
    cap: int = 10_000

    def __post_init__(self) -> None:
        if self.path is None:
            return
        path = Path(self.path)
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return
        ids = raw.get("ids") if isinstance(raw, dict) else raw
        if isinstance(ids, list):
            self._ids = {str(x) for x in ids if str(x).strip()}

    def known(self, alert_id: str) -> bool:
        return alert_id in self._ids

    def forget(self, alert_id: str) -> None:
        """Drop an id so a failed delivery can retry (H1 outbox)."""
        if alert_id not in self._ids:
            return
        self._ids.discard(alert_id)
        self._persist()

    def remember(self, alert_id: str) -> bool:
        """Return True if this id is newly recorded (first time)."""
        if alert_id in self._ids:
            return False
        self._ids.add(alert_id)
        if len(self._ids) > self.cap:
            # Drop an arbitrary oldest-ish slice; persist is a set, not a queue.
            extra = len(self._ids) - self.cap
            for item in list(self._ids)[:extra]:
                self._ids.discard(item)
        self._persist()
        return True

    def _persist(self) -> None:
        if self.path is None:
            return
        write_json_atomic(Path(self.path), {"ids": sorted(self._ids)})


@dataclass(frozen=True)
class FlowAlertHit:
    alert_id: str | None
    row: FlowRow | None
    stored: bool
    is_new_id: bool
    emit: bool
    event_type: str | None
    skip_reason: str | None
    sit_match: SitMatchFreshness | None


@dataclass(frozen=True)
class FlowAlertPollResult:
    fetched: int
    stored: int
    new_ids: int
    emitted: int
    skipped: int
    hits: tuple[FlowAlertHit, ...]
    cadence_sec: float
    path: str


def _sit_match_for_row(
    payload: Mapping[str, Any],
    row: FlowRow | None,
    now: datetime,
    env: Mapping[str, str] | None,
) -> SitMatchFreshness:
    if row is not None:
        return evaluate_sit_match_freshness(row.executed_at, now, env=env)
    return evaluate_sit_match_payload(payload, now, env=env)


def poll_flow_alerts(
    client: UnusualWhalesClient,
    ledger: FlowLedger,
    seen: SeenAlertStore,
    *,
    now: datetime | None = None,
    path: str = UW_FLOW_ALERTS_PATH,
    limit: str = DEFAULT_ALERT_LIMIT,
    env: Mapping[str, str] | None = None,
    on_material: Callable[[FlowAlertHit], None] | None = None,
    emit_sit_match: bool = False,
) -> FlowAlertPollResult:
    """One poll. Store parseable rows; emit only on a new alert id.

    ``emit_sit_match``: if True and the row is sit_match-shaped, the material
    event is ``sit_match`` **only** when freshness allows. Default material
    event is ``flow_alert`` (not a sit_match spray).
    """
    stamp = as_utc(now or client.clock.now())
    cadence = flow_alerts_poll_sec(env)
    _status, body = client.get_documented_path(path, params={"limit": str(limit)})
    rows = uw_data_rows(body)
    hits: list[FlowAlertHit] = []
    stored_n = 0
    new_n = 0
    emit_n = 0
    skip_n = 0
    for payload in rows:
        alert_id = extract_alert_id(payload)
        already = alert_id is not None and seen.known(alert_id)
        row: FlowRow | None = None
        stored = False
        try:
            # H1: append (durable) before marking seen.
            row = ledger.append_row(payload, source="flow-alerts", ingested_at=stamp)
            stored = True
            stored_n += 1
        except FlowLedgerError:
            stored = False
        shaped = is_sit_match_shaped(payload)
        freshness = _sit_match_for_row(payload, row, stamp, env) if shaped else None
        emit = False
        event: str | None = None
        skip: str | None = None
        if alert_id is None:
            skip = "missing_alert_id"
        elif already:
            skip = "duplicate_alert_id"
        elif not stored:
            skip = "store_failed"
        elif emit_sit_match and shaped:
            if freshness is not None and freshness.allow:
                emit = True
                event = SIT_MATCH_EVENT
            else:
                skip = freshness.reason if freshness is not None else "sit_match_blocked"
        else:
            emit = True
            event = FLOW_ALERT_EVENT
        hit = FlowAlertHit(
            alert_id=alert_id,
            row=row,
            stored=stored,
            is_new_id=False,
            emit=emit,
            event_type=event,
            skip_reason=skip,
            sit_match=freshness,
        )
        delivered = True
        if emit and on_material is not None:
            try:
                on_material(hit)
            except Exception:
                delivered = False
                emit = False
                skip = "delivery_failed"
                event = None
                hit = FlowAlertHit(
                    alert_id=alert_id,
                    row=row,
                    stored=stored,
                    is_new_id=False,
                    emit=False,
                    event_type=None,
                    skip_reason=skip,
                    sit_match=freshness,
                )
        is_new = False
        if alert_id is not None and not already and stored:
            if emit and delivered:
                is_new = seen.remember(alert_id)
            elif skip not in {None, "store_failed", "delivery_failed"}:
                is_new = seen.remember(alert_id)
        if is_new:
            new_n += 1
            hit = FlowAlertHit(
                alert_id=alert_id,
                row=row,
                stored=stored,
                is_new_id=True,
                emit=emit,
                event_type=event,
                skip_reason=skip,
                sit_match=freshness,
            )
        hits.append(hit)
        if emit:
            emit_n += 1
        if skip is not None:
            skip_n += 1
    return FlowAlertPollResult(
        fetched=len(rows),
        stored=stored_n,
        new_ids=new_n,
        emitted=emit_n,
        skipped=skip_n,
        hits=tuple(hits),
        cadence_sec=cadence,
        path=path,
    )


def state_document(
    result: FlowAlertPollResult | None,
    *,
    now: datetime,
    seen_count: int = 0,
) -> dict[str, Any]:
    stamp = as_utc(now)
    return {
        "source": "uw_flow_alerts",
        "path": UW_FLOW_ALERTS_PATH,
        "note": NEVER_ORDERS_NOTE,
        "as_of": stamp.isoformat(),
        "cadence_sec": result.cadence_sec if result is not None else DEFAULT_FLOW_ALERTS_POLL_SEC,
        "fetched": result.fetched if result is not None else 0,
        "stored": result.stored if result is not None else 0,
        "new_ids": result.new_ids if result is not None else 0,
        "emitted": result.emitted if result is not None else 0,
        "seen_alert_ids": seen_count,
        "places_orders": False,
        "live_http": False,
    }
