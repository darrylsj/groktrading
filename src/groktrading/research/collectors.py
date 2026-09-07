"""Expanded Context collectors using documented UW, Tradier, and Finnhub GET APIs.

Schwab OAuth is not connected. Portfolio snapshots are Tradier account
balances/positions/orders (read-only) until Schwab lands. Depth is omitted.
Macro/economic calendar uses UW GET /api/market/economic-calendar (Finnhub
/calendar/economic is unused; our plan returns 403). Dark pool, option screener,
market tide, and congress/insider slices are optional expanded LLM features.
No order submit, preview, or invented endpoints.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import httpx

from groktrading.feeds.finnhub import FINNHUB_REST_BASE
from groktrading.research.capture import (
    ReadFeed,
    as_rows,
    quotes,
)
from groktrading.research.cycle import (
    CATEGORIES,
    Category,
    Context,
    Coverage,
    CoverageStatus,
    Evidence,
)
from groktrading.research.opening15 import (
    NY,
    Config,
    Event,
    Packet,
    digest,
    now_utc,
    stamp,
    write_once,
)

Clock = Callable[[], datetime]

# Tradier production index symbol. Entitlement is not assumed; missing is labeled.
DEFAULT_MACRO_SYMBOLS = ("SPY", "QQQ", "XLK", "XLY", "IWM", "$VIX.X")
MAX_WORLD_NEWS = 50
CHAIN_EXPIRATION_LIMIT = 3
HISTORY_LOOKBACK_CALENDAR_DAYS = 45
SOURCE_UW_HEADLINES = "https://api.unusualwhales.com/api/news/headlines"
SOURCE_UW_TRADES = "https://api.unusualwhales.com/api/option-trades"
SOURCE_UW_ECONOMIC_CALENDAR = "https://api.unusualwhales.com/api/market/economic-calendar"
SOURCE_UW_DARKPOOL = "https://api.unusualwhales.com/api/darkpool"
SOURCE_UW_SCREENER = "https://api.unusualwhales.com/api/screener/option-contracts"
SOURCE_UW_MARKET_TIDE = "https://api.unusualwhales.com/api/market/market-tide"
SOURCE_UW_CONGRESS = "https://api.unusualwhales.com/api/congress/recent-trades"
SOURCE_UW_INSIDER = "https://api.unusualwhales.com/api/insider/transactions"
DARKPOOL_ROWS_PER_SYMBOL = 15
DARKPOOL_RECENT_ROWS = 15
SCREENER_FETCH_LIMIT = 40
SCREENER_PER_SYMBOL = 3
TIDE_ROW_CAP = 12
POLITICAL_FETCH_LIMIT = 100
INSIDER_FETCH_LIMIT = 50
DARKPOOL_FIELDS = (
    "ticker",
    "price",
    "size",
    "executed_at",
    "volume",
    "premium",
    "nbbo_bid",
    "nbbo_ask",
)
SCREENER_FIELDS = (
    "ticker_symbol",
    "option_symbol",
    "type",
    "strike",
    "expiry",
    "ask_side_volume",
    "bid_side_volume",
    "volume",
    "open_interest",
    "avg_price",
    "premium",
    "implied_volatility",
)
TIDE_FIELDS = ("timestamp", "date", "net_call_premium", "net_put_premium", "net_volume")
CONGRESS_FIELDS = (
    "ticker",
    "txn_type",
    "amounts",
    "filed_at_date",
    "transaction_date",
    "name",
    "reporter",
    "member_type",
    "issuer",
)
INSIDER_FIELDS = (
    "ticker",
    "ticker_symbol",
    "transaction_date",
    "transaction_code",
    "owner_name",
    "amount",
    "price",
    "value",
)
SOURCE_TRADIER_QUOTES = "https://api.tradier.com/v1/markets/quotes"
SOURCE_TRADIER_CALENDAR = "https://api.tradier.com/v1/markets/calendar"
SOURCE_TRADIER_HISTORY = "https://api.tradier.com/v1/markets/history"
SOURCE_TRADIER_EXPIRATIONS = "https://api.tradier.com/v1/markets/options/expirations"
SOURCE_TRADIER_CHAINS = "https://api.tradier.com/v1/markets/options/chains"
SOURCE_TRADIER_BALANCES = "https://api.tradier.com/v1/accounts/balances"
SOURCE_TRADIER_POSITIONS = "https://api.tradier.com/v1/accounts/positions"
SOURCE_TRADIER_ORDERS = "https://api.tradier.com/v1/accounts/orders"
SOURCE_FINNHUB_NEWS = "https://finnhub.io/api/v1/news"


class FinnhubRest:
    """Bounded Finnhub GET client. World news only; no invented paths."""

    def __init__(self, token: str, client: httpx.Client | None = None, rpm: int = 60) -> None:
        self.token = token
        self.interval = 60 / rpm
        self.last_request = 0.0
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)
        self.lock = threading.Lock()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if path != "/news":
            raise ValueError("finnhub research path not allowed")
        with self.lock:
            delay = self.interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            response = self.client.get(
                FINNHUB_REST_BASE + path,
                params=params,
                headers={"X-Finnhub-Token": self.token, "Accept": "application/json"},
            )
        if response.status_code in {401, 403}:
            raise ValueError("finnhub news entitlement missing")
        if response.status_code != 200:
            raise ValueError(f"finnhub HTTP {response.status_code}; no response/credential logging")
        return response.json()

    def close(self) -> None:
        self.client.close()


def optional_finnhub(client: httpx.Client | None = None) -> FinnhubRest | None:
    token = os.getenv("FINNHUB_API_KEY")
    if not token or token.startswith("YOUR_"):
        return None
    return FinnhubRest(token, client=client)


def optional_account_id() -> str | None:
    value = os.getenv("TRADIER_ACCOUNT_ID")
    if not value or value.startswith("YOUR_"):
        return None
    return value


def account_alias(account_id: str) -> str:
    return "acct-" + hashlib.sha256(account_id.encode()).hexdigest()[:12]


def _clock(clock: Clock | None) -> Clock:
    return clock or now_utc


def _summary(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:1200] if cleaned else "empty provider payload"


def _drop_secret_keys(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if re_secret_key(str(key)):
                continue
            out[str(key)] = _drop_secret_keys(item)
        return out
    if isinstance(value, list):
        return [_drop_secret_keys(item) for item in value]
    return value


def re_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in ("token", "secret", "password", "api_key", "account_id", "account_number")
    )


def _empty_tradier(value: Any) -> bool:
    """Tradier XML-to-JSON often encodes missing nodes as null, \"null\", or []."""
    return value is None or value == "" or value == "null" or value == []


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if _empty_tradier(value):
        return {}
    if isinstance(value, dict):
        return value
    raise ValueError(f"unexpected Tradier {label} object")


