from enum import StrEnum


class OperatingMode(StrEnum):
    """Runtime mode. Live is never the default and requires explicit enablement."""

    SIGNALS_ONLY = "signals_only"
    PAPER = "paper"
    LIVE = "live"


DEFAULT_MODE = OperatingMode.SIGNALS_ONLY
