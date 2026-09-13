"""Append-only hypothesis ledger. Observational — never places orders."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from groktrading.timeutil import session_date_pt
from tools.strategy_factory.config import (
    ACTIVE_REL,
    EVENTS_REL,
    FORWARD,
    KILL_FROM,
    LEDGER_REL,
    LIVE_GATE,
    OPEN_STAGES,
    PLACES_ORDERS,
    REJECT_FROM,
    RETIRE_FROM,
    STAGES,
    TERMINAL_STAGES,
    DeskConfig,
    FactoryError,
    PackPaths,
    load_config,
    pack_paths,
)
from tools.strategy_factory.confirm import (
    Confirmation,
    assert_hyp_id,
    isoformat,
    parse_confirmation,
    parse_now,
    unique_sources,
)

SCORE_NOTE = (
    "Observational strategy-factory score. live_gate=false always. "
    "No broker calls. No invented prices or P&L. "
    "Does not replace live_order_gate. STO/I4 stay on the dated unlock plan."
)
CLOSE_ACTION = {
    "rejected": "reject",
    "killed": "kill",
    "retired": "retire",
}


def _session_key(now: datetime, session: str | date | None) -> str:
    if session is None or (isinstance(session, str) and not session.strip()):
        return session_date_pt(now).isoformat()
    if isinstance(session, date) and not isinstance(session, datetime):
        return session.isoformat()
    text = str(session).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise FactoryError("bad_session", "session must be YYYY-MM-DD") from exc


def _named(value: str | None) -> str:
    return (value or "").strip()


@dataclass
class Hypothesis:
    hyp_id: str
    category: str
    title: str
    stage: str
    session: str
    mechanism: str = ""
    falsifier: str = ""
    note: str = ""
    confirmations: list[Confirmation] = field(default_factory=list)
    reason: str = ""
    created_at: str = ""
    updated_at: str = ""
    live_gate: bool = LIVE_GATE
    places_orders: bool = PLACES_ORDERS
    invented: bool = False

    def confirmation_sources(self) -> frozenset[str]:
        return unique_sources(self.confirmations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "strategy_factory_hypothesis",
            "hyp_id": self.hyp_id,
            "category": self.category,
            "title": self.title,
            "stage": self.stage,
            "session": self.session,
            "mechanism": self.mechanism,
            "falsifier": self.falsifier,
            "note": self.note,
            "confirmations": [item.to_dict() for item in self.confirmations],
            "confirmation_sources": sorted(self.confirmation_sources()),
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": False,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Hypothesis:
        confirmations = [
            Confirmation.from_dict(item)
            for item in raw.get("confirmations") or []
            if isinstance(item, Mapping)
        ]
        stage = str(raw.get("stage", "")).strip()
        if stage not in STAGES:
            raise FactoryError("unknown_stage", f"unknown stage: {stage}")
        return cls(
            hyp_id=assert_hyp_id(str(raw.get("hyp_id", ""))),
            category=str(raw.get("category", "")).strip(),
            title=str(raw.get("title", "")).strip(),
            stage=stage,
            session=str(raw.get("session", "")).strip(),
            mechanism=_named(str(raw.get("mechanism", "") or "")),
            falsifier=_named(str(raw.get("falsifier", "") or "")),
            note=_named(str(raw.get("note", "") or "")),
            confirmations=confirmations,
            reason=_named(str(raw.get("reason", "") or "")),
            created_at=str(raw.get("created_at", "") or ""),
            updated_at=str(raw.get("updated_at", "") or ""),
            live_gate=LIVE_GATE,
            places_orders=PLACES_ORDERS,
            invented=False,
        )


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


def load_hypotheses(paths: PackPaths) -> dict[str, Hypothesis]:
    latest: dict[str, Hypothesis] = {}
    for row in _read_jsonl(paths.ledger):
        if row.get("kind") not in {None, "strategy_factory_hypothesis"}:
            continue
        if "hyp_id" not in row:
            continue
        hyp = Hypothesis.from_dict(row)
        latest[hyp.hyp_id] = hyp
    return latest


def active_document(hyps: Mapping[str, Hypothesis]) -> dict[str, Any]:
    sessions: dict[str, dict[str, list[str]]] = {}
    for hyp in hyps.values():
        if hyp.stage not in OPEN_STAGES:
            continue
        by_cat = sessions.setdefault(hyp.session, {})
        by_cat.setdefault(hyp.category, []).append(hyp.hyp_id)
    for by_cat in sessions.values():
        for names in by_cat.values():
            names.sort()
    return {
        "kind": "strategy_factory_active",
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "sessions": sessions,
    }


def score_day(
    hyps: Mapping[str, Hypothesis],
    *,
    session: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = isoformat(parse_now(now))
    rows = [hyp for hyp in hyps.values() if hyp.session == session]
    counts = {stage: 0 for stage in STAGES}
    confirmations = 0
    for hyp in rows:
        counts[hyp.stage] = counts.get(hyp.stage, 0) + 1
        confirmations += len(hyp.confirmation_sources())
    return {
        "kind": "strategy_factory_score_day",
        "session": session,
        "scored_at": stamp,
        "hypotheses": len(rows),
        "active": sum(1 for hyp in rows if hyp.stage in OPEN_STAGES),
        "counts": counts,
        "unique_confirmation_sources": confirmations,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "invented": False,
        "pnl": None,
        "note": SCORE_NOTE,
    }


class StrategyFactory:
    """Pack-rooted ledger. Writes evidence JSONL + derived active state."""

    def __init__(
        self,
        pack: str | Path | None = None,
        *,
        config: DeskConfig | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.paths = pack_paths(pack)
        self.config = config or load_config(self.paths.root, config_path)
        self._hyps = load_hypotheses(self.paths)

    @property
    def hypotheses(self) -> dict[str, Hypothesis]:
        return self._hyps

    def get(self, hyp_id: str) -> Hypothesis:
        key = assert_hyp_id(hyp_id)
        hyp = self._hyps.get(key)
        if hyp is None:
            raise FactoryError("hyp_missing", f"hypothesis not found: {key}")
        return hyp

    def _persist(self, hyp: Hypothesis, action: str, now: datetime) -> Hypothesis:
        hyp.live_gate = LIVE_GATE
        hyp.places_orders = PLACES_ORDERS
        hyp.invented = False
        hyp.updated_at = isoformat(now)
        snapshot = hyp.to_dict()
        _append_jsonl(self.paths.ledger, snapshot)
        event = {
            "kind": "strategy_factory_event",
            "action": action,
            "hyp_id": hyp.hyp_id,
            "stage": hyp.stage,
            "session": hyp.session,
            "category": hyp.category,
            "at": hyp.updated_at,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
        }
        _append_jsonl(self.paths.events, event)
        self._hyps[hyp.hyp_id] = hyp
        _write_json(self.paths.active, active_document(self._hyps))
        return hyp

    def _active_in_category(self, category: str, session: str) -> list[Hypothesis]:
        return [
            hyp
            for hyp in self._hyps.values()
            if hyp.category == category and hyp.session == session and hyp.stage in OPEN_STAGES
        ]

    def propose(
        self,
        *,
        hyp_id: str,
        category: str,
        title: str,
        mechanism: str = "",
        falsifier: str = "",
        note: str = "",
        session: str | date | None = None,
        now: datetime | str | None = None,
    ) -> Hypothesis:
        stamp = parse_now(now)
        key = assert_hyp_id(hyp_id)
        if key in self._hyps:
            raise FactoryError("hyp_exists", f"hypothesis already exists: {key}")
        cat = category.strip()
        if cat not in self.config.categories:
            raise FactoryError("unknown_category", f"category not allowlisted: {cat}")
        heading = title.strip()
        if not heading:
            raise FactoryError("title_required", "propose requires --title")
        session_key = _session_key(stamp, session)
        active = self._active_in_category(cat, session_key)
        cap = self.config.max_active_per_category_per_session
        if len(active) >= cap:
            raise FactoryError(
                "category_session_cap",
                f"{cat} already has {cap} active hypotheses for {session_key}",
            )
        created = isoformat(stamp)
        hyp = Hypothesis(
            hyp_id=key,
            category=cat,
            title=heading,
            stage="candidate",
            session=session_key,
            mechanism=_named(mechanism),
            falsifier=_named(falsifier),
            note=_named(note),
            confirmations=[],
            created_at=created,
            updated_at=created,
        )
        return self._persist(hyp, "propose", stamp)

    def confirm(
        self,
        *,
        hyp_id: str,
        source: str,
        note: str = "",
        evidence_ref: str = "",
        now: datetime | str | None = None,
    ) -> Hypothesis:
        stamp = parse_now(now)
        hyp = self.get(hyp_id)
        if hyp.stage in TERMINAL_STAGES:
            raise FactoryError("terminal_stage", f"cannot confirm a {hyp.stage} hypothesis")
        if source not in self.config.confirmation_sources:
            raise FactoryError("unknown_source", f"confirmation source not allowlisted: {source}")
        item = parse_confirmation(
            source=source,
            note=note,
            evidence_ref=evidence_ref,
            now=stamp,
        )
        hyp.confirmations.append(item)
        if source == "mechanism_named" and item.note:
            hyp.mechanism = item.note
        if source == "falsifier_named" and item.note:
            hyp.falsifier = item.note
        return self._persist(hyp, "confirm", stamp)

    def _assert_advance(self, hyp: Hypothesis, target: str) -> None:
        sources = hyp.confirmation_sources()
        if target == "validated":
            if (
                self.config.require_mechanism_for_validated
                and not hyp.mechanism
            ):
                raise FactoryError(
                    "mechanism_required",
                    "validated requires a named mechanism "
                    "(propose --mechanism or confirm mechanism_named)",
                )
            need = self.config.min_confirmations_for_validated
            if len(sources) < need:
                raise FactoryError(
                    "confirmations_required",
                    f"validated requires {need} unique confirmation sources (have {len(sources)})",
                )
        if target == "live_allow":
            if self.config.require_falsifier_for_live_allow and not hyp.falsifier:
                raise FactoryError(
                    "falsifier_required",
                    "live_allow requires a named falsifier "
                    "(propose --falsifier or confirm falsifier_named)",
                )
            need = self.config.min_confirmations_for_live_allow
            if len(sources) < need:
                raise FactoryError(
                    "confirmations_required",
                    f"live_allow requires {need} unique confirmation sources (have {len(sources)})",
                )

    def advance(
        self,
        *,
        hyp_id: str,
        now: datetime | str | None = None,
    ) -> Hypothesis:
        stamp = parse_now(now)
        hyp = self.get(hyp_id)
        target = FORWARD.get(hyp.stage)
        if target is None:
            raise FactoryError(
                "invalid_transition",
                f"cannot advance from {hyp.stage}",
            )
        self._assert_advance(hyp, target)
        hyp.stage = target
        return self._persist(hyp, "advance", stamp)

    def reject(
        self,
        *,
        hyp_id: str,
        reason: str,
        now: datetime | str | None = None,
    ) -> Hypothesis:
        return self._close(hyp_id, "rejected", REJECT_FROM, reason, now)

    def kill(
        self,
        *,
        hyp_id: str,
        reason: str,
        now: datetime | str | None = None,
    ) -> Hypothesis:
        return self._close(hyp_id, "killed", KILL_FROM, reason, now)

    def retire(
        self,
        *,
        hyp_id: str,
        reason: str,
        now: datetime | str | None = None,
    ) -> Hypothesis:
        return self._close(hyp_id, "retired", RETIRE_FROM, reason, now)

    def _close(
        self,
        hyp_id: str,
        target: str,
        allowed: frozenset[str],
        reason: str,
        now: datetime | str | None,
    ) -> Hypothesis:
        stamp = parse_now(now)
        hyp = self.get(hyp_id)
        why = reason.strip()
        if not why:
            raise FactoryError("reason_required", f"{target} requires --reason")
        if hyp.stage not in allowed:
            raise FactoryError(
                "invalid_transition",
                f"cannot {CLOSE_ACTION[target]} from {hyp.stage}",
            )
        hyp.stage = target
        hyp.reason = why
        return self._persist(hyp, CLOSE_ACTION[target], stamp)

    def list_hypotheses(
        self,
        *,
        session: str | None = None,
        stage: str | None = None,
        category: str | None = None,
    ) -> list[Hypothesis]:
        rows = list(self._hyps.values())
        if session:
            rows = [hyp for hyp in rows if hyp.session == _session_key(parse_now(None), session)]
        if stage:
            if stage not in STAGES:
                raise FactoryError("unknown_stage", f"unknown stage: {stage}")
            rows = [hyp for hyp in rows if hyp.stage == stage]
        if category:
            if category not in self.config.categories:
                raise FactoryError("unknown_category", f"category not allowlisted: {category}")
            rows = [hyp for hyp in rows if hyp.category == category]
        rows.sort(key=lambda hyp: (hyp.session, hyp.category, hyp.hyp_id))
        return rows

    def status(self, hyp_id: str) -> dict[str, Any]:
        return self.get(hyp_id).to_dict()

    def score_day(
        self,
        *,
        session: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        stamp = parse_now(now)
        key = _session_key(stamp, session)
        return score_day(self._hyps, session=key, now=stamp)


# Re-export pack relative names so tests can assert the on-disk contract.
PACK_FILES = (EVENTS_REL, LEDGER_REL, ACTIVE_REL)
