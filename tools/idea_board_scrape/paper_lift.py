"""Tradier PAPER one-lot stub. Not wired to live_order_gate.

The only paper HTTP base this desk may use later is
``https://sandbox.tradier.com/v1``. The sandbox account id stays in host
env and is not stored here. Ranked Trade Machine cards with a resolvable
OCC may paper-lift later. Options AI stays on validated DOM boards until
a Confirmed idea endpoint exists.

Shadow metadata is not an order. Any adapter must require
``provenance.execution_realm`` of shadow or paper and
``provenance.live_order_gate is False`` before it does anything else.
This module does not submit.
"""

from __future__ import annotations

from collections.abc import Mapping

PAPER_API_BASE = "https://sandbox.tradier.com/v1"


class PaperLiftError(RuntimeError):
    """Idea card is not a paper candidate, or the caller asked for live."""


def assert_paper_base(api_base: str) -> None:
    if api_base.rstrip("/") != PAPER_API_BASE:
        raise PaperLiftError("paper path is https://sandbox.tradier.com/v1 only; never live")


def assert_shadow_provenance(card: Mapping[str, object]) -> None:
    provenance = card.get("provenance")
    if not isinstance(provenance, Mapping):
        raise PaperLiftError("paper/shadow provenance is required on every idea card")
    realm = provenance.get("execution_realm")
    if realm not in {"shadow", "paper"}:
        raise PaperLiftError("adapter must require provenance.execution_realm shadow or paper")
    if provenance.get("live_order_gate") is not False:
        raise PaperLiftError("idea cards must not authorize live_order_gate")
    if provenance.get("authorizes_live_orders") is not False:
        raise PaperLiftError("idea cards do not authorize live orders")


def paper_one_lot_ready(card: Mapping[str, object]) -> dict[str, object]:
    """Return a non-submitting decision. ``places_orders`` is always false."""
    assert_shadow_provenance(card)
    assert_paper_base(PAPER_API_BASE)
    if card.get("source") == "options_ai":
        return {
            "ok": False,
            "places_orders": False,
            "reason": "options_ai_dom_until_confirmed",
            "api_base": PAPER_API_BASE,
        }
    if card.get("occ_resolvable") is not True or card.get("legs_missing") is True:
        return {
            "ok": False,
            "places_orders": False,
            "reason": "occ_not_resolvable",
            "api_base": PAPER_API_BASE,
        }
    return {
        "ok": False,
        "places_orders": False,
        "reason": "paper_lift_not_enabled",
        "api_base": PAPER_API_BASE,
        "note": "Ranked TM ideas with resolvable OCC may paper-lift later. Not this call.",
    }
