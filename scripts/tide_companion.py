#!/usr/bin/env python3
"""Helsinki host companion: UW market-tide (+ optional net-prem) state writer.

Calls write_tide_state (NOT the offline CLI skeleton).
Never prints tokens. Never places orders. Never emits sit_match.
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

from groktrading.feeds.tide_state import tide_poll_sec, write_tide_state  # noqa: E402
from groktrading.feeds.unusual_whales import UnusualWhalesClient  # noqa: E402
from groktrading.timeutil import UTC  # noqa: E402

DEFAULT_STATE = "/var/lib/trading-desk/state/tide_state.json"


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _net_prem_symbols(env: dict[str, str]) -> list[str]:
    raw = env.get("TIDE_NET_PREM_SYMBOLS", "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> int:
    state_path = Path(os.environ.get("TIDE_STATE_PATH", DEFAULT_STATE))
    token = os.environ.get("UW_API_KEY", "").strip()
    if not token:
        print(
            "tide_companion: UW_API_KEY missing (not printed)",
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
    symbols = _net_prem_symbols(env)

    print(
        f"tide_companion: start state={state_path} "
        f"net_prem_n={len(symbols)} no_orders no_sit_match",
        flush=True,
    )

    while True:
        interval = tide_poll_sec(env)
        try:
            doc = write_tide_state(
                client,
                state_path,
                now=clock.now(),
                net_prem_symbols=symbols,
                env=env,
            )
            ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            print(
                f"tide_companion: ts={ts} ticks={doc.get('tick_count')} "
                f"net_prem_keys={len(doc.get('net_prem') or {})} "
                f"skipped={len(doc.get('skipped_tickers') or [])} "
                f"cadence={doc.get('cadence_sec')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"tide_companion: loop_error={type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
