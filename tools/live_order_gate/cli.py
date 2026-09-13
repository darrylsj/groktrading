"""Dry-run CLI for live_order_gate. Never POSTs to Tradier."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from groktrading.timeutil import UTC, as_utc
from tools.live_order_gate.gate import (
    PolicyError,
    close_with_audit,
    decision_document,
    evaluate_submit_policy,
    load_thesis,
    write_thesis,
)


def _parse_now(raw: str | None) -> datetime:
    if raw is None or not raw.strip():
        return datetime.now(tz=UTC)
    text = raw.strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit(" --now must be timezone-aware ISO-8601")
    return as_utc(parsed)


def _load_json(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise SystemExit(f"{path} must be a JSON object")
    return doc


def _print(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True))


def _add_shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--now", default=None, help="Timezone-aware ISO-8601 clock (tests).")
    parser.add_argument(
        "--out",
        default=None,
        help="Optional JSON audit path. stdout always prints the document.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_order_gate",
        description=(
            "Tradier one-lot submit/close policy. Dry-run only — this CLI never POSTs."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="Evaluate a BTO entry thesis and emit a dry-run form.")
    submit.add_argument("--thesis", required=True, help="Path to entry thesis JSON.")
    submit.add_argument("--cash", default=None, help="Deployable cash for the debit check.")
    _add_shared(submit)

    close = sub.add_parser("close", help="Evaluate an STC/BTC exit thesis and emit a dry-run form.")
    close.add_argument("--thesis", required=True, help="Path to exit thesis JSON.")
    close.add_argument(
        "--form-json",
        default=None,
        help="Optional Tradier form JSON to validate against the thesis-built form.",
    )
    _add_shared(close)

    write = sub.add_parser("write-thesis", help="Write a thesis JSON (entry or exit).")
    write.add_argument("--out", required=True)
    write.add_argument("--signal-id", required=True)
    write.add_argument("--option-symbol", required=True)
    write.add_argument("--side", required=True)
    write.add_argument("--limit", required=True)
    write.add_argument("--strategy", required=True)
    write.add_argument("--thesis-text", required=True)
    write.add_argument("--written-at", required=True)
    write.add_argument("--intent", choices=("entry", "exit"), default=None)
    write.add_argument("--tag", default=None)
    write.add_argument("--underlying", default="")
    write.add_argument("--parent-signal-id", default=None)
    write.add_argument("--falsifier", default=None)
    write.add_argument(
        "--how-it-dies",
        dest="how_it_dies",
        default=None,
        help="Alias for --falsifier. Required on every written thesis.",
    )
    write.add_argument(
        "--overnight-carry",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "When true, require carry_dte + carry_event_risk + carry_rationale. "
            "Soft field — not a flatten or cash-floor change."
        ),
    )
    write.add_argument("--carry-dte", default=None, help="Remaining DTE note (string or int).")
    write.add_argument(
        "--carry-event-risk",
        default=None,
        help="Next catalyst / gap risk (required when --overnight-carry).",
    )
    write.add_argument(
        "--carry-rationale",
        default=None,
        help="Why the mechanism survives overnight. Not 'cash floor OK'.",
    )
    write.add_argument("--receipt", default=None, help="Optional thesis receipt JSON path.")
    write.add_argument("--evidence", default=None, help="Optional evidence markdown path.")
    write.add_argument(
        "--thinking",
        default=None,
        help="Optional thinking.jsonl append path (gates/carry row).",
    )
    write.add_argument("--quantity", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "write-thesis":
            ticket = write_thesis(
                signal_id=args.signal_id,
                option_symbol=args.option_symbol,
                side=args.side,
                limit=args.limit,
                strategy=args.strategy,
                thesis=args.thesis_text,
                written_at=_parse_now(args.written_at),
                intent=args.intent,
                tag=args.tag,
                quantity=args.quantity,
                underlying=args.underlying,
                parent_signal_id=args.parent_signal_id,
                falsifier=args.falsifier,
                how_it_dies=args.how_it_dies,
                overnight_carry=args.overnight_carry,
                carry_dte=args.carry_dte,
                carry_event_risk=args.carry_event_risk,
                carry_rationale=args.carry_rationale,
                require_overnight_carry=args.overnight_carry is True,
                path=args.out,
                receipt_path=args.receipt,
                evidence_path=args.evidence,
                thinking_path=args.thinking,
            )
            _print(ticket.to_dict())
            return 0

        now = _parse_now(args.now)
        thesis = load_thesis(args.thesis)
        if args.command == "submit":
            cash = Decimal(str(args.cash)) if args.cash is not None else None
            decision = evaluate_submit_policy(thesis, now=now, cash=cash, preview=True)
            doc = decision_document(decision, now=now, command="submit")
            if args.out:
                Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            _print(doc)
            return 0 if decision.allowed else 2

        form = _load_json(Path(args.form_json)) if args.form_json else None
        doc = close_with_audit(thesis, now=now, form=form, preview=True)
        if args.out:
            Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        _print(doc)
        return 0
    except PolicyError as exc:
        _print(
            {
                "kind": "live_order_gate_error",
                "allowed": False,
                "reasons": [exc.code],
                "places_orders": False,
                "dry_run": True,
                "note": str(exc),
            }
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
