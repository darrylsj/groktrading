"""Observational shadow-bets RSI CLI. Never calls a broker. Never invents NBBO."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.shadow_bets.config import I1_MAX_AGE_SEC, LIVE_GATE, ShadowBetsError
from tools.shadow_bets.ledger import ShadowBook


def _print(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True))


def _write_out(path: str | None, doc: dict[str, Any]) -> None:
    if path:
        Path(path).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--now", default=None, help="Timezone-aware ISO-8601 clock (tests).")
    parser.add_argument("--out", default=None, help="Optional JSON path. stdout always prints.")
    parser.add_argument(
        "--pack",
        default=None,
        help="PACK root (default SHADOW_BETS_PACK or repo root).",
    )


def _add_session(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument(
        "--session",
        required=required,
        help="PT session YYYY-MM-DD.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadow_bets",
        description=(
            "Observational shadow-bets RSI (refuse ledger → Tradier-cited marks). "
            "Never calls Tradier/UW. Never invents NBBO. Never places orders. "
            "live_gate=false. Labels are observational only. Does not unlock I1>60."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_session = sub.add_parser(
        "run-session",
        help="Open refuses, apply marks if given, then summarize one session.",
    )
    _add_session(run_session)
    run_session.add_argument("--refuses", default=None, help="Refuse ledger JSON/JSONL.")
    run_session.add_argument("--marks", default=None, help="Tradier-cited marks JSON/JSONL.")
    _add_shared(run_session)

    open_cmd = sub.add_parser(
        "open-from-refuses",
        help="Open shadow bets from a refuse ledger (I1_stale backlog, …).",
    )
    _add_session(open_cmd)
    open_cmd.add_argument("--refuses", required=True, help="Refuse ledger JSON/JSONL.")
    _add_shared(open_cmd)

    mark_cmd = sub.add_parser(
        "mark-session",
        help="Apply Tradier-cited marks. Missing OCCs stay unmarked.",
    )
    _add_session(mark_cmd)
    mark_cmd.add_argument("--marks", required=True, help="Tradier-cited marks JSON/JSONL.")
    _add_shared(mark_cmd)

    summary = sub.add_parser("summarize", help="Observational session RSI. No invented P&L.")
    _add_session(summary)
    _add_shared(summary)
    return parser


def _book(args: argparse.Namespace) -> ShadowBook:
    return ShadowBook(pack=args.pack)


def _error(exc: ShadowBetsError) -> dict[str, Any]:
    return {
        "kind": "shadow_bets_error",
        "ok": False,
        "reasons": [exc.code],
        "note": str(exc),
        "live_gate": LIVE_GATE,
        "places_orders": False,
        "invented": False,
        "unlock_i1": False,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        book = _book(args)
        if args.command == "run-session":
            doc = book.run_session(
                session=args.session,
                refuses=Path(args.refuses) if args.refuses else None,
                marks=Path(args.marks) if args.marks else None,
                now=args.now,
            )
        elif args.command == "open-from-refuses":
            doc = book.open_from_refuses(
                Path(args.refuses),
                session=args.session,
                now=args.now,
            )
        elif args.command == "mark-session":
            doc = book.mark_session(
                Path(args.marks),
                session=args.session,
                now=args.now,
            )
        else:
            doc = book.summarize(session=args.session, now=args.now)
        _write_out(args.out, doc)
        _print(doc)
        return 0
    except ShadowBetsError as exc:
        doc = _error(exc)
        _write_out(getattr(args, "out", None), doc)
        _print(doc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
