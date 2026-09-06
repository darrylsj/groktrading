"""Read-only, rate-limited capture from documented UW and Tradier production APIs."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from groktrading.research.opening15 import (
    NY,
    Config,
    Event,
    Packet,
    digest,
    now_utc,
    stamp,
    window,
    write_once,
)


class ReadFeed:
    def __init__(self, base: str, key: str, rpm: int, client: httpx.Client | None = None) -> None:
        self.base = base
        self.key = key
        self.interval = 60 / rpm
        self.last_request = 0.0
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)
        self.lock = threading.Lock()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        # This adapter has NO order endpoint or POST method.
        if not path.startswith(("/api/option-trades", "/api/news/headlines", "/markets/")):
            raise ValueError("read endpoint not allowed")
        with self.lock:
            delay = self.interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            response = self.client.get(
                self.base + path,
                params=params,
                headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
            )
        if response.status_code != 200:
            raise ValueError(f"feed HTTP {response.status_code}; no response/credential logging")
        return response.json()

    def close(self) -> None:
        self.client.close()


def credentials() -> tuple[str, str, str]:
    names = {
        "UW_API_TOKEN/UW_API_KEY": os.getenv("UW_API_TOKEN") or os.getenv("UW_API_KEY"),
        "TRADIER_ACCESS_TOKEN": os.getenv("TRADIER_ACCESS_TOKEN"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    }
    missing = [name for name, value in names.items() if not value or value.startswith("YOUR_")]
    if missing:
        raise ValueError("missing environment variables: " + ", ".join(missing))
    return tuple(str(v) for v in names.values())  # type: ignore[return-value]


def feeds(config: Config) -> tuple[ReadFeed, ReadFeed]:
    uw, tradier, _ = credentials()
    if os.getenv("TRADIER_ENV", "production") != "production":
        raise ValueError("production market data required (read-only)")
    return (
        ReadFeed("https://api.unusualwhales.com", uw, config.uw_requests_per_minute),
        ReadFeed("https://api.tradier.com/v1", tradier, config.tradier_requests_per_minute),
    )


def as_rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ValueError("unexpected provider rows")
    return value


def session_open(feed: ReadFeed, day: date) -> bool:
    body = feed.get("/markets/calendar", {"month": day.month, "year": day.year})
    days = as_rows(body.get("calendar", {}).get("days", {}).get("day"))
    matches = [d for d in days if d.get("date") == day.isoformat()]
    if len(matches) != 1:
        raise ValueError("market calendar missing session")
    return bool(
        matches[0].get("status") == "open"
        and matches[0].get("open", {}).get("start") == "09:30"
        and matches[0].get("open", {}).get("end") == "16:00"
    )


def quotes(feed: ReadFeed, symbols: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for offset in range(0, len(symbols), 100):
        body = feed.get(
            "/markets/quotes",
            {"symbols": ",".join(symbols[offset : offset + 100]), "greeks": "true"},
        )
        result.extend(as_rows((body.get("quotes") or {}).get("quote")))
    return result


class FlowCapture:
    """Bisect capped time ranges instead of dropping equal-timestamp page boundaries."""

    def __init__(self, feed: ReadFeed, config: Config, directory: Path, deadline: datetime) -> None:
        self.feed, self.config, self.directory, self.deadline = feed, config, directory, deadline
        self.requests = 0
        self.events: dict[str, Event] = {}

    def interval(self, start: datetime, end: datetime) -> None:
        if now_utc() > self.deadline or self.requests >= self.config.max_flow_requests:
            raise ValueError("flow capture deadline/request budget exceeded; incomplete tape")
        self.requests += 1
        # One millisecond padding handles provider inclusive/exclusive time boundaries.
        body = self.feed.get(
            "/api/option-trades",
            {
                "ticker_symbol": ",".join(self.config.symbols),
                "limit": 500,
                "newer_than": int(start.timestamp() * 1000) - 1,
                "older_than": int(end.timestamp() * 1000) + 1,
                "include_agg_trades": "false",
                "force_15_min_delay": "false",
            },
        )
        received = now_utc()
        if "data" not in body:
            raise ValueError("missing UW data array")
        rows = as_rows(body["data"])
        write_once(
            self.directory / "raw" / f"flow-{self.requests:06d}.json",
            {
                "received_at": received.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "body": body,
            },
        )
        if len(rows) >= 500:
            if (end - start).total_seconds() <= 0.004:
                raise ValueError("saturated timestamp; cannot establish complete flow")
            midpoint = start + (end - start) / 2
            self.interval(start, midpoint)
            self.interval(midpoint, end)
            return
        for row in rows:
            event_at = stamp(row["executed_at"])
            if not start <= event_at <= end:
                continue
            symbol = str(row["underlying_symbol"])
            if symbol not in self.config.symbols:
                raise ValueError("UW ignored ticker filter")
            if not row.get("id") or not row.get("option_chain_id"):
                raise ValueError("UW trade identity/contract missing")
            key = "uw:" + str(row["id"])
            self.events[key] = Event(
                event_id=key,
                kind="option_trade",
                symbol=symbol,
                event_at=event_at,
                received_at=received,
                source="uw",
                raw=row,
            )


def collect(config: Config, day: date, directory: Path, uw: ReadFeed, tradier: ReadFeed) -> Packet:
    start, end = window(day)
    locked = now_utc()
    if locked.astimezone(NY).date() != day or locked >= start:
        raise ValueError("launch before 09:30 ET on the selected session; no retrospective run")
    if not session_open(tradier, day):
        raise ValueError("not a regular 09:30–16:00 session")
    write_once(
        directory / "config.json",
        {"locked_at": locked.isoformat(), "session": str(day), "config": config.model_dump()},
    )
    flow = FlowCapture(uw, config, directory, end + timedelta(minutes=2))
    events: list[Event] = []
    stop = threading.Event()
    errors: list[str] = []
    stock_batches = 0

    def stock_worker() -> None:
        nonlocal stock_batches
        try:
            while not stop.is_set() and now_utc() < end:
                if now_utc() < start:
                    stop.wait(min(1, max(0, (start - now_utc()).total_seconds())))
                    continue
                rows = quotes(tradier, list(dict.fromkeys(config.symbols + config.context_symbols)))
                received = now_utc()
                stock_batches += 1
                write_once(
                    directory / "raw" / f"stocks-{stock_batches:06d}.json",
                    {"received_at": received.isoformat(), "rows": rows},
                )
                for row in rows:
                    if row.get("delayed") not in (None, False):
                        raise ValueError("delayed stock quote")
                    event_at = stamp(row["trade_date"])
                    if start <= event_at <= received <= end:
                        events.append(
                            Event(
                                event_id="stock:" + digest([row, received.isoformat()]),
                                kind="stock_quote",
                                symbol=row["symbol"],
                                event_at=event_at,
                                received_at=received,
                                source="tradier_production",
                                raw=row,
                            )
                        )
                stop.wait(config.poll_seconds)
        except Exception as exc:
            errors.append(type(exc).__name__)
            stop.set()

    # News is a bounded context sample, explicitly not an exhaustive news archive.
    news_count: dict[str, int] = {}
    for symbol in config.symbols:
        rows = as_rows(uw.get("/api/news/headlines", {"ticker": symbol, "limit": 100})["data"])
        received = now_utc()
        news_count[symbol] = len(rows)
        for row in rows:
            event_at = stamp(row["created_at"])
            if event_at <= min(received, end):
                key = "news:" + digest([row, symbol])
                events.append(
                    Event(
                        event_id=key,
                        kind="news",
                        symbol=symbol,
                        event_at=event_at,
                        received_at=received,
                        source="uw",
                        raw=row,
                    )
                )
    if now_utc() >= start:
        raise ValueError("preopen news setup overran open; launch earlier")
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(stock_worker)
        cursor = start
        try:
            while cursor < end:
                target = min(cursor + timedelta(seconds=config.poll_seconds), end)
                while now_utc() < target + timedelta(seconds=2):
                    if errors:
                        raise ValueError("stock capture failed")
                    time.sleep(
                        min(
                            1,
                            max(0.01, (target + timedelta(seconds=2) - now_utc()).total_seconds()),
                        )
                    )
                flow.interval(max(start, cursor - timedelta(seconds=1)), target)
                cursor = target
                print(
                    f"Opening15 capture: {len(flow.events)} unique prints; "
                    f"through {target.astimezone(NY).strftime('%H:%M:%S')} ET",
                    flush=True,
                )
            # Recheck the last minute for late updates; freeze at actual receipt.
            flow.interval(end - timedelta(minutes=1), end)
        finally:
            stop.set()
            worker.result()
    if errors:
        raise ValueError("stock capture failed")
    freeze = now_utc()
    events += list(flow.events.values())
    events.sort(key=lambda e: (e.event_at, e.event_id))
    packet = Packet(
        session=day,
        config=config,
        config_locked_at=locked,
        knowledge_cutoff=freeze,
        synthetic=False,
        events=events,
        coverage={
            "flow_complete": True,
            "flow_requests": flow.requests,
            "flow_trade_counts": {
                s: sum(e.symbol == s for e in flow.events.values()) for s in config.symbols
            },
            "news_sample_counts": news_count,
            "limitations": [
                "UW-returned prints, not independently OPRA-reconciled",
                "News is a preopen sample of up to 100 per stock",
                "Options NBBO/Greeks are sampled at prints, not every quote",
                "Selection universe is contracts that printed",
                "Cumulative provider fields may be revised at retrieval",
                "No after-cutoff stock quotes used",
            ],
        },
    )
    write_once(directory / "packet.json", packet.model_dump(mode="json"))
    return packet
