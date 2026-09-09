#!/usr/bin/env python3
"""Helsinki host companion: UW option-trades → append-only flow ledger.

Package CLI ``groktrading-tape`` is an offline skeleton. This process is the
live poller. It stores parseable rows only. It does **not** emit sit_match
and never places orders. Grok Bot decides.

Authorization Bearer is runtime env only (see helsinki_http.py).
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from groktrading.cadence import env_seconds
from groktrading.feeds.unusual_whales import (
    UW_OPTION_TRADES_PATH,
    UnusualWhalesClient,
    uw_data_rows,
)
from groktrading.flow_ledger import FlowLedger, FlowLedgerError
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC, as_utc
from helsinki_http import NEVER_ORDERS_NOTE as HTTP_NOTE
from helsinki_http import ledger_path, make_uw_client, state_dir

NEVER_ORDERS_NOTE = (
    "Host flow-ledger companion polls UW option-trades into the hot ledger. "
    "emit_sit_match=False. Never places orders. Grok Bot decides. "
    + HTTP_NOTE
)
FLOW_SEC_ENV = "FLOW_SEC"
FLOW_LEDGER_POLL_ENV = "FLOW_LEDGER_POLL_SEC"
DEFAULT_POLL_SEC = 15.0
POLL_LO = 5.0
POLL_HI = 60.0
DEFAULT_LIMIT = "50"


def poll_sec(env: Mapping[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = str(source.get(FLOW_LEDGER_POLL_ENV, "")).strip()
    key = FLOW_LEDGER_POLL_ENV if raw else FLOW_SEC_ENV
    return env_seconds(
        source,
        key,
        default=DEFAULT_POLL_SEC,
        lo=POLL_LO,
        hi=POLL_HI,
    )


def one_poll(
    client: UnusualWhalesClient,
    ledger: FlowLedger,
    *,
    now: datetime | None = None,
    limit: str = DEFAULT_LIMIT,
) -> dict[str, object]:
    stamp = as_utc(now or client.clock.now())
    _status, body = client.get_documented_path(
        UW_OPTION_TRADES_PATH, params={"limit": str(limit)}
    )
    rows = uw_data_rows(body)
    stored = 0
    for payload in rows:
        try:
            ledger.append_row(payload, source="option-trades", ingested_at=stamp)
            stored += 1
        except FlowLedgerError:
            continue
    return {
        "source": "uw_option_trades",
        "path": UW_OPTION_TRADES_PATH,
        "note": NEVER_ORDERS_NOTE,
        "as_of": stamp.isoformat(),
        "cadence_sec": poll_sec(),
        "fetched": len(rows),
        "stored": stored,
        "emits_sit_match": False,
        "places_orders": False,
        "live_http": True,
        "mode": "signals_only",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Helsinki flow-ledger companion. Polls UW option-trades into "
            "SQLite. emit_sit_match=False. Never places orders."
        )
    )
    parser.add_argument("--ledger", default="", help="FLOW_LEDGER_PATH override")
    parser.add_argument("--state", default="", help="State JSON path")
    parser.add_argument("--once", action="store_true", help="One poll then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ
    path = Path(args.ledger) if args.ledger else ledger_path(env)
    state = Path(args.state) if args.state else state_dir(env) / "flow_ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state.parent.mkdir(parents=True, exist_ok=True)
    client = make_uw_client(env)
    ledger = FlowLedger(path)
    while True:
        doc = one_poll(client, ledger, now=datetime.now(tz=UTC))
        write_json_atomic(state, doc)
        if args.once:
            return 0
        time.sleep(poll_sec(env))


if __name__ == "__main__":
    raise SystemExit(main())
