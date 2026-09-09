#!/usr/bin/env python3
"""Shared host HTTP for Helsinki companions.

Authorization Bearer is **runtime env only** (``UW_API_KEY`` / ``UW_API_TOKEN``).
Never log headers or tokens. Never places orders. Grok Bot decides.

This module is a transport. Package helpers (``UnusualWhalesClient``) own
documented paths and freshness. CI / ``--help`` must not require secrets
or open a live socket.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from groktrading.feeds.unusual_whales import DEFAULT_UW_BASE_URL, UnusualWhalesClient
from groktrading.timeutil import UTC

NEVER_ORDERS_NOTE = (
    "Helsinki host HTTP transport. Authorization Bearer is runtime env only. "
    "Never places orders. WebSocket never places orders. Grok Bot decides."
)

DEFAULT_STATE_DIR = Path("/var/lib/trading-desk")
DEFAULT_LEDGER_NAME = "ledger/uw_flow.sqlite"
DEFAULT_TIMEOUT_SEC = 15.0
_TOKEN_KEYS = ("UW_API_KEY", "UW_API_TOKEN")


def env_map(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if env is None else env


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    source = env_map(env)
    raw = str(source.get("STATE_DIR", "")).strip()
    return Path(raw) if raw else DEFAULT_STATE_DIR


def ledger_path(env: Mapping[str, str] | None = None) -> Path:
    source = env_map(env)
    raw = str(source.get("FLOW_LEDGER_PATH", "")).strip()
    if raw:
        return Path(raw)
    return state_dir(source) / DEFAULT_LEDGER_NAME


def uw_token(env: Mapping[str, str] | None = None) -> str:
    """Token from runtime env. Empty if unset — callers fail closed."""
    source = env_map(env)
    for key in _TOKEN_KEYS:
        raw = str(source.get(key, "")).strip()
        if raw:
            return raw
    return ""


def authorization_headers(token: str) -> dict[str, str]:
    """Build Authorization Bearer at request time. Never log this mapping."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def uw_base_url(env: Mapping[str, str] | None = None) -> str:
    source = env_map(env)
    raw = str(source.get("UW_BASE_URL") or source.get("UW_API_BASE") or "").strip()
    return raw or DEFAULT_UW_BASE_URL


class HelsinkiHttp:
    """httpx JSON GET. Forwards caller headers (Bearer is runtime env / client)."""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_SEC) -> None:
        self.timeout = timeout

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        hdrs = dict(headers or {})
        if "Authorization" not in hdrs:
            token = uw_token()
            if token:
                hdrs.update(authorization_headers(token))
        try:
            response = httpx.get(url, headers=hdrs, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise TimeoutError("helsinki_http_timeout") from exc
        try:
            body: Any = response.json()
        except ValueError:
            body = {}
        return response.status_code, body


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def require_uw_token(env: Mapping[str, str] | None = None) -> str:
    token = uw_token(env)
    if not token:
        raise SystemExit("UW_API_KEY or UW_API_TOKEN is required in the environment")
    return token


def make_uw_client(env: Mapping[str, str] | None = None) -> UnusualWhalesClient:
    """Live UW client. Token is read at call time; never embedded."""
    source = env_map(env)
    return UnusualWhalesClient(
        http=HelsinkiHttp(),
        clock=UtcClock(),
        token=require_uw_token(source),
        base_url=uw_base_url(source),
    )


if __name__ == "__main__":
    print(NEVER_ORDERS_NOTE)
