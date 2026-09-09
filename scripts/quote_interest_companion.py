#!/usr/bin/env python3
"""Helsinki host companion: bounded Tradier quote interest from the flow ledger.

Package CLI ``groktrading-quote-interest`` is an offline skeleton. This process
refreshes the interest set from recent ledger rows. Live ``ws_tape.py`` is
host-owned and must be wired by the operator. This companion never opens a
Tradier socket and never places orders. Grok Bot decides.

No UW HTTP. No sit_match emit. Authorization Bearer is unused here.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

from groktrading.cadence import env_seconds
from groktrading.feeds.quote_subscribe import NEVER_ORDERS_NOTE as QUOTE_NOTE
from groktrading.feeds.quote_subscribe import (
    TradierQuoteInterest,
    quote_idle_ttl_sec,
    quote_watch_bound,
)
from groktrading.flow_ledger import FlowLedger
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC
from helsinki_http import ledger_path, state_dir

NEVER_ORDERS_NOTE = (
    "Host quote-interest companion. Live ws_tape.py is host-owned. "
    "emit_sit_match=False. WebSocket never places orders. "
    + QUOTE_NOTE
)
QUOTE_INTEREST_POLL_ENV = "QUOTE_INTEREST_POLL_SEC"
DEFAULT_POLL_SEC = 20.0
POLL_LO = 15.0
POLL_HI = 60.0
RECENT_LIMIT = 40


def poll_sec(env: dict[str, str] | None = None) -> float:
    return env_seconds(
        os.environ if env is None else env,
        QUOTE_INTEREST_POLL_ENV,
        default=DEFAULT_POLL_SEC,
        lo=POLL_LO,
        hi=POLL_HI,
    )


def refresh(
    ledger: FlowLedger,
    interest: TradierQuoteInterest,
    *,
    now: datetime,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    source = os.environ if env is None else env
    for row in ledger.iter_recent(limit=RECENT_LIMIT):
        interest.note_flow_row(row, now, env=source)
    interest.drop_idle(now)
    doc = interest.state_document(now=now)
    doc["emits_sit_match"] = False
    doc["places_orders"] = False
    doc["live_http"] = False
    doc["live_socket"] = False
    doc["note"] = NEVER_ORDERS_NOTE
    return doc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Helsinki quote-interest companion. Ledger → bounded symbol set. "
            "ws_tape.py is host-owned. Never places orders."
        )
    )
    parser.add_argument("--ledger", default="", help="FLOW_LEDGER_PATH override")
    parser.add_argument("--state", default="", help="quote_interest.json path")
    parser.add_argument("--once", action="store_true", help="One refresh then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ
    path = Path(args.ledger) if args.ledger else ledger_path(env)
    state = Path(args.state) if args.state else state_dir(env) / "quote_interest.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    ledger = FlowLedger(path)
    interest = TradierQuoteInterest(
        bound=quote_watch_bound(env),
        idle_ttl_seconds=quote_idle_ttl_sec(env),
    )
    while True:
        now = datetime.now(tz=UTC)
        doc = refresh(ledger, interest, now=now, env=dict(env))
        write_json_atomic(state, doc)
        if args.once:
            return 0
        time.sleep(poll_sec(env))


if __name__ == "__main__":
    raise SystemExit(main())
