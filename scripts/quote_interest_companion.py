#!/usr/bin/env python3
"""Helsinki host companion: Tradier quote interest set publisher.

Reads recent underlyings from the hot flow ledger, updates TradierQuoteInterest
via note_flow_row (freshness-gated), writes quote_interest.json.

Live ws_tape.py subscribe remains host-owned — this only publishes the
interest set for Grok/operator. Never opens a Tradier socket. Never orders.
Never prints tokens.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from groktrading.feeds.quote_subscribe import (
    TradierQuoteInterest,
    quote_idle_ttl_sec,
    quote_watch_bound,
)
from groktrading.flow_ledger import FlowLedger
from groktrading.io_atomic import write_json_atomic
from groktrading.timeutil import UTC

DEFAULT_LEDGER = "/var/lib/trading-desk/ledger/uw_flow.sqlite"
DEFAULT_STATE = "/var/lib/trading-desk/state/quote_interest.json"
DEFAULT_POLL = 60.0
DEFAULT_RECENT = 80


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _seed_symbols(env: dict[str, str]) -> list[str]:
    raw = env.get("QUOTE_INTEREST_SEED", env.get("QUOTE_INTEREST_SYMBOLS", "")).strip()
    if not raw:
        return []
    return [p.strip().upper() for p in raw.split(",") if p.strip()]


def main() -> int:
    ledger_path = Path(os.environ.get("FLOW_LEDGER_PATH", DEFAULT_LEDGER))
    state_path = Path(os.environ.get("QUOTE_INTEREST_STATE_PATH", DEFAULT_STATE))
    interval = max(15.0, _env_float("QUOTE_INTEREST_POLL_SEC", DEFAULT_POLL))
    recent_n = max(1, _env_int("QUOTE_INTEREST_RECENT_N", DEFAULT_RECENT))
    env = dict(os.environ)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    clock = UtcClock()
    interest = TradierQuoteInterest(
        bound=quote_watch_bound(env),
        idle_ttl_seconds=quote_idle_ttl_sec(env),
        clock=clock,
    )
    # Optional seed (operator env); not freshness-gated.
    for sym in _seed_symbols(env):
        try:
            interest.touch(sym, now=clock.now())
        except Exception:
            pass

    print(
        f"quote_interest_companion: start state={state_path} "
        f"ledger={ledger_path} interval={interval} "
        "host_owned_tape=ws_tape.py no_socket no_orders",
        flush=True,
    )

    while True:
        try:
            now = clock.now()
            if ledger_path.is_file():
                ledger = FlowLedger(ledger_path, clock=clock)
                for row in ledger.iter_recent(limit=recent_n):
                    try:
                        interest.note_flow_row(row, now, env=env)
                    except Exception:
                        continue
            interest.drop_idle(now)
            doc = interest.state_document(now=now)
            doc["mode"] = "host_companion"
            doc["recent_n"] = recent_n
            write_json_atomic(state_path, doc)
            ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            print(
                f"quote_interest_companion: ts={ts} "
                f"symbols={len(doc.get('symbols') or [])} "
                f"bound={doc.get('bound')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"quote_interest_companion: loop_error={type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
