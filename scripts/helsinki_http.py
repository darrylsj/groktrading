"""Shared urllib HttpJson for Helsinki companions.

Matches groktrading.feeds.unusual_whales.HttpJson:
  get_json(url, headers=None) -> (status, body)
Raises TimeoutError on timeouts (UW client maps to fail-closed).
Never logs tokens or Authorization headers.
Does not follow redirects (Authorization must not be re-sent).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse 3xx so Authorization is never forwarded to a new origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _urlopen(req: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


class UrllibHttp:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = float(timeout)

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        try:
            with _urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = int(getattr(resp, "status", 200) or 200)
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            status = int(exc.code)
        except TimeoutError:
            raise
        except socket.timeout as exc:
            raise TimeoutError("urllib_timeout") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("urllib_timeout") from exc
            # Some platforms wrap timeout as OSError with errno
            if "timed out" in str(exc).lower() or "timeout" in str(reason).lower():
                raise TimeoutError("urllib_timeout") from exc
            raise
        try:
            body: Any = json.loads(raw.decode("utf-8", errors="replace") or "null")
        except Exception:
            body = {}
        return status, body
