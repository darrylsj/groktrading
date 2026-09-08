"""Venue-aware broker adapters.

Phase A: `Broker` protocol + `TradierBroker` + test `RecordingBroker`.
`SchwabBroker` is an OAuth-not-ready placeholder (no secrets, no calls).

Do not import this package from Opening15 `research.cli` / packet capture.
"""

from groktrading.brokers.protocol import (
    PLANNED_SCHWAB_VENUE,
    Broker,
    OrderBroker,
    VenueId,
    exit_venue,
    refuse_dual_fire,
)
from groktrading.brokers.recording import RecordingBroker, RecordingOrderBroker
from groktrading.brokers.schwab import (
    SCHWAB_OAUTH_NOT_READY,
    SCHWAB_VENUE_ID,
    SchwabBroker,
    require_schwab_ready,
)
from groktrading.brokers.tradier import TradierBroker

__all__ = [
    "PLANNED_SCHWAB_VENUE",
    "SCHWAB_OAUTH_NOT_READY",
    "SCHWAB_VENUE_ID",
    "Broker",
    "OrderBroker",
    "RecordingBroker",
    "RecordingOrderBroker",
    "SchwabBroker",
    "TradierBroker",
    "VenueId",
    "exit_venue",
    "refuse_dual_fire",
    "require_schwab_ready",
]
