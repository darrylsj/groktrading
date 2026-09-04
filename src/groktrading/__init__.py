"""GrokTrading reference package.

Default operating mode is signals-only. Paper requires an explicit mode.
Live order placement is never enabled by default and is not reachable from
WebSocket event handlers.
"""

from groktrading.modes import OperatingMode

__all__ = ["OperatingMode", "__version__"]
__version__ = "0.1.0"
