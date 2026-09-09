"""Generic Unusual Whales client.

Official product docs: https://api.unusualwhales.com/
Agent skill / endpoint index: https://unusualwhales.com/skill.md
Default base URL is configurable. This module does not invent extra paths;
callers pass documented relative paths from the official docs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from groktrading.errors import StaleDataError, TimeoutFailClosedError
from groktrading.timeutil import is_stale

DEFAULT_UW_BASE_URL = "https://api.unusualwhales.com"
DOCS_HOME = "https://api.unusualwhales.com/"
DOCS_SKILL = "https://unusualwhales.com/skill.md"
DOCS_WS_SKILL = "https://unusualwhales.com/skills/websocket.md"
DOCS_WS_CHANNELS = (
    "https://api.unusualwhales.com/docs/operations/PublicApi.SocketController.channels"
)

# Documented GET paths only (unusualwhales.com/skill.md). No unofficial aliases.
UW_OPTION_TRADES_PATH = "/api/option-trades"
UW_FLOW_ALERTS_PATH = "/api/option-trades/flow-alerts"
UW_MARKET_TIDE_PATH = "/api/market/market-tide"
UW_SCREENER_PATH = "/api/screener/option-contracts"
UW_NET_PREM_TICKS_PREFIX = "/api/stock/"
UW_NET_PREM_TICKS_SUFFIX = "/net-prem-ticks"

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def sanitize_ticker(value: object) -> str | None:
    """Uppercase ticker or None. Rejects path-injection junk."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or not _TICKER_RE.fullmatch(text):
        return None
    return text


def net_prem_ticks_path(ticker: str) -> str:
    """Documented ``/api/stock/{ticker}/net-prem-ticks``. Ticker must sanitize."""
    clean = sanitize_ticker(ticker)
    if clean is None:
        raise ValueError("invalid_ticker_for_net_prem")
    return f"{UW_NET_PREM_TICKS_PREFIX}{clean}{UW_NET_PREM_TICKS_SUFFIX}"


def uw_data_rows(body: Any) -> list[dict[str, Any]]:
    """Unwrap UW ``{data: [...]}`` or a bare list. Junk → empty (no invent)."""
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            return [data]
    return []


class HttpJson(Protocol):
    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass
class UnusualWhalesClient:
    """Dependency-injected UW HTTP client. Timeout and stale data fail closed."""

    http: HttpJson
    clock: Clock
    token: str
    base_url: str = DEFAULT_UW_BASE_URL
    freshness_ttl_seconds: float = 30.0
    last_success_ts: datetime | None = None

    def headers(self) -> dict[str, str]:
        # Token is used at request time only; callers must not log this mapping.
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def get_documented_path(
        self,
        relative_path: str,
        params: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        """GET a caller-supplied path under the configured base URL.

        Pass only paths published in official UW docs (for example
        ``/api/option-trades``). Do not add unofficial aliases here.
        Optional ``params`` are encoded as a query string (documented keys only).
        """
        if not relative_path.startswith("/"):
            raise ValueError("relative_path must start with /")
        url = f"{self.base_url.rstrip('/')}{relative_path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        try:
            status, body = self.http.get_json(url, headers=self.headers())
        except TimeoutError as exc:
            raise TimeoutFailClosedError("unusual_whales_timeout") from exc
        if status >= 400:
            raise TimeoutFailClosedError(f"unusual_whales_http_{status}")
        self.last_success_ts = self.clock.now()
        return status, body

    def require_fresh(self) -> None:
        now = self.clock.now()
        if self.last_success_ts is None or is_stale(
            self.last_success_ts, now, self.freshness_ttl_seconds
        ):
            raise StaleDataError("unusual_whales_stale")
