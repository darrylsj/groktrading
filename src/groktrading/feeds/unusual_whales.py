"""Generic Unusual Whales client.

Official product docs: https://api.unusualwhales.com/
Agent skill / endpoint index: https://unusualwhales.com/skill.md
Default base URL is configurable. This module does not invent extra paths;
callers pass documented relative paths from the official docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from groktrading.errors import StaleDataError, TimeoutFailClosedError
from groktrading.timeutil import is_stale

DEFAULT_UW_BASE_URL = "https://api.unusualwhales.com"
DOCS_HOME = "https://api.unusualwhales.com/"
DOCS_SKILL = "https://unusualwhales.com/skill.md"


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

    def get_documented_path(self, relative_path: str) -> tuple[int, Any]:
        """GET a caller-supplied path under the configured base URL.

        Pass only paths published in official UW docs (for example
        ``/api/option-trades``). Do not add unofficial aliases here.
        """
        if not relative_path.startswith("/"):
            raise ValueError("relative_path must start with /")
        url = f"{self.base_url.rstrip('/')}{relative_path}"
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
