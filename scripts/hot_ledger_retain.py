#!/usr/bin/env python3
"""Verified hot-ledger purge + companion JSONL bound (7–14 day window).

After a verified Box cold-rotate of the closed day pack, purge rows from
``uw_flow.sqlite`` older than ``--keep-hot-days`` and trim companion
material JSONL. Does not enable timers, SSH, or place orders.

Purge is fail-closed until ``--verified`` or ``--confirm``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from groktrading.flow_ledger import FlowLedger
from groktrading.retention import (
    RetentionError,
    discover_companion_jsonl,
    retain_hot_window,
)
from groktrading.timeutil import UTC

DEFAULT_LEDGER = "/var/lib/trading-desk/ledger/uw_flow.sqlite"
DEFAULT_STATE = "/var/lib/trading-desk/state"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Purge the hot UW flow ledger after a verified Box export and "
            "bound companion JSONL. Never uploads secrets. Never places orders."
        )
    )
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help="Hot SQLite path (default /var/lib/trading-desk/ledger/uw_flow.sqlite).",
    )
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE,
        help="Companion state dir to scan for material JSONL.",
    )
    parser.add_argument(
        "--keep-hot-days",
        default=None,
        help="7–14 inclusive (default 7).",
    )
    parser.add_argument(
        "--verified",
        action="store_true",
        help="Operator asserts the closed pack was exported (Box read-after-write).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit purge without a verified Box export.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write the redacted plan JSON.",
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    if not ledger_path.is_file():
        print(f"hot_ledger_retain: ledger missing: {ledger_path}", file=sys.stderr)
        return 2

    jsonl_paths = discover_companion_jsonl(Path(args.state_dir))
    now = datetime.now(tz=UTC)
    ledger = FlowLedger(ledger_path)
    try:
        result = retain_hot_window(
            ledger,
            now=now,
            keep_days=args.keep_hot_days,
            verified=bool(args.verified),
            confirm=bool(args.confirm),
            dry_run=bool(args.dry_run),
            jsonl_paths=jsonl_paths,
        )
    except RetentionError as exc:
        print(f"hot_ledger_retain: fail-closed: {exc}", file=sys.stderr)
        return 2

    doc = {
        "keep_hot_days": result.keep_hot_days,
        "purged_rows": result.purged_rows,
        "verified": result.verified,
        "confirm": result.confirm,
        "dry_run": result.dry_run,
        "jsonl": [
            {
                "path": str(item.path),
                "trimmed": item.trimmed,
                "bytes_before": item.bytes_before,
                "bytes_after": item.bytes_after,
                "lines_before": item.lines_before,
                "lines_after": item.lines_after,
            }
            for item in result.jsonl
        ],
        "note": (
            "Hot ledger 7–14 day window. Box export first. "
            "No secrets. Never places orders. Example timer only — not enabled."
        ),
    }
    print(json.dumps(doc, indent=2, sort_keys=True))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
