#!/usr/bin/env python3
"""Helsinki host companion: UW flow-alerts poller.

Package CLI ``groktrading-flow-alerts`` is an offline skeleton. This process
is the live poller. It appends parseable rows (``source=flow-alerts``) and
records new alert ids. **emit_sit_match=False**. No webhook firehose by
default (``on_material`` is not wired). Never places orders. Grok Bot decides.

Authorization Bearer is runtime env only (see helsinki_http.py).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from groktrading.feeds.flow_alerts import NEVER_ORDERS_NOTE as FLOW_NOTE
from groktrading.feeds.flow_alerts import (
    SeenAlertStore,
    flow_alerts_poll_sec,
    poll_flow_alerts,
    state_document,
)
from groktrading.flow_ledger import FlowLedger
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC
from helsinki_http import NEVER_ORDERS_NOTE as HTTP_NOTE
from helsinki_http import ledger_path, make_uw_client, state_dir

NEVER_ORDERS_NOTE = (
    "Host flow-alerts companion. emit_sit_match=False. "
    "No webhook firehose by default. Never places orders. "
    + FLOW_NOTE
    + " "
    + HTTP_NOTE
)
EMIT_SIT_MATCH = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Helsinki flow-alerts companion. Live UW poll. "
            "emit_sit_match=False. No webhook firehose by default. "
            "Never places orders."
        )
    )
    parser.add_argument("--ledger", default="", help="FLOW_LEDGER_PATH override")
    parser.add_argument("--state", default="", help="State JSON path")
    parser.add_argument("--seen", default="", help="Seen-alert-id JSON path")
    parser.add_argument(
        "--webhook-firehose",
        action="store_true",
        default=False,
        help="Ignored / refuse. Default off. This companion does not fire webhooks.",
    )
    parser.add_argument("--once", action="store_true", help="One poll then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.webhook_firehose:
        print(
            "flow-alerts companion: webhook firehose is disabled "
            "(no sit_match spray; Grok Bot decides).",
            file=sys.stderr,
        )
    env = os.environ
    path = Path(args.ledger) if args.ledger else ledger_path(env)
    state = Path(args.state) if args.state else state_dir(env) / "flow_alerts.json"
    seen_path = Path(args.seen) if args.seen else state_dir(env) / "flow_alerts_seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state.parent.mkdir(parents=True, exist_ok=True)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    client = make_uw_client(env)
    ledger = FlowLedger(path)
    seen = SeenAlertStore(path=seen_path)
    while True:
        now = datetime.now(tz=UTC)
        result = poll_flow_alerts(
            client,
            ledger,
            seen,
            now=now,
            env=env,
            on_material=None,
            emit_sit_match=EMIT_SIT_MATCH,
        )
        doc = state_document(result, now=now, seen_count=len(seen._ids))
        doc["live_http"] = True
        doc["emits_sit_match"] = False
        doc["webhook_firehose"] = False
        doc["places_orders"] = False
        doc["note"] = NEVER_ORDERS_NOTE
        write_json_atomic(state, doc)
        if args.once:
            return 0
        time.sleep(flow_alerts_poll_sec(env))


if __name__ == "__main__":
    raise SystemExit(main())
