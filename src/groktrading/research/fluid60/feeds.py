"""Read-only market-data adapters. Credentials are read from the environment only."""

from __future__ import annotations

import importlib
import os
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import AwareDatetime, Field

from .schema import BookFrame, Event, Flows, Level, OptionFlow, Quote, Strict, digest


class QuoteTerms(Strict):
    """Explicit provider units and contract terms; no guesses from ticker text."""

    underlying: str
    asset: str
    expires_at: AwareDatetime | None = None
    size_multiplier: int = Field(ge=1, le=100)
    theta_per_day_scale: float = Field(gt=0)
    vega_per_vol_point_scale: float = Field(gt=0)


def tradier_quote(row: dict[str, Any], terms: QuoteTerms, received: datetime) -> Quote:
    """Production quote with the older of its bid/ask timestamps as freshness clock.

    Greek units must be declared in terms after checking the provider contract.
    Absent Greek timestamps remain absent, so options cannot enter on them.
    """

    def epoch(value: Any) -> datetime:
        number = float(value)
        if number <= 0:
            raise ValueError("missing quote timestamp")
        return datetime.fromtimestamp(number / 1000 if number > 1e10 else number, UTC)

    event_at = min(epoch(row["bid_date"]), epoch(row["ask_date"]))
    greeks = row.get("greeks") or {}
    updated = greeks.get("updated_at")
    greeks_at = datetime.fromisoformat(str(updated).replace("Z", "+00:00")) if updated else None
    values: dict[str, Any] = {}
    for source, target, scale in (
        ("delta", "delta", 1),
        ("gamma", "gamma", 1),
        ("theta", "theta_per_day", terms.theta_per_day_scale),
        ("vega", "vega_per_vol_point", terms.vega_per_vol_point_scale),
    ):
        if greeks.get(source) is not None:
            values[target] = float(greeks[source]) * scale
    return Quote.model_validate(
        {
            "event_id": digest([row, received.isoformat()]),
            "symbol": row["symbol"],
            "underlying": terms.underlying,
            "asset": terms.asset,
            "source": "tradier_production",
            "event_at": event_at,
            "received_at": received,
            "bid": row["bid"],
            "ask": row["ask"],
            "bid_size": int(row["bidsize"]) * terms.size_multiplier,
            "ask_size": int(row["asksize"]) * terms.size_multiplier,
            "multiplier": 1 if terms.asset == "stock" else 100,
            "delayed": row.get("delayed", False),
            "greeks_at": greeks_at,
            "expires_at": terms.expires_at,
            **values,
        }
    )


def tradier_snapshot(terms: dict[str, QuoteTerms]) -> list[Quote]:
    """Single read-only production market quote request; no account or order endpoints."""
    if not terms:
        raise ValueError("empty quote universe")
    response = httpx.get(
        "https://api.tradier.com/v1/markets/quotes",
        params={"symbols": ",".join(terms), "greeks": "true"},
        headers={
            "Authorization": "Bearer " + os.environ["TRADIER_PRODUCTION_TOKEN"],
            "Accept": "application/json",
        },
        timeout=10,
    )
    received = datetime.now(UTC)
    if response.status_code != 200:
        raise ValueError(f"Tradier quote HTTP {response.status_code}")
    rows = response.json()["quotes"]["quote"]
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or {r["symbol"] for r in rows} != set(terms):
        raise ValueError("missing or unexpected quote symbols")
    return [tradier_quote(row, terms[row["symbol"]], received) for row in rows]


