"""Minimal CLI for Finnhub REST probe and tape writer. Never places orders."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from groktrading.feeds.finnhub import (
    FINNHUB_REST_BASE,
    FinnhubStreamState,
    FinnhubWatchlist,
    probe_quote,
)
from groktrading.io_atomic import write_json_atomic
from groktrading.redaction import redact_mapping
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


if __name__ == "__main__":
    raise SystemExit(finnhub_probe_main())
