#!/usr/bin/env python3
"""Helsinki host companion: thin RTH UW option-screener snapshot.

Package CLI ``groktrading-screener`` is an offline skeleton. This process is
the live poller. **emit_sit_match=False** — do not spray sit_match for every
row. Never places orders. Grok Bot decides.

Authorization Bearer is runtime env only (see helsinki_http.py).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from groktrading.feeds.screener_snapshot import NEVER_ORDERS_NOTE as SCREENER_NOTE
from groktrading.feeds.screener_snapshot import screener_poll_sec, write_screener_state
from groktrading.io_atomic import write_json_atomic
from helsinki_http import NEVER_ORDERS_NOTE as HTTP_NOTE
from helsinki_http import make_uw_client, state_dir

NEVER_ORDERS_NOTE = (
    "Host screener companion. emit_sit_match=False. Never places orders. "
    + SCREENER_NOTE
    + " "
    + HTTP_NOTE
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Helsinki screener companion. Thin RTH UW snapshot. "
            "emit_sit_match=False. Never places orders."
        )
    )
    parser.add_argument("--state", default="", help="screener_state.json path")
    parser.add_argument("--once", action="store_true", help="One poll then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ
    state = Path(args.state) if args.state else state_dir(env) / "screener_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    client = make_uw_client(env)
    while True:
        doc = write_screener_state(client, state, env=env)
        doc["emits_sit_match"] = False
        doc["places_orders"] = False
        doc["live_http"] = True
        doc["note"] = NEVER_ORDERS_NOTE
        if doc.get("wrote"):
            write_json_atomic(state, doc)
        if args.once:
            return 0
        time.sleep(screener_poll_sec(env))


if __name__ == "__main__":
    raise SystemExit(main())
