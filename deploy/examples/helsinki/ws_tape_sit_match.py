"""Live Helsinki sit_match POST contract (optional rare alert — not hunt).

Not a port of /opt/trading-desk/ws_tape.py. Never places orders. No secrets.

Hunt is three planes (``docs/REALTIME_PLANES.md``): hot tape → thin
``shortlist.json`` → Continual15. ``sit_match`` POSTs are deprecated as
the hunt bus. Prefer ``SIT_MATCH_WEBHOOK=0``. ``MIN_INTERVAL`` is a
Cursor bandage, not trading latency.

Host tape must call ``prepare_sit_match_outbound`` immediately before HTTP
POST. This file is the in-repo SoT for the producer controls already
deployed on Helsinki:

- OCC-only debounce (not OCC|executed_at) so one name cannot firehose.
- ``SIT_MATCH_MIN_INTERVAL_SEC`` default **60** (15 outran Cursor ~22s wakes).
- Mute: ``SIT_MATCH_WEBHOOK=0`` and/or
  ``/opt/trading-desk/state/sit_match_webhook_muted`` →
  ``sit_match_webhook_muted``.
- Keep stale-at-POST: ``executed_at`` ≤60s, stamp ``emitted_at``,
  ``print_age_sec`` from executed_at age.

``install_helsinki.sh`` does not copy this over ``ws_tape.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from groktrading.sit_match import (
    DEFAULT_SIT_MATCH_MUTE_FILE,
    SitMatchEmitMemory,
    prepare_sit_match_outbound,
)

HOST_MUTE_FILE = Path(DEFAULT_SIT_MATCH_MUTE_FILE)
_MEMORY = SitMatchEmitMemory()


def maybe_post_sit_match(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    detected_at: object | None = None,
    enqueued_at: object | None = None,
    post: Any = None,
) -> object:
    """Return the prepare decision. Call ``post(prepared.payload)`` only if allow.

    ``post`` is injected by the host tape. This helper never opens a socket.
    """
    stamp = now or datetime.now(tz=UTC)
    prepared = prepare_sit_match_outbound(
        payload,
        stamp,
        detected_at=detected_at,
        enqueued_at=enqueued_at or stamp,
        stale_at_post=True,
        memory=_MEMORY,
        mute_path=HOST_MUTE_FILE,
    )
    if not prepared.allow:
        return prepared
    if post is not None:
        post(prepared.payload)
        if prepared.occ is not None:
            _MEMORY.remember(prepared.occ, stamp)
    return prepared
