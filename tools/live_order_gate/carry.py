"""Optional overnight-carry thesis fields (soft). Not a live flatten gate.

``how_it_dies`` / ``falsifier`` stay hard-required on every *written* thesis.
Carry notes are optional for same-day entries. ``--overnight-carry`` / 
``overnight_carry=true`` requires ``carry_dte``, ``carry_event_risk``, and
``carry_rationale``. Rationale must explain why the mechanism survives
overnight — not "cash floor OK".

Does not change cash floor, does not auto-flatten, does not lift the credit/STO
dated hold (through Tue 2026-09-15 RTH; see ``docs/STO_UNLOCK_PLAN.md``).
``live_gate`` is not flipped by these fields.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from groktrading.timeutil import UTC, as_utc

CASH_FLOOR_RATIONALE_RE = re.compile(r"^cash\s+floor\s+ok\.?$", re.IGNORECASE)

CarryDte = str | int | None


def _iso(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def blank_to_none(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def resolve_falsifier(
    falsifier: object | None,
    how_it_dies: object | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(text, error_code)``. Missing both → ``falsifier_required``."""
    left = str(falsifier).strip() if falsifier not in (None, "") else ""
    right = str(how_it_dies).strip() if how_it_dies not in (None, "") else ""
    if left and right and left != right:
        return None, "falsifier_mismatch"
    text = left or right
    if not text:
        return None, "falsifier_required"
    return text, None


