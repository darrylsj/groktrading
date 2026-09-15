"""Opportunity-process funnel from refuse evidence.

Reads ``uw_opportunity_refuses.jsonl`` (or a JSON list). Optional shortlist
and shadow-summary hooks attach only what those files already contain.

Never invents OCCs, prices, or P&L. Rows with ``invented: true`` are
skipped. Rows without a usable OCC are skipped (not filled in).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dashboard.config import (
    FUNNEL_KIND,
    FUNNEL_SCHEMA,
    HUNT_WHILE_PAUSED,
    I1_MAX_AGE_SEC,
    INVENTED,
    LAST_OCCS_DEFAULT,
    LIVE_GATE,
    OPPORTUNITY_WEBHOOK_RESUME,
    PLACES_ORDERS,
    SHORTLIST_OPP_EVENT,
    SIT_MATCH_STAYS_OFF,
    UNLOCK_I1,
    DashboardError,
)
from groktrading.quote_gate import normalize_occ
from groktrading.sit_match import parse_executed_at


def _named(value: object) -> str:
    return str(value or "").strip()


def extract_occ(row: Mapping[str, Any]) -> str | None:
    raw = row.get("occ") or row.get("option_symbol") or row.get("symbol")
    text = _named(raw)
    if not text:
        return None
    occ = normalize_occ(text)
    if len(occ) < 5 or not occ.isalnum():
        return None
    return occ


def _is_invented(row: Mapping[str, Any]) -> bool:
    flag = row.get("invented")
    if flag is True:
        return True
    if isinstance(flag, str) and flag.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def load_rows(path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    """Load refuse rows. Missing/empty is a reported hole, not an error."""
    if path is None:
        return [], "no_input"
    target = Path(path)
    if not target.is_file():
        return [], "file_missing"
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return [], "empty_file"
    doc: object | None = None
    if text[0] in "{[":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, list):
            return [row for row in doc if isinstance(row, dict)], None
        if isinstance(doc, dict):
            for key in ("refuses", "rows", "events", "items"):
                nested = doc.get(key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)], None
            return [doc], None
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DashboardError(
                "refuses_invalid_jsonl",
                f"invalid JSONL at {target}:{line_no}",
            ) from exc
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows, None if rows else "empty_file"


def _evidence_ask(row: Mapping[str, Any]) -> str | None:
    """Copy an already-present ask. Never invent a mid/last/mark."""
    for key in ("evidence_ask", "refuse_ask", "ask", "print_ask"):
        raw = row.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"none", "null", "nan"}:
            return text
    return None


def _shortlist_hook(path: Path | None) -> dict[str, Any]:
    hook: dict[str, Any] = {
        "present": False,
        "empty_reason": "no_input",
        "ranked_at": None,
        "candidates": [],
        "candidate_occs": [],
        "empty_reason_shortlist": None,
        "emit_sit_match": False,
        "schema": None,
    }
    if path is None:
        return hook
    target = Path(path)
    if not target.is_file():
        hook["empty_reason"] = "file_missing"
        return hook
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DashboardError("shortlist_invalid_json", f"invalid JSON: {target}") from exc
    if not isinstance(doc, Mapping):
        hook["empty_reason"] = "unknown_shape"
        return hook
    hook["present"] = True
    hook["empty_reason"] = None
    hook["schema"] = doc.get("schema")
    hook["ranked_at"] = doc.get("ranked_at")
    hook["empty_reason_shortlist"] = doc.get("empty_reason")
    hook["emit_sit_match"] = False
    raw_candidates = doc.get("candidates")
    occs: list[str] = []
    slim: list[dict[str, Any]] = []
    if isinstance(raw_candidates, list):
        for row in raw_candidates:
            if not isinstance(row, Mapping):
                continue
            if _is_invented(row):
                continue
            occ = extract_occ(row)
            if occ is None:
                continue
            occs.append(occ)
            item: dict[str, Any] = {
                "occ": occ,
                "underlying": _named(row.get("underlying")).upper() or None,
                "option_type": _named(row.get("option_type")).lower() or None,
                "source": _named(row.get("source")) or None,
            }
            executed = parse_executed_at(row.get("executed_at"))
            if executed is not None:
                item["executed_at"] = executed.isoformat().replace("+00:00", "Z")
            slim.append(item)
    hook["candidates"] = slim
    hook["candidate_occs"] = occs
    return hook


def _shadow_hook(path: Path | None) -> dict[str, Any]:
    hook: dict[str, Any] = {
        "present": False,
        "empty_reason": "no_input",
        "kind": None,
        "opened": None,
        "marked": None,
        "unmarked": None,
        "scored": None,
        "hits": None,
        "hit_rate": None,
        "labels": {},
        "pnl": None,
        "one_lot_usd": None,
        "live_gate": LIVE_GATE,
        "invented": False,
    }
    if path is None:
        return hook
    target = Path(path)
    if not target.is_file():
        hook["empty_reason"] = "file_missing"
        return hook
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DashboardError(
            "shadow_summary_invalid_json", f"invalid JSON: {target}"
        ) from exc
    if not isinstance(doc, Mapping):
        hook["empty_reason"] = "unknown_shape"
        return hook
    hook["present"] = True
    hook["empty_reason"] = None
    hook["kind"] = doc.get("kind")
    for key in ("opened", "marked", "unmarked", "scored", "hits", "hit_rate"):
        if key in doc:
            hook[key] = doc.get(key)
    labels = doc.get("labels")
    if isinstance(labels, Mapping):
        hook["labels"] = {
            str(name): labels[name] for name in labels if isinstance(labels[name], int)
        }
    # Shadow bets contract: summarize.pnl is always null. Never invent P&L.
    hook["pnl"] = None
    if "one_lot_usd" in doc and doc.get("one_lot_usd") is not None:
        hook["one_lot_usd"] = str(doc.get("one_lot_usd"))
    return hook


def _row_snapshot(row: Mapping[str, Any], occ: str) -> dict[str, Any]:
    reason = _named(row.get("reason") or row.get("refuse_reason")) or "unspecified"
    snap: dict[str, Any] = {
        "occ": occ,
        "reason": reason,
        "invented": False,
    }
    executed = parse_executed_at(row.get("executed_at"))
    if executed is not None:
        snap["executed_at"] = executed.isoformat().replace("+00:00", "Z")
    emitted = parse_executed_at(row.get("emitted_at"))
    if emitted is not None:
        snap["emitted_at"] = emitted.isoformat().replace("+00:00", "Z")
    consumed = parse_executed_at(row.get("consumed_at") or row.get("woken_at"))
    if consumed is not None:
        snap["consumed_at"] = consumed.isoformat().replace("+00:00", "Z")
    ask = _evidence_ask(row)
    if ask is not None:
        snap["evidence_ask"] = ask
    session = _named(row.get("session"))
    if session:
        snap["session"] = session
    return snap


def build_funnel(
    refuses: Path | None = None,
    *,
    shortlist: Path | None = None,
    shadow_summary: Path | None = None,
    last_occs: int = LAST_OCCS_DEFAULT,
) -> dict[str, Any]:
    """Build the opportunity-process funnel. Missing inputs are holes."""
    if last_occs <= 0:
        raise DashboardError("last_occs_invalid", "last_occs must be > 0")
    rows, empty_reason = load_rows(refuses)
    kept: list[dict[str, Any]] = []
    skipped_invented = 0
    skipped_no_occ = 0
    reasons: Counter[str] = Counter()
    occ_order: list[str] = []
    for row in rows:
        if _is_invented(row):
            skipped_invented += 1
            continue
        occ = extract_occ(row)
        if occ is None:
            skipped_no_occ += 1
            continue
        snap = _row_snapshot(row, occ)
        kept.append(snap)
        reasons[str(snap["reason"])] += 1
        if occ not in occ_order:
            occ_order.append(occ)
        else:
            occ_order.remove(occ)
            occ_order.append(occ)
    present = empty_reason is None
    last = occ_order[-last_occs:] if occ_order else []
    return {
        "kind": FUNNEL_KIND,
        "schema": FUNNEL_SCHEMA,
        "source": "uw_opportunity_refuses.jsonl",
        "present": present,
        "empty_reason": empty_reason if not present else None,
        "rows": len(kept),
        "skipped_invented": skipped_invented,
        "skipped_no_occ": skipped_no_occ,
        "refuse_reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        "last_occs": last,
        "refuses": kept[-last_occs:],
        "shortlist": _shortlist_hook(shortlist),
        "shadow_summary": _shadow_hook(shadow_summary),
        "posture": {
            "sit_match": False,
            "sit_match_stays_off": SIT_MATCH_STAYS_OFF,
            "opportunity_webhook": "paused",
            "opportunity_event": SHORTLIST_OPP_EVENT,
            "opportunity_webhook_resume": OPPORTUNITY_WEBHOOK_RESUME,
            "hunt": HUNT_WHILE_PAUSED,
            "i1_max_age_sec": I1_MAX_AGE_SEC,
            "unlock_i1": UNLOCK_I1,
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "invented": INVENTED,
        },
    }
