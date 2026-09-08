"""Venue-aware broker adapters.

Phase A: `Broker` protocol + `TradierBroker` + test `RecordingBroker`.
`SchwabBroker` fails closed without OAuth tokens. Auth scaffolding lives in
`schwab_oauth` (no live order/quote HTTP).

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
from groktrading.brokers.schwab_oauth import (
    CALLBACK_URL,
    client_from_login_flow,
    refresh_client,
    stub_message,
)
from groktrading.brokers.tradier import TradierBroker
from groktrading.errors import SchwabAuthNotReady

__all__ = [
    "CALLBACK_URL",
    "PLANNED_SCHWAB_VENUE",
    "SCHWAB_OAUTH_NOT_READY",
    "SCHWAB_VENUE_ID",
    "Broker",
    "OrderBroker",
    "RecordingBroker",
    "RecordingOrderBroker",
    "SchwabAuthNotReady",
    "SchwabBroker",
    "TradierBroker",
    "VenueId",
    "client_from_login_flow",
    "exit_venue",
    "refresh_client",
    "refuse_dual_fire",
    "require_schwab_ready",
    "stub_message",
]
