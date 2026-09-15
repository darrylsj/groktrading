"""Desk defaults for the observational shadow-bets RSI ledger.

``live_gate`` is forced false. This tool never places orders and never
invents NBBO. Marks must already exist (Tradier-cited). I1 stays 60s —
this ledger cannot unlock a wider consume age.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from groktrading.sit_match import DEFAULT_SIT_MATCH_MAX_AGE_SEC

LIVE_GATE = False
PLACES_ORDERS = False
PACK_ENV = "SHADOW_BETS_PACK"
PACK_SYNC_PATH = "/home/box/agent-data/projects/trading-desk/tools/shadow_bets/"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Live I1 consume age. Observational labels must not raise this.
I1_MAX_AGE_SEC = float(DEFAULT_SIT_MATCH_MAX_AGE_SEC)
assert I1_MAX_AGE_SEC == 60.0

# Opportunity webhook emit (host script; sit_match stays OFF).
SIT_MATCH_STAYS_OFF = True
SHORTLIST_OPP_EVENT = "shortlist_opportunity"
SHORTLIST_OPP_TOP1_ONLY = True
SHORTLIST_OPP_MAX_AGE_SEC = 45.0
SHORTLIST_OPP_OCC_DEBOUNCE_SEC = 600.0
SHORTLIST_OPP_MIN_INTERVAL_SEC = 300.0
WAKE_REENABLE_BUDGET_SEC = 30.0
HOST_OPP_WEBHOOK = "/opt/trading-desk/bin/shortlist_opportunity_webhook.py"

STAGES = ("opened", "marked")
LABELS = (
    "yes_latency_fix_wake",
    "no_latency_fix_wake",
    "yes_fresh_wake",
    "unscored",
    "other",
)
WAKE_LATENCY_REASONS = frozenset(
    {
        "i1_stale",
        "stale_print",
        "sit_match_stale",
    }
)
MARK_SOURCES = frozenset({"tradier_production", "tradier_sandbox"})

EVENTS_REL = Path("evidence") / "shadow_bets_events.jsonl"
LEDGER_REL = Path("evidence") / "shadow_bets_ledger.jsonl"
SESSION_REL = Path("state") / "shadow_bets_session.json"

SCORE_NOTE = (
    "Observational shadow-bets RSI. live_gate=false always. "
    "Never invents NBBO. Never places orders. "
    "Labels (yes_latency_fix_wake, …) are observational only. "
    "Does not unlock I1 > 60s. Does not re-enable sit_match. "
    "Does not change MUST_TRADE_SMALL_ASK_CAP."
)


class ShadowBetsError(ValueError):
    """Fail-closed shadow-bets reject. ``code`` is the stable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class PackPaths:
    root: Path
    events: Path
    ledger: Path
    session: Path


def pack_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(PACK_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT


def pack_paths(root: str | Path | None = None) -> PackPaths:
    base = pack_root(root)
    return PackPaths(
        root=base,
        events=base / EVENTS_REL,
        ledger=base / LEDGER_REL,
        session=base / SESSION_REL,
    )


def assert_i1_unlocked(max_age_sec: float | None) -> float:
    """Refuse any attempt to observe or consume past live I1 60s."""
    if max_age_sec is None:
        return I1_MAX_AGE_SEC
    try:
        value = float(max_age_sec)
    except (TypeError, ValueError) as exc:
        raise ShadowBetsError("i1_invalid_max_age", "I1 max age must be a finite number") from exc
    if value != value or value in {float("inf"), float("-inf")}:
        raise ShadowBetsError("i1_invalid_max_age", "I1 max age must be finite")
    if value > I1_MAX_AGE_SEC:
        raise ShadowBetsError(
            "i1_widen_forbidden",
            f"refusing I1 max age {value}; live I1 stays {I1_MAX_AGE_SEC:.0f}s",
        )
    if value <= 0:
        raise ShadowBetsError("i1_invalid_max_age", "I1 max age must be > 0")
    return value
