"""Minimal CLI for Finnhub REST probe and tape writer. Never places orders."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from groktrading.feeds.account_events import NEVER_ORDERS_NOTE, AccountEventStreamState
from groktrading.feeds.finnhub import (
    FINNHUB_REST_BASE,
    FinnhubStreamState,
    FinnhubWatchlist,
    probe_quote,
)
from groktrading.feeds.flow_alerts import (
    DEFAULT_FLOW_ALERTS_POLL_SEC,
)
from groktrading.feeds.flow_alerts import (
    NEVER_ORDERS_NOTE as FLOW_ALERTS_NOTE,
)
from groktrading.feeds.flow_alerts import (
    state_document as flow_alerts_state_document,
)
from groktrading.feeds.quote_subscribe import (
    NEVER_ORDERS_NOTE as QUOTE_INTEREST_NOTE,
)
from groktrading.feeds.quote_subscribe import (
    TradierQuoteInterest,
)
from groktrading.feeds.screener_snapshot import (
    DEFAULT_SCREENER_POLL_SEC,
)
from groktrading.feeds.screener_snapshot import (
    NEVER_ORDERS_NOTE as SCREENER_NOTE,
)
from groktrading.feeds.shadow_marks import (
    DEFAULT_SHADOW_MARK_SEC,
    marks_document,
)
from groktrading.feeds.shadow_marks import (
    NEVER_ORDERS_NOTE as SHADOW_NOTE,
)
from groktrading.feeds.tide_state import (
    DEFAULT_TIDE_POLL_SEC,
)
from groktrading.feeds.tide_state import (
    NEVER_ORDERS_NOTE as TIDE_NOTE,
)
from groktrading.feeds.uw_ws import (
    NEVER_ORDERS_NOTE as UW_WS_NOTE,
)
from groktrading.feeds.uw_ws import (
    probe_document,
    probe_uw_ws,
)
from groktrading.flow_ledger import FlowLedger
from groktrading.io_atomic import write_json_atomic
from groktrading.redaction import redact_mapping
from groktrading.replay_scorecard import scorecard
from groktrading.timeutil import UTC


class HttpxProbe:
    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, Any]]:
        response = httpx.get(url, headers=headers or {}, timeout=self.timeout)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {"data": body}
        return response.status_code, body


def finnhub_probe_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finnhub REST quote probe (signals only).")
    parser.add_argument("--symbol", default="SPY")
    args = parser.parse_args(argv)
    token = os.environ.get("FINNHUB_API_KEY", "")
    if not token:
        print("FINNHUB_API_KEY is required in the environment", file=sys.stderr)
        return 2
    status, body = probe_quote(HttpxProbe(), args.symbol, token=token)
    print(f"http_status={status} rest_base={FINNHUB_REST_BASE} symbol={args.symbol}")
    print(redact_mapping({"ok": status == 200, "has_c": "c" in body}))
    return 0 if status == 200 else 1


def finnhub_tape_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write an empty Finnhub tape skeleton. Does not connect unless --connect."
    )
    parser.add_argument("--output", default="finnhub_tape.json")
    parser.add_argument("--symbol", action="append", dest="symbols", default=None)
    parser.add_argument(
        "--connect",
        action="store_true",
        help="Reserved. This CLI refuses to place orders and does not auto-trade.",
    )
    args = parser.parse_args(argv)
    symbols = args.symbols or ["SPY", "QQQ"]
    watch = FinnhubWatchlist()
    for symbol in symbols:
        watch.add(symbol)
    state = FinnhubStreamState(watchlist=watch)
    doc = state.tape_document([])
    doc["mode"] = "signals_only"
    doc["generated_ts"] = datetime.now(tz=UTC).isoformat()
    if args.connect:
        doc["connect_requested"] = True
        doc["note"] = (
            "Connect is an operator deployment step. This process still never places orders."
        )
    write_json_atomic(Path(args.output), doc)
    return 0


def tape_skeleton_main(argv: list[str] | None = None) -> int:
    """Write a signals-only tape skeleton. Not the legacy UW+Tradier ws_tape.py."""
    parser = argparse.ArgumentParser(
        description=(
            "Write a signals-only package tape skeleton. "
            "Not a port of /opt/trading-desk/ws_tape.py. Never places orders."
        )
    )
    parser.add_argument("--output", default="package_tape_skeleton.json")
    args = parser.parse_args(argv)
    doc = {
        "kind": "package_tape_skeleton",
        "mode": "signals_only",
        "live_explicitly_enabled": False,
        "generated_ts": datetime.now(tz=UTC).isoformat(),
        "note": (
            "Not the legacy /opt/trading-desk/ws_tape.py UW+Tradier tape. "
            "Migration is an operator step. This process never places orders. "
            "WebSocket never places orders. Finnhub is not option NBBO. "
            "Sandbox is not live fill evidence."
        ),
    }
    write_json_atomic(Path(args.output), doc)
    return 0


def _account_events_enabled(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return str(source.get("ACCOUNT_EVENTS_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def account_events_main(argv: list[str] | None = None) -> int:
    """Write position-truth state. Never connects to Tradier. Never places orders.

    ``--listen`` stays resident and rewrites state. Live WS recv is host-wired
    through ``ReconnectingAccountEventsClient`` — this CLI does not open a
    Tradier socket (CI / default install stay offline).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Tradier account-events position-truth helper. "
            "WebSocket never places orders. This CLI does not submit."
        )
    )
    parser.add_argument("--state", default="account_events.json")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Stay resident and rewrite state. Still does not open Tradier.",
    )
    args = parser.parse_args(argv)
    enabled = _account_events_enabled()
    state = AccountEventStreamState()
    doc = state.state_document()
    doc["mode"] = "signals_only"
    doc["account_events_enabled"] = enabled
    doc["listen_requested"] = bool(args.listen)
    doc["live_socket"] = False
    doc["note"] = NEVER_ORDERS_NOTE
    write_json_atomic(Path(args.state), doc)
    if not args.listen:
        return 0
    if not enabled:
        return 0
    # Enabled listen still refuses an implicit live Tradier connect.
    print(
        "account-events: ACCOUNT_EVENTS_ENABLED=1; package CLI still will not "
        "open a Tradier socket. Wire ReconnectingAccountEventsClient on the host.",
        file=sys.stderr,
    )
    return 0