def parse_overnight_carry(value: object) -> tuple[bool | None, str | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return value, None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True, None
    if text in {"false", "0", "no"}:
        return False, None
    return None, "overnight_carry_invalid"


def parse_carry_dte(value: object) -> tuple[CarryDte, str | None]:
    cleaned = blank_to_none(value)
    if cleaned is None:
        return None, None
    if isinstance(cleaned, bool):
        return None, "carry_dte_invalid"
    if isinstance(cleaned, int):
        return cleaned, None
    text = str(cleaned).strip()
    if not text:
        return None, None
    if text.lstrip("-").isdigit():
        return int(text), None
    return text, None


def parse_carry_text(value: object) -> str | None:
    cleaned = blank_to_none(value)
    if cleaned is None:
        return None
    return str(cleaned).strip()


def overnight_carry_notes_required(
    overnight_carry: bool | None,
    *,
    require_overnight_carry: bool = False,
) -> bool:
    """True when the operator set overnight carry (flag or field)."""
    return require_overnight_carry or overnight_carry is True


def validate_carry_fields(
    *,
    overnight_carry: bool | None,
    carry_dte: CarryDte,
    carry_event_risk: str | None,
    carry_rationale: str | None,
    require_overnight_carry: bool = False,
) -> str | None:
    """Return a PolicyError code, or None if the soft/required carry notes pass."""
    if not overnight_carry_notes_required(
        overnight_carry, require_overnight_carry=require_overnight_carry
    ):
        return None
    if carry_dte is None or (isinstance(carry_dte, str) and not carry_dte.strip()):
        return "carry_dte_required"
    if not carry_event_risk:
        return "carry_event_risk_required"
    if not carry_rationale:
        return "carry_rationale_required"
    if CASH_FLOOR_RATIONALE_RE.fullmatch(carry_rationale):
        return "carry_rationale_not_cash_floor"
    return None


def carry_gate_document(
    *,
    overnight_carry: bool | None,
    carry_dte: CarryDte,
    carry_event_risk: str | None,
    carry_rationale: str | None,
) -> dict[str, Any]:
    """``gates/carry`` stamp for receipt JSON, evidence, and thinking.jsonl."""
    return {
        "overnight_carry": overnight_carry,
        "carry_dte": carry_dte,
        "carry_event_risk": carry_event_risk,
        "carry_rationale": carry_rationale,
        "required": overnight_carry is True,
        "soft": True,
        "auto_flatten": False,
        "changes_cash_floor": False,
        "credit_sto_banned": True,
        "credit_sto_hold_through": "2026-09-15 RTH",
        "live_gate": False,
    }


def carry_fields_from_mapping(raw: Mapping[str, Any]) -> dict[str, Any]:
    overnight, err = parse_overnight_carry(raw.get("overnight_carry"))
    if err:
        return {"error": err}
    dte, dte_err = parse_carry_dte(raw.get("carry_dte"))
    if dte_err:
        return {"error": dte_err}
    return {
        "overnight_carry": overnight,
        "carry_dte": dte,
        "carry_event_risk": parse_carry_text(raw.get("carry_event_risk")),
        "carry_rationale": parse_carry_text(raw.get("carry_rationale")),
    }


def thesis_receipt_document(
    thesis: Mapping[str, Any],
    *,
    carry: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = now or datetime.now(tz=UTC)
    falsifier = thesis.get("falsifier") or thesis.get("how_it_dies")
    return {
        "kind": "live_order_gate_thesis_receipt",
        "places_orders": False,
        "dry_run": True,
        "live_gate": False,
        "thesis": dict(thesis),
        "gates": {"carry": dict(carry)},
        "how_it_dies": falsifier,
        "falsifier": falsifier,
        "now": _iso(stamp),
    }


def thesis_evidence_markdown(
    thesis: Mapping[str, Any],
    *,
    carry: Mapping[str, Any],
) -> str:
    falsifier = thesis.get("falsifier") or thesis.get("how_it_dies") or ""
    lines = [
        "# live_order_gate thesis evidence",
        "",
        f"signal_id: {thesis.get('signal_id', '')}",
        f"option_symbol: {thesis.get('option_symbol', '')}",
        f"intent: {thesis.get('intent', '')}",
        f"side: {thesis.get('side', '')}",
        f"strategy: {thesis.get('strategy', '')}",
        "",
        "## how_it_dies / falsifier",
        "",
        str(falsifier),
        "",
        "## gates/carry",
        "",
        f"- overnight_carry: {carry.get('overnight_carry')}",
        f"- carry_dte: {carry.get('carry_dte')}",
        f"- carry_event_risk: {carry.get('carry_event_risk')}",
        f"- carry_rationale: {carry.get('carry_rationale')}",
        f"- required: {carry.get('required')}",
        "- soft: true (not a live flatten; cash floor unchanged; "
        "credits/STO dated hold through Tue 2026-09-15 RTH; see docs/STO_UNLOCK_PLAN.md)",
        "- live_gate: false",
        "",
    ]
    return "\n".join(lines)


def thinking_carry_row(
    thesis: Mapping[str, Any],
    *,
    carry: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = now or datetime.now(tz=UTC)
    falsifier = thesis.get("falsifier") or thesis.get("how_it_dies")
    return {
        "kind": "live_order_gate_thinking",
        "signal_id": thesis.get("signal_id"),
        "option_symbol": thesis.get("option_symbol"),
        "intent": thesis.get("intent"),
        "how_it_dies": falsifier,
        "falsifier": falsifier,
        "gates": {"carry": dict(carry)},
        "places_orders": False,
        "dry_run": True,
        "live_gate": False,
        "now": _iso(stamp),
    }


def stamp_thesis_artifacts(
    thesis: Mapping[str, Any],
    *,
    carry: Mapping[str, Any],
    receipt_path: Path | str | None = None,
    evidence_path: Path | str | None = None,
    thinking_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write receipt JSON, evidence markdown, and append a thinking.jsonl row."""
    receipt = thesis_receipt_document(thesis, carry=carry, now=now)
    evidence = thesis_evidence_markdown(thesis, carry=carry)
    row = thinking_carry_row(thesis, carry=carry, now=now)
    if receipt_path is not None:
        dest = Path(receipt_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if evidence_path is not None:
        dest = Path(evidence_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(evidence, encoding="utf-8")
    if thinking_path is not None:
        dest = Path(thinking_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {"receipt": receipt, "evidence": evidence, "thinking": row}
