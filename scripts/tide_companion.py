#!/usr/bin/env python3
"""Helsinki host companion: UW market-tide / optional net-prem → tide_state.json.

Package CLI ``groktrading-tide`` is an offline skeleton. This process is the
live poller. **emit_sit_match=False**. Never places orders. Grok Bot decides.

Authorization Bearer is runtime env only (see helsinki_http.py).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from groktrading.feeds.tide_state import NEVER_ORDERS_NOTE as TIDE_NOTE
from groktrading.feeds.tide_state import tide_poll_sec, write_tide_state
from groktrading.io_atomic import write_json_atomic
from helsinki_http import NEVER_ORDERS_NOTE as HTTP_NOTE
from helsinki_http import make_uw_client, state_dir

NEVER_ORDERS_NOTE = (
    "Host tide companion. emit_sit_match=False. Never places orders. "
    + TIDE_NOTE
    + " "
    + HTTP_NOTE
)


def _net_prem_symbols(env: dict[str, str] | None = None) -> list[str]:
    source = os.environ if env is None else env
    raw = str(source.get("TIDE_NET_PREM_SYMBOLS", "")).strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Helsinki tide companion. Live UW market-tide poll. "
            "emit_sit_match=False. Never places orders. Grok Bot decides."
        )
    )
    parser.add_argument("--state", default="", help="tide_state.json path")
    parser.add_argument("--once", action="store_true", help="One poll then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ
    state = Path(args.state) if args.state else state_dir(env) / "tide_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    client = make_uw_client(env)
    while True:
        doc = write_tide_state(
            client,
            state,
            net_prem_symbols=_net_prem_symbols(dict(env)),
            env=env,
        )
        doc["emits_sit_match"] = False
        doc["places_orders"] = False
        doc["live_http"] = True
        doc["note"] = NEVER_ORDERS_NOTE
        write_json_atomic(state, doc)
        if args.once:
            return 0
        time.sleep(tide_poll_sec(env))


if __name__ == "__main__":
    raise SystemExit(main())
