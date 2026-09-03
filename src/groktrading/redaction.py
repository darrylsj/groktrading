"""Redact credentials and secret-shaped values from logs and on-disk JSON."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|bearer|"
    r"webhook[_-]?secret|hmac|private[_-]?key|access[_-]?key)$",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_QUERY_TOKEN_RE = re.compile(r"([?&](?:token|api[_-]?key|secret)=)[^&\s]+", re.IGNORECASE)


def redact_string(value: str) -> str:
    value = _BEARER_RE.sub(f"Bearer {REDACTED}", value)
    return _QUERY_TOKEN_RE.sub(rf"\1{REDACTED}", value)


def _key_is_secret(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key.replace("-", "_")))


def redact_mapping(data: Any) -> Any:
    """Return a deep-copied structure with secret fields replaced."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if _key_is_secret(str(key)):
                out[key] = REDACTED
            else:
                out[key] = redact_mapping(value)
        return out
    if isinstance(data, list):
        return [redact_mapping(item) for item in data]
    if isinstance(data, str):
        return redact_string(data)
    return data