def flow_alerts_main(argv: list[str] | None = None) -> int:
    """Write flow-alerts helper state. Does not poll UW. Never places orders."""
    parser = argparse.ArgumentParser(
        description=(
            "UW flow-alerts poller helper skeleton. "
            "Host wires poll_flow_alerts. Never places orders."
        )
    )
    parser.add_argument("--state", default="flow_alerts.json")
    args = parser.parse_args(argv)
    now = datetime.now(tz=UTC)
    doc = flow_alerts_state_document(None, now=now, seen_count=0)
    doc["mode"] = "signals_only"
    doc["live_http"] = False
    doc["cadence_sec"] = DEFAULT_FLOW_ALERTS_POLL_SEC
    doc["note"] = FLOW_ALERTS_NOTE
    write_json_atomic(Path(args.state), doc)
    return 0


def tide_state_main(argv: list[str] | None = None) -> int:
    """Write an empty tide_state skeleton. Does not call UW."""
    parser = argparse.ArgumentParser(
        description="UW market-tide / net-prem state skeleton. Never places orders."
    )
    parser.add_argument("--state", default="tide_state.json")
    args = parser.parse_args(argv)
    now = datetime.now(tz=UTC)
    doc = {
        "source": "uw_market_tide",
        "note": TIDE_NOTE,
        "as_of": now.isoformat(),
        "cadence_sec": DEFAULT_TIDE_POLL_SEC,
        "ticks": [],
        "net_prem": {},
        "places_orders": False,
        "emits_sit_match": False,
        "live_http": False,
        "mode": "signals_only",
    }
    write_json_atomic(Path(args.state), doc)
    return 0


