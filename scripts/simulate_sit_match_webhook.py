#!/usr/bin/env python3
"""Local sit_match webhook hop chase. Never reads grok-webhook.env.

Usage (from repo root, PYTHONPATH=src):

  python scripts/simulate_sit_match_webhook.py
  python scripts/simulate_sit_match_webhook.py --stale
  python scripts/simulate_sit_match_webhook.py --lie-print-age

Fresh path: POST to 127.0.0.1 with executed_at=now; expect post_ms in
milliseconds and print_age_sec ≈ 0.

Stale / lie path: executed_at is 10 minutes old (optional print_age_sec=5);
expect no HTTP receive and skip sit_match_stale / sit_match_print_age_contradicts.

Helsinki verify: after patching ws_tape.py to call prepare_sit_match_outbound
immediately before POST, restart trading-desk-tape and compare journal hop
lines to this script. Do not point this script at the live Grok inbox.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from groktrading.sit_match_sim import (  # noqa: E402
    result_document,
    simulate_sit_match_http,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local sit_match POST simulation. Never places orders. "
            "Does not read grok-webhook.env."
        )
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="Use executed_at 600s ago (must not POST).",
    )
    parser.add_argument(
        "--lie-print-age",
        action="store_true",
        help="Stamp print_age_sec=5 on a 600s-old executed_at (must not POST).",
    )
    args = parser.parse_args(argv)
    stale = bool(args.stale or args.lie_print_age)
    lie = 5.0 if args.lie_print_age else None
    result = simulate_sit_match_http(stale_executed_at=stale, lie_print_age_sec=lie)
    print(json.dumps(result_document(result), indent=2, sort_keys=True))
    if stale:
        return 0 if (not result.sent and not result.http_received) else 1
    if not result.sent or not result.http_received:
        return 1
    if result.post_ms is not None and result.post_ms > 2000:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