class MBOBook:
    """XNAS ITCH only; rebuild from clear + full snapshot/start-of-day replay.

    Caller supplies complete F_LAST batches. A, C and M change the book; F and T
    do not. F associates a decrement with execution rather than cancellation.
    Sequence regressions and unknown orders invalidate the reconstruction.
    """

    def __init__(self, symbol: str, levels: int = 64) -> None:
        self.symbol, self.levels = symbol, levels
        self.orders: dict[int, tuple[str, float, int]] = {}
        self.initialized = False
        self.sequence = -1
        self.publisher: int | None = None
        self.start: datetime | None = None
        self.totals: dict[str, float] = defaultdict(float)
        self.snapshot = False

    def apply(self, batch: list[dict[str, Any]], at: datetime) -> list[Event]:
        if not batch:
            return []
        fills: dict[int, int] = defaultdict(int)
        for row in batch:
            if row["action"] == "F":
                fills[int(row["order_id"])] += int(row["size"])
        for row in batch:
            action, oid = str(row["action"]), int(row["order_id"])
            sequence, publisher = int(row["sequence"]), int(row["publisher_id"])
            snapshot = bool(row.get("snapshot", False))
            if self.publisher is not None and publisher != self.publisher:
                raise ValueError("mixed publishers in XNAS book")
            self.publisher = publisher
            if sequence < self.sequence and not snapshot and action != "R":
                raise ValueError("sequence regression; rebuild from snapshot")
            self.sequence = sequence
            if action == "R":
                self.orders.clear()
                self.initialized = True
                self.start = at
                self.totals.clear()
            if not self.initialized:
                raise ValueError("missing initial clear/snapshot; do not start MBO midstream")
            if self.snapshot and not snapshot:
                self.start = at
                self.totals.clear()
            self.snapshot = snapshot
            if action in ("R", "F", "T", "N"):
                continue
            side, price, size = str(row["side"]), float(row["price"]), int(row["size"])
            if side not in ("A", "B") or price <= 0 or size < 0:
                raise ValueError("invalid depth event")
            label = "bid" if side == "B" else "ask"
            if action == "A":
                if oid in self.orders or size == 0:
                    raise ValueError("duplicate/empty add")
                self.orders[oid] = (side, price, size)
                if not snapshot:
                    self.totals[label + "_add"] += size
            elif action in ("C", "M"):
                if oid not in self.orders:
                    raise ValueError("unknown order; rebuild from snapshot")
                old_side, old_price, old_size = self.orders[oid]
                if side != old_side:
                    raise ValueError("order changed side")
                if action == "C":
                    if price != old_price or size > old_size:
                        raise ValueError("invalid cancel")
                    executed = min(size, fills[oid])
                    fills[oid] -= executed
                    self.totals["sell" if side == "B" else "buy"] += executed
                    self.totals[label + "_cancel"] += size - executed
                    if size == old_size:
                        del self.orders[oid]
                    else:
                        self.orders[oid] = (side, price, old_size - size)
                else:
                    # Replace treated as source/sink, never falsely as an execution.
                    self.totals[label + "_cancel"] += (
                        old_size if price != old_price else max(old_size - size, 0)
                    )
                    self.totals[label + "_add"] += (
                        size if price != old_price else max(size - old_size, 0)
                    )
                    if size:
                        self.orders[oid] = (side, price, size)
                    else:
                        del self.orders[oid]
            else:
                raise ValueError(f"unsupported MBO action {action}")
        if self.snapshot or self.start is None or (at - self.start).total_seconds() < 1:
            return []
        depth: dict[str, dict[float, int]] = {"B": defaultdict(int), "A": defaultdict(int)}
        for side, price, size in self.orders.values():
            depth[side][price] += size
        bids = tuple(
            Level(price=p, size=depth["B"][p])
            for p in sorted(depth["B"], reverse=True)[: self.levels]
        )
        asks = tuple(Level(price=p, size=depth["A"][p]) for p in sorted(depth["A"])[: self.levels])
        if len(bids) < 2 or len(asks) < 2 or bids[0].price >= asks[0].price:
            # Keep interval open: subsequent recovery still exposes the gap to the model.
            return []
        event_at = datetime.fromisoformat(str(batch[-1]["event_at"]))
        identity = f"{self.symbol}:{self.sequence}:{at.isoformat()}"
        frame = BookFrame(
            event_id=identity,
            symbol=self.symbol,
            source="xnas_itch",
            interval_start=self.start,
            event_at=event_at,
            received_at=at,
            bids=bids,
            asks=asks,
            flows=Flows.model_validate(dict(self.totals)),
        )
        self.start = at
        self.totals.clear()
        quote = Quote(
            event_id=identity,
            symbol=self.symbol,
            underlying=self.symbol,
            asset="stock",
            source="xnas_itch",
            event_at=event_at,
            received_at=at,
            bid=bids[0].price,
            ask=asks[0].price,
            bid_size=int(bids[0].size),
            ask_size=int(asks[0].size),
        )
        return [frame, quote]


