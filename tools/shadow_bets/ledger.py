"""Append-only shadow-bets ledger. Refuse rows → Tradier-cited marks.

Never invents NBBO. Never places orders. Observational labels only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from groktrading.quote_gate import normalize_occ
from groktrading.sit_match import parse_executed_at
from groktrading.timeutil import as_utc, session_date_pt
from tools.shadow_bets.config import (
    EVENTS_REL,
    I1_MAX_AGE_SEC,
    LABELS,
    LEDGER_REL,
    LIVE_GATE,
    MARK_SOURCES,
    PLACES_ORDERS,
    SCORE_NOTE,
    SESSION_REL,
    STAGES,
    WAKE_LATENCY_REASONS,
    PackPaths,
    ShadowBetsError,
    assert_i1_unlocked,
    pack_paths,
)

CONTRACT_MULTIPLIER = Decimal("100")


def isoformat(now: datetime) -> str:
    return as_utc(now).isoformat().replace("+00:00", "Z")


def parse_now(raw: str | datetime | None) -> datetime:
    if raw is None:
        from groktrading.timeutil import UTC

        return datetime.now(tz=UTC)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raise ShadowBetsError("now_naive", "--now must be timezone-aware ISO-8601")
        return as_utc(raw)
    parsed = parse_executed_at(raw)
    if parsed is None:
        raise ShadowBetsError("now_naive", "--now must be timezone-aware ISO-8601")
    return parsed


def session_key(now: datetime, session: str | date | None) -> str:
    if session is None or (isinstance(session, str) and not session.strip()):
        return session_date_pt(now).isoformat()
    if isinstance(session, date) and not isinstance(session, datetime):
        return session.isoformat()
    text = str(session).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ShadowBetsError("bad_session", "session must be YYYY-MM-DD") from exc


def _named(value: object) -> str:
    return str(value or "").strip()


def normalize_reason(value: object) -> str:
    return _named(value).lower().replace("-", "_")


def parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool) or isinstance(value, Mapping):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


def extract_occ(row: Mapping[str, Any]) -> str | None:
    raw = row.get("occ") or row.get("option_symbol") or row.get("symbol")
    text = _named(raw)
    if not text:
        return None
    occ = normalize_occ(text)
    if len(occ) < 5 or not occ.isalnum():
        return None
    return occ


def infer_label(row: Mapping[str, Any], *, i1_max_age_sec: float = I1_MAX_AGE_SEC) -> str:
    explicit = _named(row.get("label")).lower()
    if explicit in LABELS:
        return explicit
    reason = normalize_reason(row.get("reason") or row.get("refuse_reason"))
    executed = parse_executed_at(row.get("executed_at"))
    emitted = parse_executed_at(row.get("emitted_at"))
    consumed = parse_executed_at(row.get("consumed_at") or row.get("woken_at"))
    if reason in WAKE_LATENCY_REASONS:
        if executed is not None and emitted is not None and consumed is not None:
            emit_age = (emitted - executed).total_seconds()
            consume_age = (consumed - executed).total_seconds()
            if emit_age <= i1_max_age_sec and consume_age > i1_max_age_sec:
                return "yes_latency_fix_wake"
            if consume_age <= i1_max_age_sec:
                return "yes_fresh_wake"
            return "no_latency_fix_wake"
        # I1_stale backlog without hop clocks: Monday wake-latency default.
        return "yes_latency_fix_wake"
    return "no_latency_fix_wake"


def bet_id_for(session: str, occ: str, reason: str, explicit: object = None) -> str:
    named = _named(explicit)
    if named:
        return named
    why = normalize_reason(reason) or "refuse"
    return f"{session}:{occ}:{why}"


@dataclass
class ShadowBet:
    bet_id: str
    session: str
    occ: str
    reason: str
    label: str
    stage: str
    executed_at: str = ""
    emitted_at: str = ""
    consumed_at: str = ""
    refuse_ask: str | None = None
    mark_bid: str | None = None
    mark_ask: str | None = None
    mark_ts: str = ""
    mark_source: str = ""
    skip_reason: str = ""
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    live_gate: bool = LIVE_GATE
    places_orders: bool = PLACES_ORDERS
    invented: bool = False
    i1_max_age_sec: float = I1_MAX_AGE_SEC

    def scored(self) -> bool:
        return (
            self.stage == "marked"
            and not self.invented
            and parse_decimal(self.refuse_ask) is not None
            and parse_decimal(self.mark_bid) is not None
        )

    def one_lot_usd(self) -> Decimal | None:
        if not self.scored():
            return None
        ask = parse_decimal(self.refuse_ask)
        bid = parse_decimal(self.mark_bid)
        if ask is None or bid is None:
            return None
        return (bid - ask) * CONTRACT_MULTIPLIER

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "shadow_bet",
            "bet_id": self.bet_id,
            "session": self.session,
            "occ": self.occ,
            "reason": self.reason,
            "label": self.label,
            "stage": self.stage,
            "executed_at": self.executed_at,
            "emitted_at": self.emitted_at,
            "consumed_at": self.consumed_at,
            "refuse_ask": self.refuse_ask,
            "mark_bid": self.mark_bid,
            "mark_ask": self.mark_ask,
            "mark_ts": self.mark_ts,
            "mark_source": self.mark_source,
            "skip_reason": self.skip_reason,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": False,
            "i1_max_age_sec": I1_MAX_AGE_SEC,
            "unlock_i1": False,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ShadowBet:
        stage = _named(raw.get("stage")) or "opened"
        if stage not in STAGES:
            raise ShadowBetsError("unknown_stage", f"unknown stage: {stage}")
        label = _named(raw.get("label")) or "other"
        if label not in LABELS:
            raise ShadowBetsError("unknown_label", f"unknown observational label: {label}")
        occ = extract_occ(raw)
        if occ is None:
            raise ShadowBetsError("invalid_occ", "shadow bet requires an OCC")
        return cls(
            bet_id=_named(raw.get("bet_id")),
            session=_named(raw.get("session")),
            occ=occ,
            reason=_named(raw.get("reason")),
            label=label,
            stage=stage,
            executed_at=_named(raw.get("executed_at")),
            emitted_at=_named(raw.get("emitted_at")),
            consumed_at=_named(raw.get("consumed_at")),
            refuse_ask=_optional_price(raw.get("refuse_ask")),
            mark_bid=_optional_price(raw.get("mark_bid")),
            mark_ask=_optional_price(raw.get("mark_ask")),
            mark_ts=_named(raw.get("mark_ts")),
            mark_source=_named(raw.get("mark_source")),
            skip_reason=_named(raw.get("skip_reason")),
            note=_named(raw.get("note")),
            created_at=_named(raw.get("created_at")),
            updated_at=_named(raw.get("updated_at")),
        )


def _optional_price(value: object) -> str | None:
    parsed = parse_decimal(value)
    if parsed is None:
        return None
    return format(parsed, "f")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        doc = json.loads(text)
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


def _append_jsonl(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, sort_keys=True) + "\n")


def _write_json(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_rows(path: Path) -> list[dict[str, Any]]:
    """JSONL or a JSON list/object of refuse or mark rows."""
    if not path.is_file():
        raise ShadowBetsError("input_missing", f"file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] in "{[":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, list):
            return [row for row in doc if isinstance(row, dict)]
        if isinstance(doc, dict):
            for key in ("refuses", "marks", "rows", "bets"):
                nested = doc.get(key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
            return [doc]
    return _read_jsonl(path)


def load_bets(paths: PackPaths) -> dict[str, ShadowBet]:
    latest: dict[str, ShadowBet] = {}
    for row in _read_jsonl(paths.ledger):
        if row.get("kind") not in {None, "shadow_bet"}:
            continue
        if "bet_id" not in row:
            continue
        bet = ShadowBet.from_dict(row)
        latest[bet.bet_id] = bet
    return latest


def session_document(bets: Mapping[str, ShadowBet], session: str) -> dict[str, Any]:
    rows = [bet for bet in bets.values() if bet.session == session]
    return {
        "kind": "shadow_bets_session",
        "session": session,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "invented": False,
        "unlock_i1": False,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
        "count": len(rows),
        "bet_ids": sorted(bet.bet_id for bet in rows),
    }


def summarize_session(
    bets: Mapping[str, ShadowBet],
    *,
    session: str,
    now: datetime,
) -> dict[str, Any]:
    rows = [bet for bet in bets.values() if bet.session == session]
    labels = {label: 0 for label in LABELS}
    marked = 0
    scored = 0
    hits = 0
    one_lot = Decimal("0")
    for bet in rows:
        labels[bet.label] = labels.get(bet.label, 0) + 1
        if bet.stage == "marked":
            marked += 1
        usd = bet.one_lot_usd()
        if usd is None:
            continue
        scored += 1
        one_lot += usd
        if usd > 0:
            hits += 1
    return {
        "kind": "shadow_bets_summary",
        "session": session,
        "scored_at": isoformat(now),
        "opened": len(rows),
        "marked": marked,
        "unmarked": len(rows) - marked,
        "scored": scored,
        "hits": hits,
        "hit_rate": None if scored == 0 else float(hits / scored),
        "one_lot_usd": None if scored == 0 else format(one_lot, "f"),
        "labels": labels,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "invented": False,
        "unlock_i1": False,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
        "pnl": None,
        "note": SCORE_NOTE,
    }


class ShadowBook:
    """Pack-rooted refuse → mark ledger. Writes evidence JSONL."""

    def __init__(self, pack: str | Path | None = None) -> None:
        self.paths = pack_paths(pack)
        self._bets = load_bets(self.paths)

    @property
    def bets(self) -> dict[str, ShadowBet]:
        return self._bets

    def _persist(self, bet: ShadowBet, action: str, now: datetime) -> ShadowBet:
        bet.live_gate = LIVE_GATE
        bet.places_orders = PLACES_ORDERS
        bet.invented = False
        bet.i1_max_age_sec = I1_MAX_AGE_SEC
        bet.updated_at = isoformat(now)
        snapshot = bet.to_dict()
        _append_jsonl(self.paths.ledger, snapshot)
        event = {
            "kind": "shadow_bets_event",
            "action": action,
            "bet_id": bet.bet_id,
            "session": bet.session,
            "occ": bet.occ,
            "label": bet.label,
            "stage": bet.stage,
            "at": bet.updated_at,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "unlock_i1": False,
        }
        _append_jsonl(self.paths.events, event)
        self._bets[bet.bet_id] = bet
        _write_json(self.paths.session, session_document(self._bets, bet.session))
        return bet

    def open_from_refuses(
        self,
        refuses: list[Mapping[str, Any]] | Path,
        *,
        session: str,
        now: datetime | str | None = None,
        i1_max_age_sec: float | None = None,
    ) -> dict[str, Any]:
        stamp = parse_now(now)
        key = session_key(stamp, session)
        i1 = assert_i1_unlocked(i1_max_age_sec)
        rows = load_rows(refuses) if isinstance(refuses, Path) else list(refuses)
        opened: list[ShadowBet] = []
        skipped: list[dict[str, Any]] = []
        for row in rows:
            occ = extract_occ(row)
            reason = _named(row.get("reason") or row.get("refuse_reason")) or "I1_stale"
            if occ is None:
                skipped.append({"reason": "invalid_occ", "row": dict(row)})
                continue
            bet_id = bet_id_for(key, occ, reason, row.get("bet_id") or row.get("id"))
            if bet_id in self._bets:
                skipped.append({"reason": "already_open", "bet_id": bet_id, "occ": occ})
                continue
            created = isoformat(stamp)
            bet = ShadowBet(
                bet_id=bet_id,
                session=key,
                occ=occ,
                reason=reason,
                label=infer_label(row, i1_max_age_sec=i1),
                stage="opened",
                executed_at=_named(row.get("executed_at")),
                emitted_at=_named(row.get("emitted_at")),
                consumed_at=_named(row.get("consumed_at") or row.get("woken_at")),
                refuse_ask=_optional_price(
                    row.get("refuse_ask") or row.get("ask") or row.get("print_ask")
                ),
                note=_named(row.get("note")),
                created_at=created,
                updated_at=created,
            )
            opened.append(self._persist(bet, "open-from-refuses", stamp))
        return {
            "kind": "shadow_bets_open",
            "session": key,
            "opened": len(opened),
            "skipped": len(skipped),
            "bets": [bet.to_dict() for bet in opened],
            "skip_rows": skipped,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": False,
            "unlock_i1": False,
            "i1_max_age_sec": I1_MAX_AGE_SEC,
        }

    def mark_session(
        self,
        marks: list[Mapping[str, Any]] | Path,
        *,
        session: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        stamp = parse_now(now)
        key = session_key(stamp, session)
        rows = load_rows(marks) if isinstance(marks, Path) else list(marks)
        by_occ: dict[str, Mapping[str, Any]] = {}
        rejected: list[dict[str, Any]] = []
        for row in rows:
            occ = extract_occ(row)
            if occ is None:
                rejected.append({"reason": "invalid_occ"})
                continue
            if row.get("invented") is True:
                rejected.append({"reason": "invented_nbbo_forbidden", "occ": occ})
                continue
            source = _named(row.get("source") or row.get("mark_source"))
            if source and source not in MARK_SOURCES:
                rejected.append({"reason": "mark_source_not_tradier", "occ": occ, "source": source})
                continue
            bid = _optional_price(row.get("mark_bid") or row.get("bid"))
            ask = _optional_price(row.get("mark_ask") or row.get("ask"))
            if bid is None:
                rejected.append({"reason": "missing_mark", "occ": occ})
                continue
            if occ not in by_occ:
                by_occ[occ] = {
                    **dict(row),
                    "occ": occ,
                    "mark_bid": bid,
                    "mark_ask": ask,
                    "mark_source": source or "tradier_production",
                    "mark_ts": _named(row.get("mark_ts") or row.get("quote_ts")),
                }
        marked: list[ShadowBet] = []
        unmarked: list[str] = []
        for bet in list(self._bets.values()):
            if bet.session != key:
                continue
            row = by_occ.get(bet.occ)
            if row is None:
                if bet.stage != "marked":
                    unmarked.append(bet.bet_id)
                continue
            bet.stage = "marked"
            bet.mark_bid = _optional_price(row.get("mark_bid"))
            bet.mark_ask = _optional_price(row.get("mark_ask"))
            bet.mark_ts = _named(row.get("mark_ts"))
            bet.mark_source = _named(row.get("mark_source"))
            bet.skip_reason = ""
            marked.append(self._persist(bet, "mark-session", stamp))
        return {
            "kind": "shadow_bets_mark",
            "session": key,
            "marked": len(marked),
            "unmarked": len(unmarked),
            "rejected_marks": rejected,
            "bets": [bet.to_dict() for bet in marked],
            "unmarked_ids": unmarked,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": False,
            "unlock_i1": False,
            "i1_max_age_sec": I1_MAX_AGE_SEC,
            "note": "Missing marks stay unmarked. NBBO is never invented.",
        }

    def summarize(self, *, session: str, now: datetime | str | None = None) -> dict[str, Any]:
        stamp = parse_now(now)
        key = session_key(stamp, session)
        return summarize_session(self._bets, session=key, now=stamp)

    def run_session(
        self,
        *,
        session: str,
        refuses: Path | list[Mapping[str, Any]] | None = None,
        marks: Path | list[Mapping[str, Any]] | None = None,
        now: datetime | str | None = None,
        i1_max_age_sec: float | None = None,
    ) -> dict[str, Any]:
        stamp = parse_now(now)
        key = session_key(stamp, session)
        opened = (
            self.open_from_refuses(
                refuses, session=key, now=stamp, i1_max_age_sec=i1_max_age_sec
            )
            if refuses is not None
            else None
        )
        marked = (
            self.mark_session(marks, session=key, now=stamp) if marks is not None else None
        )
        summary = self.summarize(session=key, now=stamp)
        return {
            "kind": "shadow_bets_run_session",
            "session": key,
            "open": opened,
            "mark": marked,
            "summary": summary,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": False,
            "unlock_i1": False,
            "i1_max_age_sec": I1_MAX_AGE_SEC,
        }


PACK_FILES = (EVENTS_REL, LEDGER_REL, SESSION_REL)
