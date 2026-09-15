"""Desk live-board CLI. Observational. Never opens a socket. Never orders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dashboard.builder import build_board, write_board
from dashboard.config import (
    BOARD_NOTE,
    I1_MAX_AGE_SEC,
    LIVE_GATE,
    NEW_WS_SUBSCRIPTIONS,
    OPPORTUNITY_WEBHOOK_RESUME,
    SCHEMA_ID,
    SIT_MATCH_STAYS_OFF,
    DashboardError,
)


def _print(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True, default=str))


def _path(value: str | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dashboard",
        description=BOARD_NOTE,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build",
        help="Build static board.json + index.html from evidence (no Helsinki required).",
    )
    build.add_argument(
        "--refuses",
        default=None,
        help="uw_opportunity_refuses.jsonl (or JSON list). Missing → funnel empty_reason.",
    )
    build.add_argument("--shortlist", default=None, help="Optional shortlist.json hook.")
    build.add_argument(
        "--shadow-summary",
        default=None,
        help="Optional shadow_bets summarize JSON hook.",
    )
    build.add_argument(
        "--finnhub-tape",
        default=None,
        help="Optional READ-ONLY finnhub_tape.json snapshot (connection/freshness/symbols).",
    )
    build.add_argument(
        "--live-tape",
        default=None,
        help="Optional READ-ONLY live_tape health JSON (flow_n/flow_http/errors/candidates).",
    )
    build.add_argument(
        "--book",
        default=None,
        help="Optional READ-ONLY book/positions JSON. Missing → book empty_reason.",
    )
    build.add_argument(
        "--open-orders",
        default=None,
        help="Optional READ-ONLY open-orders JSON. Missing → open_orders empty_reason.",
    )
    build.add_argument("--session", default=None, help="PT session YYYY-MM-DD.")
    build.add_argument("--now", default=None, help="Timezone-aware ISO-8601 clock (tests).")
    build.add_argument(
        "--omit-ws-stats",
        action="store_true",
        help="Omit the optional ws_stats section entirely.",
    )
    build.add_argument("--out", default=None, help="Write board.json to this path.")
    build.add_argument("--html", default=None, help="Write index.html to this path.")
    build.add_argument(
        "--out-dir",
        default=None,
        help="Write board.json + index.html here (sibling-site static pattern).",
    )
    return parser


def _error(exc: DashboardError) -> dict[str, Any]:
    return {
        "kind": "desk_board_error",
        "ok": False,
        "reasons": [exc.code],
        "note": str(exc),
        "schema": SCHEMA_ID,
        "live_gate": LIVE_GATE,
        "places_orders": False,
        "invented": False,
        "unlock_i1": False,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
        "sit_match": False,
        "sit_match_stays_off": SIT_MATCH_STAYS_OFF,
        "new_ws_subscriptions": NEW_WS_SUBSCRIPTIONS,
        "opportunity_webhook_resume": OPPORTUNITY_WEBHOOK_RESUME,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command != "build":
            raise DashboardError("unknown_command", f"unknown command {args.command}")
        board = build_board(
            refuses=_path(args.refuses),
            shortlist=_path(args.shortlist),
            shadow_summary=_path(args.shadow_summary),
            finnhub_tape=_path(args.finnhub_tape),
            live_tape=_path(args.live_tape),
            book=_path(args.book),
            open_orders=_path(args.open_orders),
            session=args.session,
            now=args.now,
            include_ws_stats=not args.omit_ws_stats,
        )
        written = {}
        if args.out or args.html or args.out_dir:
            written = write_board(
                board,
                out_json=_path(args.out),
                out_html=_path(args.html),
                out_dir=_path(args.out_dir),
            )
            board = {**board, "written": written}
        _print(board)
        return 0
    except DashboardError as exc:
        doc = _error(exc)
        _print(doc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
