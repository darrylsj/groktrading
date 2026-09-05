"""Time helpers. 12:30 America/Los_Angeles is a new-entry cutoff only.

Overnight long options are allowed. Fail-closed after the cutoff means no new
risk; existing positions continue to be monitored. This is not a flatten clock.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")
CASH_UP_PT = time(12, 30)
ENTRY_CUTOFF_PT = CASH_UP_PT
RTH_OPEN_HINT_PT = time(6, 30)
RTH_CLOSE_HINT_PT = time(13, 0)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_pt(value: datetime) -> datetime:
    return as_utc(value).astimezone(PT)


def session_date_pt(now: datetime) -> date:
    return as_pt(now).date()


def cash_up_deadline_pt(now: datetime) -> datetime:
    """12:30 PT deadline. Alias kept; prefer entry_cutoff_deadline_pt."""
    return entry_cutoff_deadline_pt(now)


def entry_cutoff_deadline_pt(now: datetime) -> datetime:
    day = session_date_pt(now)
    return datetime.combine(day, ENTRY_CUTOFF_PT, tzinfo=PT)


def past_cash_up(now: datetime) -> bool:
    """True at/after 12:30 PT. Alias kept; prefer past_entry_cutoff."""
    return past_entry_cutoff(now)


def past_entry_cutoff(now: datetime) -> bool:
    return as_pt(now) >= entry_cutoff_deadline_pt(now)


def quote_age_seconds(quote_ts: datetime, now: datetime) -> float:
    return (as_utc(now) - as_utc(quote_ts)).total_seconds()


def is_stale(quote_ts: datetime, now: datetime, ttl_seconds: float) -> bool:
    return quote_age_seconds(quote_ts, now) > ttl_seconds


def is_future_ts(ts: datetime, now: datetime, slack_seconds: float = 1.0) -> bool:
    return quote_age_seconds(ts, now) < -slack_seconds


def next_session_open_hint(now: datetime) -> datetime:
    """Next calendar 06:30 PT after the entry cutoff — hint only, not a trading clock."""
    deadline = entry_cutoff_deadline_pt(now)
    if as_pt(now) < deadline:
        return deadline
    nxt = session_date_pt(now) + timedelta(days=1)
    return datetime.combine(nxt, RTH_OPEN_HINT_PT, tzinfo=PT)


def market_session_kind(now: datetime, clock_state: str | None = None) -> str:
    """Coarse session kind for webhook coalesce. Not a broker clock."""
    pt = as_pt(now)
    if pt.weekday() >= 5:
        return "weekend"
    state = (clock_state or "").lower()
    if state == "open":
        return "rth"
    if state in {"closed", "pre", "post"}:
        return "after_hours"
    t = pt.time()
    if RTH_OPEN_HINT_PT <= t < RTH_CLOSE_HINT_PT:
        return "rth"
    return "after_hours"


def should_coalesce_digest(now: datetime, clock_state: str | None = None) -> bool:
    """AH/weekend same-digest webhooks must not fan out."""
    return market_session_kind(now, clock_state) != "rth"