def quote_interest_main(argv: list[str] | None = None) -> int:
    """Write Tradier quote-interest state. Does not open a market WS."""
    parser = argparse.ArgumentParser(
        description=(
            "Tradier quote interest helper. Live ws_tape.py is host-owned. "
            "WebSocket never places orders."
        )
    )
    parser.add_argument("--state", default="quote_interest.json")
    args = parser.parse_args(argv)
    interest = TradierQuoteInterest()
    doc = interest.state_document()
    doc["mode"] = "signals_only"
    doc["note"] = QUOTE_INTEREST_NOTE
    write_json_atomic(Path(args.state), doc)
    return 0


def screener_snapshot_main(argv: list[str] | None = None) -> int:
    """Write a screener snapshot skeleton. Does not poll UW or emit sit_match."""
    parser = argparse.ArgumentParser(
        description=(
            "UW option-screener snapshot skeleton. "
            "Do not spray sit_match. Never places orders."
        )
    )
    parser.add_argument("--state", default="screener_state.json")
    args = parser.parse_args(argv)
    now = datetime.now(tz=UTC)
    doc = {
        "source": "uw_option_screener",
        "note": SCREENER_NOTE,
        "as_of": now.isoformat(),
        "cadence_sec": DEFAULT_SCREENER_POLL_SEC,
        "rth": False,
        "wrote": False,
        "rows": [],
        "emits_sit_match": False,
        "places_orders": False,
        "live_http": False,
        "mode": "signals_only",
    }
    write_json_atomic(Path(args.state), doc)
    return 0


def shadow_marks_main(argv: list[str] | None = None) -> int:
    """Write a shadow-mark book skeleton. Does not quote Tradier or submit."""
    parser = argparse.ArgumentParser(
        description="Shadow minute-mark helper skeleton. Never places orders."
    )
    parser.add_argument("--state", default="shadow_marks.json")
    args = parser.parse_args(argv)
    now = datetime.now(tz=UTC)
    doc = marks_document([], now=now, occ_count=0)
    doc["mode"] = "signals_only"
    doc["cadence_sec"] = DEFAULT_SHADOW_MARK_SEC
    doc["live_http"] = False
    doc["note"] = SHADOW_NOTE
    write_json_atomic(Path(args.state), doc)
    return 0


def uw_ws_probe_main(argv: list[str] | None = None) -> int:
    """Inspect UW_WS_URL. Fail-closed if unset. Never opens a socket."""
    parser = argparse.ArgumentParser(
        description=(
            "UW WebSocket probe stub. Fail-closed if UW_WS_URL is unset. "
            "Does not invent a subscribe protocol. Does not connect."
        )
    )
    parser.add_argument("--state", default="uw_ws_probe.json")
    args = parser.parse_args(argv)
    probe = probe_uw_ws(dict(os.environ))
    doc = probe_document(probe)
    doc["mode"] = "signals_only"
    doc["note"] = UW_WS_NOTE
    write_json_atomic(Path(args.state), doc)
    return 0 if probe.ok else 2


def replay_scorecard_main(argv: list[str] | None = None) -> int:
    """Read a local flow ledger and write a deterministic scorecard. No PnL."""
    parser = argparse.ArgumentParser(
        description=(
            "Replay scorecard over a local flow ledger. "
            "Counts only. No invented PnL. No network."
        )
    )
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output", default="replay_scorecard.json")
    parser.add_argument("--already-run", default="", help="Comma-separated OCC list")
    args = parser.parse_args(argv)
    ledger_path = Path(args.ledger)
    if not ledger_path.is_file() and str(ledger_path) != ":memory:":
        print(f"ledger not found: {ledger_path}", file=sys.stderr)
        return 2
    already = [p for p in args.already_run.split(",") if p.strip()]
    now = datetime.now(tz=UTC)
    card = scorecard(FlowLedger(ledger_path), now=now, already_run_occs=already)
    write_json_atomic(Path(args.output), card.document())
    return 0


if __name__ == "__main__":
    raise SystemExit(finnhub_probe_main())