def _walk(body: Any, *keys: str, label: str) -> Any:
    """Descend Tradier wrappers without calling .get on strings or lists."""
    current: Any = body
    for key in keys:
        if _empty_tradier(current):
            return None
        if not isinstance(current, dict):
            raise ValueError(f"unexpected Tradier {label} wrapper")
        current = current.get(key)
    return current


def _dicts(value: Any, *, label: str) -> list[dict[str, Any]]:
    """Normalize one-or-many Tradier rows. Never assume every element is a dict."""
    if _empty_tradier(value):
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        rows = [item for item in value if isinstance(item, dict)]
        if value and not rows:
            raise ValueError(f"unexpected Tradier {label} rows")
        return rows
    raise ValueError(f"unexpected Tradier {label} rows")


def _nested_field(mapping: Any, *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _known_amount(*values: Any) -> Any:
    """Treat 0 as a known cash/BP figure; only None/blank/null are unknown."""
    for value in values:
        if value in (None, "", "null"):
            continue
        return value
    return None


def _write_raw(directory: Path, name: str, payload: dict[str, Any]) -> None:
    path = directory / "raw" / name
    if not path.exists():
        write_once(path, payload)


def calendar_days(feed: ReadFeed, month: int, year: int) -> list[dict[str, Any]]:
    body = feed.get("/markets/calendar", {"month": month, "year": year})
    return as_rows(((body or {}).get("calendar") or {}).get("days", {}).get("day"))


def prior_open_session(feed: ReadFeed, session: date) -> date | None:
    cursor = date(session.year, session.month, 1)
    seen: list[date] = []
    for offset in (0, -1):
        month = cursor.month + offset
        year = cursor.year
        if month <= 0:
            month += 12
            year -= 1
        for row in calendar_days(feed, month, year):
            raw = str(row.get("date") or "")
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            if row.get("status") == "open" and day < session:
                seen.append(day)
    return max(seen) if seen else None


def _history_days(body: Any) -> list[dict[str, Any]]:
    return as_rows(((body or {}).get("history") or {}).get("day"))


def _expirations(body: Any) -> list[str]:
    raw = ((body or {}).get("expirations") or {}).get("date")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    raise ValueError("unexpected expirations payload")


def _chain_rows(body: Any) -> list[dict[str, Any]]:
    return as_rows(((body or {}).get("options") or {}).get("option"))


def _realized_vol(closes: list[float]) -> float | None:
    if len(closes) < 3:
        return None
    returns: list[float] = []
    for prior, current in zip(closes, closes[1:], strict=False):
        if prior <= 0 or current <= 0:
            continue
        returns.append(math.log(current / prior))
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(252)


def collect_company_news(
    *,
    config: Config,
    uw: ReadFeed,
    news_events: list[Event],
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    records: list[Evidence] = []
    seen_set: set[str] = set()
    source_events = [event for event in news_events if event.kind == "news"]
    if not source_events:
        for symbol in config.symbols:
            body = uw.get("/api/news/headlines", {"ticker": symbol, "limit": 100})
            rows = as_rows((body or {}).get("data"))
            fetched = clock()
            for row in rows:
                event_at = stamp(row.get("created_at") or row.get("timestamp") or fetched)
                source_events.append(
                    Event(
                        event_id="news:" + digest([row, symbol]),
                        kind="news",
                        symbol=symbol,
                        event_at=event_at,
                        received_at=fetched,
                        source="uw",
                        raw=row,
                    )
                )
    versions: dict[str, int] = {}
    for event in source_events:
        story = str(event.raw.get("id") or event.event_id)
        versions[story] = versions.get(story, 0) + 1
        evidence_id = f"company-news:{story}:v{versions[story]}"
        if evidence_id in seen_set:
            continue
        seen_set.add(evidence_id)
        headline = str(event.raw.get("headline") or event.raw.get("title") or "UW headline")
        records.append(
            Evidence(
                evidence_id=evidence_id,
                category="company_news",
                symbols=[event.symbol],
                source="unusual_whales",
                source_uri=SOURCE_UW_HEADLINES,
                as_of=event.event_at,
                received_at=event.received_at,
                summary=_summary(f"{event.symbol}: {headline}"),
                payload=_drop_secret_keys(
                    {
                        "story_id": story,
                        "version": versions[story],
                        "headline": headline,
                        "detail_hook": "archived_local_payload",
                        "uw_news_body_endpoint": "none_in_official_skill",
                        "fields": event.raw,
                    }
                ),
            )
        )
    if not records:
        return [], Coverage(
            category="company_news",
            status="missing",
            detail="UW headlines returned no usable preopen stories",
        )
    missing_symbols = [s for s in config.symbols if not any(s in r.symbols for r in records)]
    status: CoverageStatus = "partial" if missing_symbols else "available"
    return records, Coverage(
        category="company_news",
        status=status,
        detail=(
            f"{len(records)} UW headline versions archived; local detail hook only; "
            f"no UW article-body endpoint. missing_symbols={missing_symbols or 'none'}"
        ),
    )


def archived_news_detail(context: Context, evidence_id: str) -> dict[str, Any]:
    """Local archive lookup. UW official skill has headlines only, not article bodies."""
    return context.retrieve([evidence_id])[0]


def collect_world_news(
    *,
    finnhub: FinnhubRest | None,
    frozen_at: datetime,
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    if finnhub is None:
        return [], Coverage(
            category="world_news",
            status="missing",
            detail=(
                "Finnhub GET /news?category=general unused (no FINNHUB_API_KEY). "
                "UW official skill has ticker headlines only, not a world-news feed. "
                "Not fabricated."
            ),
        )
    try:
        body = finnhub.get("/news", {"category": "general"})
    except ValueError as exc:
        return [], Coverage(
            category="world_news",
            status="missing",
            detail=f"Finnhub general news not entitled or failed ({exc})",
        )
    if not isinstance(body, list):
        return [], Coverage(
            category="world_news",
            status="missing",
            detail="Finnhub general news returned a non-list payload",
        )
    records: list[Evidence] = []
    received = clock()
    for row in body:
        if not isinstance(row, dict):
            continue
        raw_ts = row.get("datetime")
        if raw_ts in (None, ""):
            continue
        as_of = stamp(raw_ts)
        if as_of > frozen_at or as_of > received:
            continue
        story = str(row.get("id") or digest(row))
        headline = str(row.get("headline") or row.get("summary") or "Finnhub headline")
        records.append(
            Evidence(
                evidence_id=f"world-news:{story}",
                category="world_news",
                symbols=[],
                source="finnhub",
                source_uri=SOURCE_FINNHUB_NEWS,
                as_of=as_of,
                received_at=received,
                summary=_summary(headline),
                payload=_drop_secret_keys(
                    {
                        "category": row.get("category") or "general",
                        "headline": headline,
                        "source_name": row.get("source"),
                        "related": row.get("related"),
                        "url": row.get("url"),
                        "summary": row.get("summary"),
                    }
                ),
            )
        )
        if len(records) >= MAX_WORLD_NEWS:
            break
    if not records:
        return [], Coverage(
            category="world_news",
            status="missing",
            detail="Finnhub general news entitled but returned no pre-freeze headlines",
        )
    return records, Coverage(
        category="world_news",
        status="available",
        detail=(
            f"{len(records)} Finnhub general headlines at or before freeze; "
            f"bounded to {MAX_WORLD_NEWS}"
        ),
    )


def collect_macro(
    *,
    config: Config,
    tradier: ReadFeed,
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    symbols = list(dict.fromkeys([*config.context_symbols, *DEFAULT_MACRO_SYMBOLS]))
    try:
        rows = quotes(tradier, symbols)
        received = clock()
    except ValueError as exc:
        return [], Coverage(
            category="macro",
            status="missing",
            detail=f"Tradier macro quotes failed ({exc})",
        )
    by_symbol = {str(row.get("symbol") or ""): row for row in rows if isinstance(row, dict)}
    records: list[Evidence] = []
    missing: list[str] = []
    delayed: list[str] = []
    for symbol in symbols:
        row = by_symbol.get(symbol)
        if row is None:
            missing.append(symbol)
            continue
        if row.get("delayed") not in (None, False):
            delayed.append(symbol)
        trade_at = row.get("trade_date") or row.get("bid_date") or row.get("ask_date")
        as_of = stamp(trade_at) if trade_at not in (None, "", 0, "0") else received
        if as_of > received:
            as_of = received
        records.append(
            Evidence(
                evidence_id=f"macro:{symbol}",
                category="macro",
                symbols=[symbol],
                source="tradier_production",
                source_uri=SOURCE_TRADIER_QUOTES,
                as_of=as_of,
                received_at=received,
                summary=_summary(
                    f"{symbol} last={row.get('last')} bid={row.get('bid')} ask={row.get('ask')} "
                    f"delayed={row.get('delayed')}"
                ),
                payload=_drop_secret_keys(
                    {
                        "quote": row,
                        "missing_instrument": False,
                        "delayed": bool(row.get("delayed")),
                    }
                ),
            )
        )
    if not records:
        return [], Coverage(
            category="macro",
            status="missing",
            detail=f"No Tradier macro quotes. missing={missing}",
        )
    status: CoverageStatus = "available"
    if missing or delayed:
        status = "partial"
    return records, Coverage(
        category="macro",
        status=status,
        detail=(
            f"Tradier quotes for {len(records)} macro symbols. "
            f"missing={missing or 'none'} delayed={delayed or 'none'}. "
            "Rates/USD/commodities beyond these tickers are not fetched."
        ),
    )


def _economic_event_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Copy UW economic-calendar fields only. Do not invent actuals or prices."""
    event = row.get("event")
    if event in (None, ""):
        return None
    return {
        "event": event,
        "forecast": row.get("forecast"),
        "prev": row.get("prev"),
        "reported_period": row.get("reported_period"),
        "time": row.get("time"),
        "type": row.get("type"),
    }


def collect_economic_calendar(
    *,
    uw: ReadFeed,
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    """Expanded-only UW macro calendar. Empty data is available; HTTP/auth is missing."""
    try:
        body = uw.get("/api/market/economic-calendar")
        received = clock()
    except ValueError as exc:
        return [], Coverage(
            category="calendar",
            status="missing",
            detail=f"UW economic calendar not entitled or failed ({exc})",
        )
    if directory is not None:
        archived = body if isinstance(body, dict) else {"unexpected": True}
        _write_raw(
            directory,
            "uw-economic-calendar.json",
            {
                "received_at": received.isoformat(),
                "source_uri": SOURCE_UW_ECONOMIC_CALENDAR,
                "body": _drop_secret_keys(archived),
            },
        )
    if not isinstance(body, dict) or "data" not in body:
        return [], Coverage(
            category="calendar",
            status="missing",
            detail="UW economic calendar returned unexpected payload (no data array)",
        )
    raw_rows = body.get("data")
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, list):
        return [], Coverage(
            category="calendar",
            status="missing",
            detail="UW economic calendar data was not a list",
        )
    events: list[dict[str, Any]] = []
    skipped = 0
    for row in raw_rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        parsed = _economic_event_row(row)
        if parsed is None:
            skipped += 1
            continue
        events.append(parsed)
    status: CoverageStatus = "partial" if skipped else "available"
    quiet = " (quiet session, empty data)" if not events else ""
    record = Evidence(
        evidence_id="calendar:uw-economic",
        category="calendar",
        symbols=[],
        source="unusual_whales",
        source_uri=SOURCE_UW_ECONOMIC_CALENDAR,
        as_of=received,
        received_at=received,
        summary=_summary(f"UW economic calendar: {len(events)} events{quiet}"),
        payload={
            "event_count": len(events),
            "skipped_rows": skipped,
            "events": events,
            "note": (
                "Provider forecast/prev copied as-is; no invented actuals or prices. "
                "Empty data is a valid quiet calendar, not missing coverage. "
                "as_of is archive receipt, not future event occurrence."
            ),
            "finnhub_economic_calendar": "not_used_plan_returns_403",
        },
    )
    return [record], Coverage(
        category="calendar",
        status=status,
        detail=(
            f"UW GET /api/market/economic-calendar: {len(events)} events, "
            f"skipped_rows={skipped}. Empty data is available, not missing. "
            "Finnhub /calendar/economic unused (403 on this plan)."
        ),
    )


def collect_calendar(
    *,
    config: Config,
    session: date,
    tradier: ReadFeed,
    uw: ReadFeed,
    flow_events: list[Event],
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    months = [(session.month, session.year)]
    nxt_month = 1 if session.month == 12 else session.month + 1
    nxt_year = session.year + 1 if session.month == 12 else session.year
    months.append((nxt_month, nxt_year))
    days: list[dict[str, Any]] = []
    for month, year in months:
        days.extend(calendar_days(tradier, month, year))
    received = clock()
    match = next((row for row in days if row.get("date") == session.isoformat()), None)
    version = digest({"days": days, "months": months})
    records = [
        Evidence(
            evidence_id=f"calendar:tradier:{version[:16]}",
            category="calendar",
            symbols=list(config.symbols),
            source="tradier_production",
            source_uri=SOURCE_TRADIER_CALENDAR,
            as_of=received,
            received_at=received,
            summary=_summary(
                f"Tradier calendar version {version[:12]} published at receipt; "
                f"session {session} occurrence={match}"
            ),
            payload={
                "schedule_version": version,
                "published_at": received.isoformat(),
                "occurrence_time": {
                    "session": session.isoformat(),
                    "row": match,
                },
                "days": days,
            },
        )
    ]
    earnings_hits: list[dict[str, Any]] = []
    for event in flow_events:
        tokens: list[str] = []
        for key in ("tags", "tag", "earnings", "has_earnings"):
            value = event.raw.get(key)
            if isinstance(value, list):
                tokens.extend(str(item).lower() for item in value)
            elif value not in (None, "", False):
                tokens.append(str(value).lower())
        if any("earn" in token for token in tokens):
            earnings_hits.append(
                {
                    "event_id": event.event_id,
                    "symbol": event.symbol,
                    "as_of": event.event_at.isoformat(),
                    "fields": {
                        k: event.raw.get(k)
                        for k in ("tags", "tag", "earnings", "has_earnings")
                    },
                }
            )
    if earnings_hits:
        records.append(
            Evidence(
                evidence_id="calendar:print-earnings",
                category="calendar",
                symbols=sorted({str(item["symbol"]) for item in earnings_hits}),
                source="unusual_whales",
                source_uri=SOURCE_UW_TRADES,
                as_of=min(event.event_at for event in flow_events),
                received_at=max(event.received_at for event in flow_events),
                summary=_summary(
                    f"{len(earnings_hits)} UW prints already carried earnings-related fields"
                ),
                payload={
                    "prints": earnings_hits,
                    "note": "fields already on prints; not a schedule API",
                },
            )
        )
    econ_records, econ = collect_economic_calendar(uw=uw, clock=clock, directory=directory)
    records.extend(econ_records)
    if not days and econ.status == "missing":
        return [], Coverage(
            category="calendar",
            status="missing",
            detail="Tradier market calendar returned no days; UW economic calendar missing",
        )
    if not days:
        return records, Coverage(
            category="calendar",
            status="partial",
            detail=(
                "Tradier session calendar empty. "
                + econ.detail
                + " Dedicated earnings calendar is still print-fields only."
            ),
        )
    status: CoverageStatus = "available"
    if econ.status in {"missing", "partial"}:
        status = "partial"
    return records, Coverage(
        category="calendar",
        status=status,
        detail=(
            "Tradier /markets/calendar archived with schedule_version separate from "
            f"session occurrence. Print earnings fields={len(earnings_hits)}. "
            + econ.detail
            + " Dedicated earnings calendar remains print-fields only."
        ),
    )


def _provider_quote_stamp(row: dict[str, Any]) -> datetime | None:
    for key in ("ask_date", "bid_date", "trade_date", "quote_date"):
        value = row.get(key)
        if value in (None, "", 0, "0"):
            continue
        try:
            return stamp(value)
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    return None


def _chain_contract(
    row: dict[str, Any], expiration: str, received: datetime, max_age: int
) -> dict[str, Any]:
    greeks = row.get("greeks")
    bid_date = row.get("bid_date")
    ask_date = row.get("ask_date")
    contract: dict[str, Any] = {
        "symbol": row.get("symbol"),
        "option_type": row.get("option_type"),
        "strike": row.get("strike"),
        "expiration_date": row.get("expiration_date") or expiration,
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "bidsize": row.get("bidsize"),
        "asksize": row.get("asksize"),
        "last": row.get("last"),
        "volume": row.get("volume"),
        "bid_date": bid_date,
        "ask_date": ask_date,
        "trade_date": row.get("trade_date"),
        "quote_date": row.get("quote_date"),
        "prior_session_open_interest": row.get("open_interest"),
        "open_interest_label": "prior_day_provider_field",
        "greeks": greeks if isinstance(greeks, dict) else None,
        "greeks_label": "provider_orats_if_present" if greeks else "not_supplied",
    }
    ages: dict[str, float] = {}
    try:
        if bid_date not in (None, "", 0, "0"):
            ages["bid"] = (received - stamp(bid_date)).total_seconds()
        if ask_date not in (None, "", 0, "0"):
            ages["ask"] = (received - stamp(ask_date)).total_seconds()
    except (ValueError, TypeError, OverflowError, OSError):
        ages = {}
    if ages:
        contract["quote_ages_seconds"] = ages
        contract["quote_stale"] = any(age < 0 or age > max_age for age in ages.values())
    return contract


def collect_option_chain(
    *,
    config: Config,
    session: date,
    tradier: ReadFeed,
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    records: list[Evidence] = []
    missing: list[str] = []
    stale_contracts = 0
    dated_contracts = 0
    for symbol in config.symbols:
        symbol_records: list[Evidence] = []
        try:
            exp_body = tradier.get(
                "/markets/options/expirations",
                {"symbol": symbol, "includeAllRoots": "false"},
            )
            expirations = [item for item in _expirations(exp_body) if item >= session.isoformat()]
        except ValueError:
            missing.append(symbol)
            continue
        if not expirations:
            missing.append(symbol)
            continue
        for expiration in expirations[:CHAIN_EXPIRATION_LIMIT]:
            body = tradier.get(
                "/markets/options/chains",
                {"symbol": symbol, "expiration": expiration, "greeks": "true"},
            )
            received = clock()
            rows = _chain_rows(body)
            contracts: list[dict[str, Any]] = []
            provider_times: list[datetime] = []
            for row in rows:
                contract = _chain_contract(
                    row, expiration, received, config.max_quote_age_seconds
                )
                if "quote_ages_seconds" in contract:
                    dated_contracts += 1
                    if contract.get("quote_stale"):
                        stale_contracts += 1
                quoted = _provider_quote_stamp(row)
                if quoted is not None:
                    provider_times.append(quoted)
                contracts.append(contract)
            if not contracts:
                continue
            as_of = received
            if provider_times:
                latest = max(provider_times)
                as_of = latest if latest <= received else received
            symbol_records.append(
                Evidence(
                    evidence_id=f"chain:{symbol}:{expiration}",
                    category="option_chain",
                    symbols=[symbol],
                    source="tradier_production",
                    source_uri=SOURCE_TRADIER_CHAINS,
                    as_of=as_of,
                    received_at=received,
                    summary=_summary(
                        f"{symbol} {expiration} chain {len(contracts)} contracts; "
                        "OI labeled prior-day; Greeks only if Tradier returned them"
                    ),
                    payload={
                        "expiration": expiration,
                        "observed_at": received.isoformat(),
                        "provider_quote_as_of": as_of.isoformat(),
                        "contract_count": len(contracts),
                        "contracts": contracts,
                    },
                )
            )
        if not symbol_records:
            missing.append(symbol)
            continue
        records.extend(symbol_records)
    covered = {symbol for record in records for symbol in record.symbols}
    uncovered = [symbol for symbol in config.symbols if symbol not in covered]
    for symbol in uncovered:
        if symbol not in missing:
            missing.append(symbol)
    if not records:
        return [], Coverage(
            category="option_chain",
            status="missing",
            detail=f"Tradier chains unavailable. missing={missing or list(config.symbols)}",
        )
    status: CoverageStatus = "available"
    if missing:
        status = "partial"
    elif dated_contracts and stale_contracts == dated_contracts:
        status = "delayed"
    return records, Coverage(
        category="option_chain",
        status=status,
        detail=(
            f"{len(records)} Tradier chain snapshots (max {CHAIN_EXPIRATION_LIMIT} expirations). "
            f"per_symbol_missing={missing or 'none'}. "
            f"provider_quote_timestamps={dated_contracts} stale={stale_contracts}. "
            "available only when every configured underlying has at least one chain. "
            "open_interest is the provider prior-session field, not today's opening OI. "
            "Greeks are copied only when present; none are invented."
        ),
    )


def collect_history(
    *,
    config: Config,
    session: date,
    tradier: ReadFeed,
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    prior = prior_open_session(tradier, session)
    if prior is None:
        return [], Coverage(
            category="history",
            status="missing",
            detail="No prior open session found on Tradier calendar",
        )
    start = session - timedelta(days=HISTORY_LOOKBACK_CALENDAR_DAYS)
    records: list[Evidence] = []
    missing: list[str] = []
    received = clock()
    for symbol in [*config.symbols, *config.context_symbols]:
        body = tradier.get(
            "/markets/history",
            {
                "symbol": symbol,
                "interval": "daily",
                "start": start.isoformat(),
                "end": prior.isoformat(),
            },
        )
        received = clock()
        days = [
            row
            for row in _history_days(body)
            if str(row.get("date") or "") < session.isoformat()
            and str(row.get("date") or "") <= prior.isoformat()
        ]
        if not days:
            missing.append(symbol)
            continue
        closes = [float(row["close"]) for row in days if row.get("close") not in (None, "")]
        volumes = [int(row["volume"]) for row in days if row.get("volume") not in (None, "")]
        last = days[-1]
        records.append(
            Evidence(
                evidence_id=f"history:{symbol}",
                category="history",
                symbols=[symbol],
                source="tradier_production",
                source_uri=SOURCE_TRADIER_HISTORY,
                    as_of=datetime.combine(prior, dt_time(16, 0), NY).astimezone(UTC),
                received_at=received,
                summary=_summary(
                    f"{symbol} prior session {last.get('date')} close={last.get('close')} "
                    f"volume={last.get('volume')}"
                ),
                payload={
                    "prior_session": prior.isoformat(),
                    "excluded_on_or_after": session.isoformat(),
                    "prior_close": last.get("close"),
                    "prior_volume": last.get("volume"),
                    "realized_vol_daily_log_ann": _realized_vol(closes),
                    "realized_vol_label": "sample_stdev_log_return_from_prior_daily_closes",
                    "volume_mean": (sum(volumes) / len(volumes)) if volumes else None,
                    "volume_mean_label": "daily_volume_proxy_not_opening_print_volume",
                    "bars": days,
                },
            )
        )
    if not records:
        return [], Coverage(
            category="history",
            status="missing",
            detail=f"Tradier history empty before {session}. missing={missing}",
        )
    status: CoverageStatus = "partial" if missing else "available"
    return records, Coverage(
        category="history",
        status=status,
        detail=(
            f"Tradier daily bars through {prior}, excluding {session} and later. "
            f"missing={missing or 'none'}"
        ),
    )


def collect_portfolio(
    *,
    tradier: ReadFeed,
    account_id: str | None,
    clock: Clock,
) -> tuple[list[Evidence], Coverage]:
    if not account_id:
        return [], Coverage(
            category="portfolio",
            status="missing",
            detail=(
                "Schwab OAuth is not connected. Tradier account snapshot unused "
                "(no TRADIER_ACCOUNT_ID). Expanded mode fails closed without --allow-degraded."
            ),
        )
    alias = account_alias(account_id)
    reasons: list[str] = []
    bal: dict[str, Any] = {}
    pos_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    try:
        balances = tradier.get(f"/accounts/{account_id}/balances")
        received = clock()
        parsed = _drop_secret_keys(
            _mapping(_walk(balances, "balances", label="balances"), label="balances")
        )
        if not isinstance(parsed, dict):
            raise ValueError("unexpected Tradier balances object")
        bal = parsed
    except (ValueError, TypeError, AttributeError) as exc:
        reasons.append(f"balances unusable ({exc})")
        bal = {}
    try:
        positions = tradier.get(f"/accounts/{account_id}/positions")
        pos_rows = _dicts(
            _walk(positions, "positions", "position", label="positions"),
            label="positions",
        )
    except (ValueError, TypeError, AttributeError) as exc:
        reasons.append(f"positions unusable ({exc})")
    try:
        orders = tradier.get(f"/accounts/{account_id}/orders")
        order_rows = _dicts(_walk(orders, "orders", "order", label="orders"), label="orders")
    except (ValueError, TypeError, AttributeError) as exc:
        reasons.append(f"orders unusable ({exc})")
    received = clock()
    if reasons:
        return [], Coverage(
            category="portfolio",
            status="missing",
            detail=(
                "Tradier portfolio fail-closed: "
                + "; ".join(reasons)
                + ". Working orders not assumed empty."
            ),
        )
    cash = _known_amount(bal.get("total_cash"), bal.get("cash"))
    buying_power = _known_amount(
        _nested_field(bal, "margin", "option_buying_power"),
        _nested_field(bal, "pdt", "option_buying_power"),
        bal.get("option_buying_power"),
    )
    if cash is None or buying_power is None:
        return [], Coverage(
            category="portfolio",
            status="missing",
            detail=(
                "Tradier portfolio snapshot missing known cash and/or option buying power. "
                "Empty or unknown capital fields are not coverage available."
            ),
        )
    working = []
    for row in order_rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").lower()
        if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
            continue
        working.append(
            _drop_secret_keys(
                {
                    "symbol": row.get("option_symbol") or row.get("symbol"),
                    "side": row.get("side"),
                    "quantity": row.get("quantity"),
                    "status": row.get("status"),
                    "type": row.get("type"),
                }
            )
        )
    held = [
        _drop_secret_keys(
            {
                "symbol": row.get("option_symbol") or row.get("symbol"),
                "quantity": row.get("quantity"),
                "cost_basis": row.get("cost_basis"),
                "date_acquired": row.get("date_acquired"),
            }
        )
        for row in pos_rows
        if isinstance(row, dict)
    ]
    record = Evidence(
        evidence_id=f"portfolio:{alias}",
        category="portfolio",
        symbols=sorted(
            {
                str(item.get("symbol"))
                for item in [*held, *working]
                if isinstance(item, dict) and item.get("symbol")
            }
        ),
        source="tradier_production_interim_portfolio",
        source_uri=SOURCE_TRADIER_BALANCES,
        as_of=received,
        received_at=received,
        summary=_summary(
            f"Tradier-backed interim portfolio {alias}: "
            f"{len(held)} positions, {len(working)} working orders"
        ),
        payload={
            "account_alias": alias,
            "portfolio_source": "tradier_read_only_until_schwab_oauth",
            "cash": cash,
            "equity": _known_amount(bal.get("total_equity"), bal.get("equity")),
            "option_buying_power": buying_power,
            "account_type": bal.get("account_type"),
            "pending_orders_count": bal.get("pending_orders_count"),
            "positions": held,
            "working_orders": working,
            "related_uris": [SOURCE_TRADIER_POSITIONS, SOURCE_TRADIER_ORDERS],
        },
    )
    return [record], Coverage(
        category="portfolio",
        status="available",
        detail=(
            "Read-only Tradier balances/positions/orders. Account numbers replaced with "
            f"opaque alias {alias}. Schwab is not the portfolio source."
            + (
                " Empty or null orders payload treated as no working orders."
                if not working
                else ""
            )
        ),
    )


def _uw_data_rows(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or "data" not in body:
        raise ValueError("missing UW data array")
    return as_rows(body.get("data"))


def _pick_fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: row[key] for key in keys if key in row}


def _row_ticker(row: dict[str, Any]) -> str:
    for key in ("ticker_symbol", "ticker", "underlying_symbol", "symbol"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return ""


def _archive_uw(directory: Path | None, name: str, received: datetime, uri: str, body: Any) -> None:
    if directory is None:
        return
    archived = body if isinstance(body, dict) else {"unexpected": True}
    _write_raw(
        directory,
        name,
        {
            "received_at": received.isoformat(),
            "source_uri": uri,
            "body": _drop_secret_keys(archived),
        },
    )


def collect_dark_pool(
    *,
    config: Config,
    uw: ReadFeed,
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    """Per-symbol UW dark pool plus a small market-wide recent summary."""
    records: list[Evidence] = []
    missing: list[str] = []
    for symbol in config.symbols:
        try:
            body = uw.get(f"/api/darkpool/{symbol}")
            received = clock()
            rows = _uw_data_rows(body)[:DARKPOOL_ROWS_PER_SYMBOL]
        except ValueError:
            missing.append(symbol)
            continue
        _archive_uw(
            directory,
            f"uw-darkpool-{symbol}.json",
            received,
            f"{SOURCE_UW_DARKPOOL}/{symbol}",
            body,
        )
        prints = [_pick_fields(row, DARKPOOL_FIELDS) for row in rows]
        records.append(
            Evidence(
                evidence_id=f"darkpool:{symbol}",
                category="dark_pool",
                symbols=[symbol],
                source="unusual_whales",
                source_uri=f"{SOURCE_UW_DARKPOOL}/{symbol}",
                as_of=received,
                received_at=received,
                summary=_summary(
                    f"{symbol} UW dark pool: {len(prints)} prints "
                    f"(cap {DARKPOOL_ROWS_PER_SYMBOL})"
                ),
                payload={
                    "print_count": len(prints),
                    "row_cap": DARKPOOL_ROWS_PER_SYMBOL,
                    "prints": prints,
                    "note": "Provider prints copied as-is; no invented prices or levels.",
                },
            )
        )
    recent_note = "market-wide recent not fetched"
    try:
        recent_body = uw.get("/api/darkpool/recent", {"limit": DARKPOOL_RECENT_ROWS})
        received = clock()
        recent_rows = _uw_data_rows(recent_body)[:DARKPOOL_RECENT_ROWS]
        _archive_uw(
            directory,
            "uw-darkpool-recent.json",
            received,
            f"{SOURCE_UW_DARKPOOL}/recent",
            recent_body,
        )
        universe = set(config.symbols)
        hits = [
            _pick_fields(row, DARKPOOL_FIELDS)
            for row in recent_rows
            if _row_ticker(row) in universe
        ]
        others = sum(1 for row in recent_rows if _row_ticker(row) not in universe)
        records.append(
            Evidence(
                evidence_id="darkpool:recent",
                category="dark_pool",
                symbols=sorted({_row_ticker(row) for row in hits if _row_ticker(row)}),
                source="unusual_whales",
                source_uri=f"{SOURCE_UW_DARKPOOL}/recent",
                as_of=received,
                received_at=received,
                summary=_summary(
                    f"UW dark pool recent: {len(hits)} universe prints, "
                    f"{others} other tickers counted"
                ),
                payload={
                    "universe_prints": hits,
                    "other_print_count": others,
                    "row_cap": DARKPOOL_RECENT_ROWS,
                    "note": "Non-universe rows counted only; prices not copied.",
                },
            )
        )
        recent_note = f"recent universe={len(hits)} other={others}"
    except ValueError as exc:
        recent_note = f"market-wide recent failed ({exc})"
    if not records:
        return [], Coverage(
            category="dark_pool",
            status="missing",
            detail=(
                "UW dark pool unavailable. "
                f"missing={missing or list(config.symbols)} {recent_note}"
            ),
        )
    status: CoverageStatus = "partial" if missing else "available"
    return records, Coverage(
        category="dark_pool",
        status=status,
        detail=(
            f"UW GET /api/darkpool/{{ticker}} for {len(config.symbols) - len(missing)}/"
            f"{len(config.symbols)} names (cap {DARKPOOL_ROWS_PER_SYMBOL}/symbol). "
            f"missing={missing or 'none'}. {recent_note}. Empty prints are available, not missing."
        ),
    )


def collect_option_screener(
    *,
    config: Config,
    uw: ReadFeed,
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    """Hottest-contract slice filtered to the frozen 10 names. Keep payload small."""
    try:
        body = uw.get("/api/screener/option-contracts", {"limit": SCREENER_FETCH_LIMIT})
        received = clock()
    except ValueError as exc:
        return [], Coverage(
            category="option_screener",
            status="missing",
            detail=f"UW option screener not entitled or failed ({exc})",
        )
    _archive_uw(directory, "uw-option-screener.json", received, SOURCE_UW_SCREENER, body)
    try:
        rows = _uw_data_rows(body)
    except ValueError:
        return [], Coverage(
            category="option_screener",
            status="missing",
            detail="UW option screener returned unexpected payload (no data array)",
        )
    universe = set(config.symbols)
    by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in config.symbols}
    skipped = 0
    other = 0
    for row in rows:
        ticker = _row_ticker(row)
        if ticker not in universe:
            other += 1
            continue
        if len(by_symbol[ticker]) >= SCREENER_PER_SYMBOL:
            skipped += 1
            continue
        by_symbol[ticker].append(_pick_fields(row, SCREENER_FIELDS))
    contracts = [item for rows_for in by_symbol.values() for item in rows_for]
    record = Evidence(
        evidence_id="screener:uw-option-contracts",
        category="option_screener",
        symbols=sorted({_row_ticker(item) for item in contracts if _row_ticker(item)}),
        source="unusual_whales",
        source_uri=SOURCE_UW_SCREENER,
        as_of=received,
        received_at=received,
        summary=_summary(
            f"UW option screener: {len(contracts)} universe contracts "
            f"(fetch {SCREENER_FETCH_LIMIT}, cap {SCREENER_PER_SYMBOL}/name)"
        ),
        payload={
            "contract_count": len(contracts),
            "per_symbol": {symbol: by_symbol[symbol] for symbol in config.symbols},
            "other_ticker_count": other,
            "skipped_over_cap": skipped,
            "note": (
                "Market-wide screener filtered to packet.config.symbols. "
                "Provider fields copied as-is; no invented prices or Greeks."
            ),
        },
    )
    return [record], Coverage(
        category="option_screener",
        status="available",
        detail=(
            f"UW GET /api/screener/option-contracts limit={SCREENER_FETCH_LIMIT}: "
            f"{len(contracts)} universe contracts, other_tickers={other}. "
            "Empty universe slice is available, not missing."
        ),
    )


def collect_market_tide(
    *,
    uw: ReadFeed,
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    """Session-level UW market tide once. Not per-symbol."""
    try:
        body = uw.get("/api/market/market-tide")
        received = clock()
    except ValueError as exc:
        return [], Coverage(
            category="market_tide",
            status="missing",
            detail=f"UW market tide not entitled or failed ({exc})",
        )
    _archive_uw(directory, "uw-market-tide.json", received, SOURCE_UW_MARKET_TIDE, body)
    try:
        rows = _uw_data_rows(body)
    except ValueError:
        return [], Coverage(
            category="market_tide",
            status="missing",
            detail="UW market tide returned unexpected payload (no data array)",
        )
    ticks = [_pick_fields(row, TIDE_FIELDS) for row in rows[-TIDE_ROW_CAP:]]
    record = Evidence(
        evidence_id="macro:uw-market-tide",
        category="market_tide",
        symbols=[],
        source="unusual_whales",
        source_uri=SOURCE_UW_MARKET_TIDE,
        as_of=received,
        received_at=received,
        summary=_summary(f"UW market tide: {len(ticks)} recent ticks (cap {TIDE_ROW_CAP})"),
        payload={
            "tick_count": len(ticks),
            "row_cap": TIDE_ROW_CAP,
            "ticks": ticks,
            "note": (
                "Session-level tape, not per-symbol. Provider net premium copied as-is; "
                "no invented sentiment score."
            ),
        },
    )
    return [record], Coverage(
        category="market_tide",
        status="available",
        detail=(
            f"UW GET /api/market/market-tide once: {len(ticks)} ticks archived "
            f"(cap {TIDE_ROW_CAP}). Empty data is available, not missing."
        ),
    )


def collect_political(
    *,
    config: Config,
    uw: ReadFeed,
    clock: Clock,
    directory: Path | None = None,
) -> tuple[list[Evidence], Coverage]:
    """Congress trades touching the 10 names; insider only if the official feed is cheap."""
    universe = set(config.symbols)
    records: list[Evidence] = []
    notes: list[str] = []
    try:
        body = uw.get("/api/congress/recent-trades", {"limit": POLITICAL_FETCH_LIMIT})
        received = clock()
        _archive_uw(directory, "uw-congress-recent.json", received, SOURCE_UW_CONGRESS, body)
        rows = [
            _pick_fields(row, CONGRESS_FIELDS)
            for row in _uw_data_rows(body)
            if _row_ticker(row) in universe
        ]
        records.append(
            Evidence(
                evidence_id="political:uw-congress",
                category="political",
                symbols=sorted({_row_ticker(row) for row in rows if _row_ticker(row)}),
                source="unusual_whales",
                source_uri=SOURCE_UW_CONGRESS,
                as_of=received,
                received_at=received,
                summary=_summary(
                    f"UW congress trades touching universe: {len(rows)} rows"
                ),
                payload={
                    "row_count": len(rows),
                    "trades": rows,
                    "note": (
                        "Market-wide /api/congress/recent-trades filtered to "
                        "packet.config.symbols. Amount ranges are provider text, not prices."
                    ),
                },
            )
        )
        notes.append(f"congress universe rows={len(rows)}")
    except ValueError as exc:
        notes.append(f"congress failed ({exc})")
    try:
        insider_body = uw.get("/api/insider/transactions", {"limit": INSIDER_FETCH_LIMIT})
        received = clock()
        _archive_uw(
            directory,
            "uw-insider-transactions.json",
            received,
            SOURCE_UW_INSIDER,
            insider_body,
        )
        insider_rows = [
            _pick_fields(row, INSIDER_FIELDS)
            for row in _uw_data_rows(insider_body)
            if _row_ticker(row) in universe
        ]
        if insider_rows:
            records.append(
                Evidence(
                    evidence_id="political:uw-insider",
                    category="political",
                    symbols=sorted({_row_ticker(row) for row in insider_rows if _row_ticker(row)}),
                    source="unusual_whales",
                    source_uri=SOURCE_UW_INSIDER,
                    as_of=received,
                    received_at=received,
                    summary=_summary(
                        f"UW insider transactions touching universe: {len(insider_rows)} rows"
                    ),
                    payload={
                        "row_count": len(insider_rows),
                        "transactions": insider_rows,
                        "note": "Official /api/insider/transactions; provider fields only.",
                    },
                )
            )
            notes.append(f"insider universe rows={len(insider_rows)}")
        else:
            notes.append("insider returned 0 universe rows (skipped quietly)")
    except ValueError as exc:
        notes.append(f"insider unused ({exc})")
    if not records:
        return [], Coverage(
            category="political",
            status="missing",
            detail="UW congress/insider unused or failed. " + "; ".join(notes),
        )
    return records, Coverage(
        category="political",
        status="available",
        detail=(
            "UW congress/insider filtered to the 10 configured symbols. "
            + "; ".join(notes)
            + ". Zero universe hits stay available, not fabricated."
        ),
    )


def collect_depth() -> tuple[list[Evidence], Coverage]:
    return [], Coverage(
        category="depth",
        status="missing",
        detail="No entitled exchange-depth API is wired. NBBO is not depth. Optional category.",
    )


def collect_context(
    *,
    config: Config,
    session: date,
    uw: ReadFeed,
    tradier: ReadFeed,
    finnhub: FinnhubRest | None = None,
    account_id: str | None = None,
    news_events: list[Event] | None = None,
    flow_events: list[Event] | None = None,
    packet: Packet | None = None,
    clock: Clock | None = None,
    frozen_at: datetime | None = None,
    directory: Path | None = None,
) -> Context:
    tick = _clock(clock)
    if packet is not None:
        news_events = [event for event in packet.events if event.kind == "news"]
        flow_events = [event for event in packet.events if event.kind == "option_trade"]
        session = packet.session
        config = packet.config
    news_events = news_events or []
    flow_events = flow_events or []
    records: list[Evidence] = []
    coverage: list[Coverage] = []
    collectors: list[tuple[Category, Any]] = [
        (
            "company_news",
            lambda: collect_company_news(
                config=config, uw=uw, news_events=news_events, clock=tick
            ),
        ),
        (
            "world_news",
            lambda: collect_world_news(finnhub=finnhub, frozen_at=frozen_at or tick(), clock=tick),
        ),
        ("macro", lambda: collect_macro(config=config, tradier=tradier, clock=tick)),
        (
            "calendar",
            lambda: collect_calendar(
                config=config,
                session=session,
                tradier=tradier,
                uw=uw,
                flow_events=flow_events,
                clock=tick,
                directory=directory,
            ),
        ),
        (
            "option_chain",
            lambda: collect_option_chain(
                config=config, session=session, tradier=tradier, clock=tick
            ),
        ),
        (
            "history",
            lambda: collect_history(config=config, session=session, tradier=tradier, clock=tick),
        ),
        (
            "portfolio",
            lambda: collect_portfolio(tradier=tradier, account_id=account_id, clock=tick),
        ),
        ("depth", collect_depth),
        (
            "dark_pool",
            lambda: collect_dark_pool(
                config=config, uw=uw, clock=tick, directory=directory
            ),
        ),
        (
            "option_screener",
            lambda: collect_option_screener(
                config=config, uw=uw, clock=tick, directory=directory
            ),
        ),
        (
            "market_tide",
            lambda: collect_market_tide(uw=uw, clock=tick, directory=directory),
        ),
        (
            "political",
            lambda: collect_political(
                config=config, uw=uw, clock=tick, directory=directory
            ),
        ),
    ]
    for category, collector in collectors:
        try:
            collected, entry = collector()
        except (
            ValueError,
            TypeError,
            AttributeError,
            TimeoutError,
            OSError,
            httpx.HTTPError,
        ) as exc:
            collected, entry = [], Coverage(
                category=category,
                status="missing",
                detail=f"collector fail-closed ({type(exc).__name__}: {exc})",
            )
        records.extend(collected)
        coverage.append(entry)
    declared = {entry.category for entry in coverage}
    if declared != CATEGORIES:
        raise ValueError("collector omitted a context category")
    latest = max((record.received_at for record in records), default=tick())
    frozen = frozen_at or latest
    return Context(session=session, frozen_at=frozen, records=records, coverage=coverage)


def write_expanded_context(
    *,
    config: Config,
    session: date,
    directory: Path,
    uw: ReadFeed,
    tradier: ReadFeed,
    news_events: list[Event],
    flow_events: list[Event],
    packet: Packet | None = None,
    finnhub: FinnhubRest | None = None,
    account_id: str | None = None,
    clock: Clock | None = None,
    target: Path | None = None,
) -> Context:
    context = collect_context(
        config=config,
        session=session,
        uw=uw,
        tradier=tradier,
        finnhub=finnhub if finnhub is not None else optional_finnhub(),
        account_id=account_id if account_id is not None else optional_account_id(),
        news_events=news_events,
        flow_events=flow_events,
        packet=packet,
        clock=clock,
        directory=directory,
    )
    _write_raw(
        directory,
        "context-coverage.json",
        {
            "received_at": (clock or now_utc)().isoformat(),
            "coverage": [item.model_dump() for item in context.coverage],
        },
    )
    dest = target or (directory / "context.json")
    if not dest.exists():
        write_once(dest, context.model_dump(mode="json"))
    return context
