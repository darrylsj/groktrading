"""Fail-closed errors. Timeouts and stale data never proceed as success."""


class FailClosedError(Exception):
    """Base for timeout, stale, or incomplete-data failures."""


class StaleDataError(FailClosedError):
    pass


class TimeoutFailClosedError(FailClosedError):
    pass


class WatchlistBoundError(FailClosedError):
    pass


class LiveGatingError(FailClosedError):
    """Raised when live placement is requested without an explicit live path."""


class SchwabAuthNotReady(FailClosedError):
    """Schwab OAuth credentials or token file are missing; no live Schwab calls."""
