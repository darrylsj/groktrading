"""Time helpers. Flatten/cash-up is 12:30 America/Los_Angeles. No overnight holds."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")
CASH_UP_PT = time(12, 30)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_pt(value: datetime) -> datetime:
    return as_utc(value).astimezone(PT)


def session_date_pt(now: datetime) -> date:
    return as_pt(now).date()


def cash_up_deadline_pt(now: datetime) -> datetime:
    day = session_date_pt(now)
    return datetime.combine(day, CASH_UP_PT, tzinfo=PT)


def past_cash_up(now: datetime) -> bool:
    return as_pt(now) >= cash_up_deadline_pt(now)


def quote_age_seconds(quote_ts: datetime, now: datetime) -> float:
    return (as_utc(now) - as_utc(quote_ts)).total_seconds()


def is_stale(quote_ts: datetime, now: datetime, ttl_seconds: float) -> bool:
    return quote_age_seconds(quote_ts, now) > ttl_seconds


def next_session_open_hint(now: datetime) -> datetime:
    """Next calendar 06:30 PT after cash-up — hint only, not a trading clock."""
    deadline = cash_up_deadline_pt(now)
    if as_pt(now) < deadline:
        return deadline
    nxt = session_date_pt(now) + timedelta(days=1)
    return datetime.combine(nxt, time(6, 30), tzinfo=PT)
