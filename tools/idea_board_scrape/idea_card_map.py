"""Map an idea_board.v0_1 into idea_card.v0_1 records with provenance.

Empty legs stay empty and are flagged ``legs_missing``. That is not a
tradable contract. OCC is copied only when a leg already carries an OCC
symbol. Nothing here authorizes ``live_order_gate``.
"""

from __future__ import annotations

import re

OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def _occ(leg: dict) -> str | None:
    raw = str(leg.get("occ") or "")
    compact = raw.replace("-", "").replace(" ", "").upper()
    if OCC_RE.fullmatch(compact):
        return compact
    return None


def board_to_idea_cards(board: dict) -> list[dict]:
    provenance = dict(board.get("provenance") or {})
    cards: list[dict] = []
    for idea in board.get("ideas") or []:
        if not isinstance(idea, dict):
            continue
        legs = [leg for leg in (idea.get("legs") or []) if isinstance(leg, dict)]
        occs = [occ for occ in (_occ(leg) for leg in legs) if occ]
        ui = idea.get("ui_fields") if isinstance(idea.get("ui_fields"), dict) else {}
        cards.append(
            {
                "schema": "idea_card.v0_1",
                "source": board.get("source"),
                "ticker": idea.get("ticker"),
                "strategy_template_id": ui.get("templateType") or idea.get("strategy"),
                "vendor_status": idea.get("status"),
                "direction": idea.get("direction"),
                "legs": legs,
                "legs_missing": len(legs) == 0,
                "max_risk": idea.get("max_risk"),
                "max_gain": idea.get("max_gain"),
                "pop": idea.get("pop"),
                "compare_metrics_present": idea.get("compare_metrics_present") is True,
                "entry": idea.get("entry") or {"display": None, "mid": None},
                "occ_resolvable": bool(legs) and len(occs) == len(legs),
                "occ_symbols": occs,
                "provenance": {
                    "capture": provenance.get("capture"),
                    "observed_at_pt": board.get("as_of_pt"),
                    "source_url": board.get("source_url"),
                    "board_schema": board.get("schema"),
                    "execution_realm": "shadow",
                    "authorizes_live_orders": False,
                    "live_order_gate": False,
                },
                "no_invented_prices": True,
            }
        )
    return cards
