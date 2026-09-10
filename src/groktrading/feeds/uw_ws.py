"""UW WebSocket probe stub — fail-closed if unset; do not invent a protocol.

Unusual Whales documents a socket at ``wss://api.unusualwhales.com/socket``
and a live channel catalog. Channel names and subscribe frames **change**.
This helper does not open a socket and does not invent subscribe JSON.

Prove ``UW_WS_URL`` (operator, if the plan supports it):

1. Set ``UW_WS_URL`` in the host env (0600). Never commit the tokenized URL.
2. Fetch current channel docs:
   ``https://api.unusualwhales.com/docs/operations/PublicApi.SocketController.channels``
3. Confirm the plan entitles the socket (skill:
   ``https://unusualwhales.com/skills/websocket.md``).
4. Wire a host-owned consumer (not this package) using the live docs.

If ``UW_WS_URL`` is unset or not ``wss://``, this probe fail-closes.
CI never connects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from groktrading.feeds.unusual_whales import DOCS_WS_CHANNELS, DOCS_WS_SKILL

UW_WS_URL_ENV = "UW_WS_URL"
DOCUMENTED_UW_WS_HINT = "wss://api.unusualwhales.com/socket"
REASON_UNSET = "uw_ws_url_unset"
REASON_INVALID = "uw_ws_url_invalid"
NEVER_ORDERS_NOTE = (
    "UW_WS probe stub. Fail-closed if UW_WS_URL is unset. "
    "Do not invent a subscribe protocol. Never places orders. "
    "This helper does not open a socket."
)


@dataclass(frozen=True)
class UwWsProbe:
    ok: bool
    configured: bool
    reason: str | None
    public_url: str | None
    connected: bool = False
    live_socket: bool = False
    places_orders: bool = False
    channels_docs: str = DOCS_WS_CHANNELS
    skill_docs: str = DOCS_WS_SKILL
    note: str = NEVER_ORDERS_NOTE


def public_probe_url(raw: str) -> str | None:
    """Publish only validated ``wss`` scheme/host/path.

    Query, userinfo, and fragment (including ``access_token``) are discarded.
    """
    text = str(raw).strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme.lower() != "wss":
        return None
    host = parts.hostname
    if not host:
        return None
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path or ""
    return urlunsplit(("wss", host, path, "", ""))


def probe_uw_ws(env: Mapping[str, str] | None = None) -> UwWsProbe:
    """Inspect env only. Never connects. Never logs an unredacted URL."""
    source = {} if env is None else env
    raw = str(source.get(UW_WS_URL_ENV) or "").strip()
    if not raw:
        return UwWsProbe(
            ok=False,
            configured=False,
            reason=REASON_UNSET,
            public_url=None,
        )
    public = public_probe_url(raw)
    if public is None:
        return UwWsProbe(
            ok=False,
            configured=True,
            reason=REASON_INVALID,
            public_url=None,
        )
    return UwWsProbe(
        ok=True,
        configured=True,
        reason=None,
        public_url=public,
        note=(
            f"{NEVER_ORDERS_NOTE} Documented hint: {DOCUMENTED_UW_WS_HINT}. "
            f"Fetch {DOCS_WS_CHANNELS} before any host subscribe."
        ),
    )


def probe_document(probe: UwWsProbe) -> dict[str, Any]:
    return {
        "source": "uw_ws_probe",
        "ok": probe.ok,
        "configured": probe.configured,
        "reason": probe.reason,
        "public_url": probe.public_url,
        "connected": probe.connected,
        "live_socket": probe.live_socket,
        "places_orders": probe.places_orders,
        "channels_docs": probe.channels_docs,
        "skill_docs": probe.skill_docs,
        "documented_hint": DOCUMENTED_UW_WS_HINT,
        "note": probe.note,
        "invents_protocol": False,
    }
