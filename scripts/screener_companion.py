#!/usr/bin/env python3
"""Helsinki host companion: RTH UW option-screener snapshot.

Calls write_screener_state(..., rth_only=True). Outside RTH the library
no-op skips the write. Never sprays sit_match. Never prints tokens.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helsinki_http import UrllibHttp  # noqa: E402

from groktrading.feeds.screener_snapshot import (  # noqa: E402
    screener_poll_sec,
    write_screener_state,
)
from groktrading.feeds.unusual_whales import UnusualWhalesClient  # noqa: E402
from groktrading.timeutil import UTC  # noqa: E402

DEFAULT_STATE = "/var/lib/trading-desk/state/screener_state.json"


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def main() -> int:
    state_path = Path(os.environ.get("SCREENER_STATE_PATH", DEFAULT_STATE))
    token = os.environ.get("UW_API_KEY", "").strip()
    if not token:
        print(
            "screener_companion: UW_API_KEY missing (not printed)",
            file=sys.stderr,
            flush=True,
        )
        return 2

    state_path.parent.mkdir(parents=True, exist_ok=True)
    clock = UtcClock()
    client = UnusualWhalesClient(
        http=UrllibHttp(timeout=20.0), clock=clock, token=token
    )
    env = dict(os.environ)

    print(
        f"screener_companion: start state={state_path} rth_only=True "
        "no_sit_match_spray no_orders",
        flush=True,
    )

    while True:
        interval = screener_poll_sec(env)
        try:
            doc = write_screener_state(
                client,
                state_path,
                now=clock.now(),
                env=env,
                rth_only=True,
            )
            ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            print(
                f"screener_companion: ts={ts} wrote={doc.get('wrote')} "
                f"rth={doc.get('rth')} rows={doc.get('row_count')} "
                f"skip={doc.get('skipped_reason')} cadence={doc.get('cadence_sec')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"screener_companion: loop_error={type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