def databento_events(
    symbol: str,
    *,
    start: str | None = None,
    end: str | None = None,
    historical_delay_ms: float = 100,
    levels: int = 64,
) -> Iterator[Event]:
    """One-symbol historical replay or live snapshot stream using the optional SDK.

    History requires a range beginning before the daily clear. ts_recv plus an
    explicit simulated delivery delay is used; live uses local receipt time.
    Any feed error terminates capture, requiring a new snapshot on restart.
    """
    if historical_delay_ms < 0:
        raise ValueError("negative delivery delay")
    db = importlib.import_module("databento")
    key = os.environ["DATABENTO_API_KEY"]
    book = MBOBook(symbol, levels)
    if (start is None) != (end is None):
        raise ValueError("provide both start and end, or neither for live")
    live: Any = None
    if start is not None:
        data = db.Historical(key).timeseries.get_range(
            dataset="XNAS.ITCH", schema="mbo", symbols=[symbol], start=start, end=end
        )
    else:
        live = db.Live(key=key)
        live.subscribe(dataset="XNAS.ITCH", schema="mbo", symbols=[symbol], snapshot=True)
        data = live
    batch: list[dict[str, Any]] = []
    try:
        for record in data:
            if isinstance(record, db.ErrorMsg):
                raise ValueError("Databento feed error; restart from a fresh snapshot")
            if not isinstance(record, db.MBOMsg):
                continue
            if record.flags & db.RecordFlags.F_TOB:
                raise ValueError("top-of-book normalization is not full XNAS depth")
            if record.flags & (db.RecordFlags.F_BAD_TS_RECV | db.RecordFlags.F_MAYBE_BAD_BOOK):
                raise ValueError("feed marked suspect timestamps/book; rebuild before replay")
            received = (
                datetime.now(UTC)
                if live is not None
                else datetime.fromtimestamp(record.ts_recv / 1e9, UTC)
                + timedelta(milliseconds=historical_delay_ms)
            )
            batch.append(
                {
                    "action": str(record.action),
                    "order_id": record.order_id,
                    "sequence": record.sequence,
                    "publisher_id": record.publisher_id,
                    "side": str(record.side),
                    "size": record.size,
                    "price": record.price / db.FIXED_PRICE_SCALE,
                    "snapshot": bool(record.flags & db.RecordFlags.F_SNAPSHOT),
                    "event_at": datetime.fromtimestamp(record.ts_event / 1e9, UTC).isoformat(),
                }
            )
            if record.flags & db.RecordFlags.F_LAST:
                yield from book.apply(batch, received)
                batch = []
        if batch:
            raise ValueError("truncated event batch")
    finally:
        if live is not None:
            live.stop()


def signed_option_flow(
    *,
    trade_id: str,
    symbol: str,
    executed_at: datetime,
    received_at: datetime,
    side: str,
    size: int,
    delta: float,
    multiplier: int = 100,
    multileg: bool = False,
    canceled: bool = False,
    revision_of: str | None = None,
) -> OptionFlow | None:
    """Normalize a provider-classified UW trade. Unknown/multileg flow is excluded.

    Side is the option aggressor's buy/sell, delta is signed (puts negative).
    This is a directional exposure proxy, not observed dealer hedge demand.
    """
    if side not in ("buy", "sell") or multileg:
        return None
    if size < 0 or multiplier != 100 or not -1 <= delta <= 1:
        raise ValueError("unsupported option trade")
    return OptionFlow(
        event_id=trade_id,
        symbol=symbol,
        source="uw",
        event_at=executed_at,
        received_at=received_at,
        revision_of=revision_of,
        signed_delta_shares=0
        if canceled
        else (1 if side == "buy" else -1) * size * multiplier * delta,
    )
