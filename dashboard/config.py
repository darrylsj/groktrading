"""Desk live-board defaults. Observational only. Never a live gate.

Hard rules (also rendered on the static board):

- READ-ONLY snapshots. No new WebSocket subscriptions.
- ``sit_match`` stays OFF. This builder does not unmute it.
- ``shortlist_opportunity`` stays paused. This builder does not resume
  the host webhook timer.
- Never invent prices, P&L, or OCCs.
- Helsinki tape files are optional. Missing files are reported, not
  invented. CI must not claim ``/opt/trading-desk`` exists.
"""

from __future__ import annotations

from pathlib import Path

from groktrading.sit_match import DEFAULT_SIT_MATCH_MAX_AGE_SEC

LIVE_GATE = False
PLACES_ORDERS = False
INVENTED = False
UNLOCK_I1 = False
SIT_MATCH_STAYS_OFF = True
NEW_WS_SUBSCRIPTIONS = False
OPPORTUNITY_WEBHOOK_RESUME = False

I1_MAX_AGE_SEC = float(DEFAULT_SIT_MATCH_MAX_AGE_SEC)
assert I1_MAX_AGE_SEC == 60.0

SCHEMA_ID = "groktrading.desk_board.v1"
FUNNEL_SCHEMA = "groktrading.desk_board.funnel.v1"
WS_STATS_SCHEMA = "groktrading.desk_board.ws_stats.v1"
KIND = "desk_board"
FUNNEL_KIND = "opportunity_funnel"
WS_STATS_KIND = "ws_stats"

SIBLING_SITE_REPO = "darrylsj/trading-desk-live-board"
SIBLING_SITE_HOST = "Vercel"
PACK_SYNC_PATH = "/home/box/agent-data/projects/trading-desk/dashboard/"

# Ops documentation only. Not a deploy claim. CI must not require these.
HOST_FINNHUB_TAPE = "/opt/trading-desk/finnhub_tape.json"
HOST_LIVE_TAPE = "/opt/trading-desk/live_tape.json"
HOST_REFUSES = "/opt/trading-desk/evidence/uw_opportunity_refuses.jsonl"
HOST_SHORTLIST = "/opt/trading-desk/state/shortlist.json"

LAST_OCCS_DEFAULT = 8
HUNT_WHILE_PAUSED = "Continual15 + shortlist.json"
SHORTLIST_OPP_EVENT = "shortlist_opportunity"

HARD_RULES = (
    "READ-ONLY snapshots. No new WebSocket subscriptions.",
    "sit_match stays OFF. This builder does not unmute it.",
    "shortlist_opportunity stays paused. This builder does not resume the webhook.",
    "Never invent prices, P&L, or OCCs.",
    "Helsinki tape files are optional. Missing files are reported, not invented.",
    "Does not place orders. Does not change live_order_gate.",
)

BOARD_NOTE = (
    "Observational desk board. live_gate=false. "
    "Reads uw_opportunity_refuses.jsonl plus optional shortlist / "
    "shadow-summary hooks and optional Helsinki health JSON. "
    "Does not open sockets. Does not unmute sit_match. "
    "Does not resume shortlist_opportunity. "
    "Static HTML/JSON for darrylsj/trading-desk-live-board (Vercel)."
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class DashboardError(ValueError):
    """Fail-closed dashboard reject. ``code`` is the stable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)
