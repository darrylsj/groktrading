"""Dynamic Tradier quote interest set — session watchlist, not an order path.

When a fresh sit/flow print appears, add the underlying to a bounded
interest set (default max 40) for the session. Drop idle names. This is
the **interest list** a host-owned ``ws_tape.py`` can subscribe to.

Live Tradier market WS / ``ws_tape.py`` is **host-owned** and must be
wired by the operator. This helper never opens a Tradier socket and
never places orders. Sandbox has no market-data stream.

Freshness: only touch on a print that passes sit_match rules (or an
explicit ``fresh=True`` from the caller). Stale ledger rows do not
expand the watchlist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from groktrading.cadence import env_seconds
from groktrading.errors import WatchlistBoundError
from groktrading.feeds.unusual_whales import sanitize_ticker
from groktrading.flow_ledger import FlowRow
from groktrading.sit_match import SitMatchFreshness, evaluate_sit_match_freshness
from groktrading.timeutil import UTC, as_utc

QUOTE_WATCH_BOUND_ENV = "TRADIER_QUOTE_WATCH_BOUND"
QUOTE_IDLE_TTL_ENV = "TRADIER_QUOTE_IDLE_TTL_SEC"
DEFAULT_QUOTE_WATCH_BOUND = 40
QUOTE_WATCH_BOUND_LO = 1
QUOTE_WATCH_BOUND_HI = 40
DEFAULT_IDLE_TTL_SEC = 900.0
IDLE_TTL_LO = 60.0
IDLE_TTL_HI = 3600.0
NEVER_ORDERS_NOTE = (
    "Tradier quote interest set only. Live ws_tape.py is host-owned and "
    "must be wired by the operator. WebSocket never places orders."
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def quote_watch_bound(env: Mapping[str, str] | None = None) -> int:
    return int(
        env_seconds(
            env,
            QUOTE_WATCH_BOUND_ENV,
            default=float(DEFAULT_QUOTE_WATCH_BOUND),
            lo=float(QUOTE_WATCH_BOUND_LO),
            hi=float(QUOTE_WATCH_BOUND_HI),
        )
    )


def quote_idle_ttl_sec(env: Mapping[str, str] | None = None) -> float:
    return env_seconds(
        env,
        QUOTE_IDLE_TTL_ENV,
        default=DEFAULT_IDLE_TTL_SEC,
        lo=IDLE_TTL_LO,
        hi=IDLE_TTL_HI,
    )


@dataclass
class TradierQuoteInterest:
    """Session interest set. LRU-evict idle, then oldest, when at bound."""

    bound: int = DEFAULT_QUOTE_WATCH_BOUND
    idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SEC
    last_seen: dict[str, datetime] = field(default_factory=dict)
    clock: Clock = field(default_factory=UtcClock)

    def symbols(self) -> list[str]:
        return sorted(self.last_seen, key=lambda s: self.last_seen[s], reverse=True)

    def drop_idle(self, now: datetime | None = None) -> list[str]:
        stamp = as_utc(now or self.clock.now())
        dropped: list[str] = []
        for symbol, seen in list(self.last_seen.items()):
            age = (stamp - as_utc(seen)).total_seconds()
            if age > self.idle_ttl_seconds:
                del self.last_seen[symbol]
                dropped.append(symbol)
        return dropped

    def _evict_oldest(self) -> str | None:
        if not self.last_seen:
            return None
        oldest = min(self.last_seen, key=lambda s: self.last_seen[s])
        del self.last_seen[oldest]
        return oldest

    def touch(self, symbol: str, now: datetime | None = None) -> bool:
        """Add or refresh a name. Returns True if newly added."""
        clean = sanitize_ticker(symbol)
        if clean is None:
            return False
        stamp = as_utc(now or self.clock.now())
        self.drop_idle(stamp)
        if clean in self.last_seen:
            self.last_seen[clean] = stamp
            return False
        if len(self.last_seen) >= self.bound:
            self._evict_oldest()
        if len(self.last_seen) >= self.bound:
            raise WatchlistBoundError(f"quote interest bound {self.bound} exceeded")
        self.last_seen[clean] = stamp
        return True

    def note_fresh_print(
        self,
        ticker: str,
        *,
        now: datetime | None = None,
        freshness: SitMatchFreshness | None = None,
        fresh: bool | None = None,
    ) -> bool:
        """Touch only when the print is fresh. Stale → no expand."""
        if fresh is False:
            return False
        if freshness is not None and not freshness.allow:
            return False
        if freshness is None and fresh is None:
            return False
        return self.touch(ticker, now)

    def note_flow_row(
        self,
        row: FlowRow,
        now: datetime,
        *,
        env: Mapping[str, str] | None = None,
    ) -> bool:
        decision = evaluate_sit_match_freshness(row.executed_at, now, env=env)
        return self.note_fresh_print(row.ticker, now=now, freshness=decision)

    def state_document(self, *, now: datetime | None = None) -> dict[str, Any]:
        stamp = as_utc(now or self.clock.now())
        return {
            "source": "tradier_quote_interest",
            "note": NEVER_ORDERS_NOTE,
            "as_of": stamp.isoformat(),
            "symbols": self.symbols(),
            "bound": self.bound,
            "idle_ttl_seconds": self.idle_ttl_seconds,
            "places_orders": False,
            "live_socket": False,
            "host_owned_tape": "ws_tape.py",
        }
