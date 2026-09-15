"""In-repo contract for the operator-side shortlist_opportunity webhook.

Host SoT (not copied by this repo):
``/opt/trading-desk/bin/shortlist_opportunity_webhook.py``.

This file does **not** POST, does **not** read ``grok-webhook.env``, and
does **not** re-enable ``sit_match``. Hunt default while the opportunity
timer is paused: Continual15 + ``shortlist.json``.

Emit rules if an operator enables the host timer:

- ``TOP1_ONLY``
- wall-clock ``executed_at`` freshness
- ``SHORTLIST_OPP_MAX_AGE_SEC=45``
- OCC debounce **600s**
- global min interval **300s**

Re-enable the opportunity timer only if a wake completes the
refuse-or-lift path in **<30s**. Live I1 consume stays **60s**. Do not
unlock I1>60. Never places orders. Never invents NBBO.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from groktrading.sit_match import (
    DEFAULT_SIT_MATCH_MAX_AGE_SEC,
    evaluate_sit_match_freshness,
    parse_executed_at,
    sit_match_occ_key,
)
from groktrading.timeutil import as_utc

SIT_MATCH_STAYS_OFF = True
SHORTLIST_OPP_EVENT = "shortlist_opportunity"
SHORTLIST_OPP_TOP1_ONLY = True
SHORTLIST_OPP_MAX_AGE_SEC = 45.0
SHORTLIST_OPP_OCC_DEBOUNCE_SEC = 600.0
SHORTLIST_OPP_MIN_INTERVAL_SEC = 300.0
WAKE_REENABLE_BUDGET_SEC = 30.0
I1_MAX_AGE_SEC = float(DEFAULT_SIT_MATCH_MAX_AGE_SEC)
HOST_SCRIPT = "/opt/trading-desk/bin/shortlist_opportunity_webhook.py"
HUNT_WHILE_PAUSED = "Continual15 + shortlist.json"


def emit_allowed(
    payload: Mapping[str, Any],
    *,
    now: datetime,
    rank: int = 1,
    last_occ_at: datetime | None = None,
    last_global_at: datetime | None = None,
) -> dict[str, Any]:
    """Dry emit decision. Never POSTs. sit_match stays off."""
    if not SIT_MATCH_STAYS_OFF:
        return {"allow": False, "reason": "sit_match_must_stay_off", "places_orders": False}
    if SHORTLIST_OPP_TOP1_ONLY and rank != 1:
        return {"allow": False, "reason": "not_top1", "places_orders": False}
    freshness = evaluate_sit_match_freshness(
        payload.get("executed_at"),
        as_utc(now),
        max_age_sec=SHORTLIST_OPP_MAX_AGE_SEC,
    )
    if not freshness.allow:
        return {
            "allow": False,
            "reason": freshness.reason or "stale_executed_at",
            "age_seconds": freshness.age_seconds,
            "places_orders": False,
            "event": SHORTLIST_OPP_EVENT,
        }
    occ = sit_match_occ_key(str(payload.get("occ") or payload.get("option_symbol") or ""))
    stamp = as_utc(now)
    if occ and last_occ_at is not None:
        if (stamp - as_utc(last_occ_at)).total_seconds() < SHORTLIST_OPP_OCC_DEBOUNCE_SEC:
            return {"allow": False, "reason": "occ_debounce", "places_orders": False}
    if last_global_at is not None:
        if (stamp - as_utc(last_global_at)).total_seconds() < SHORTLIST_OPP_MIN_INTERVAL_SEC:
            return {"allow": False, "reason": "global_min_interval", "places_orders": False}
    executed = parse_executed_at(payload.get("executed_at"))
    return {
        "allow": True,
        "reason": "ok",
        "event": SHORTLIST_OPP_EVENT,
        "occ": occ,
        "executed_at": None if executed is None else executed.isoformat(),
        "print_age_sec": freshness.age_seconds,
        "top1_only": True,
        "max_age_sec": SHORTLIST_OPP_MAX_AGE_SEC,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
        "unlock_i1": False,
        "sit_match": False,
        "places_orders": False,
        "invented": False,
    }


def wake_fast_enough(refuse_or_lift_sec: float) -> bool:
    """Re-enable the opportunity timer only if refuse-or-lift is <30s."""
    return 0 <= refuse_or_lift_sec < WAKE_REENABLE_BUDGET_SEC
