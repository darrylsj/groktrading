"""Observational strategy-factory CLI. Never calls a broker. Never invents prices."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.strategy_factory.config import (
    CATEGORIES,
    CONFIRMATION_SOURCES,
    LIVE_GATE,
    STAGES,
    FactoryError,
)
from tools.strategy_factory.ledger import StrategyFactory


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
        help="PACK root (default STRATEGY_FACTORY_PACK or repo root).",
    )
    parser.add_argument("--config", default=None, help="Optional config JSON override.")


def _add_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--id",
        "--hyp-id",
        dest="hyp_id",
        required=True,
        help="Hypothesis id (portable Continual15 / pack flag; --hyp-id alias).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strategy_factory",
        description=(
            "Observational hypothesis ledger (generate→paper→validate→kill). "
            "Never calls Tradier/UW. Never invents prices. live_gate=false. "
            "Does not replace live_order_gate."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    propose = sub.add_parser("propose", help="Record a candidate hypothesis.")
    _add_id(propose)
    propose.add_argument("--category", required=True, choices=CATEGORIES)
    propose.add_argument("--title", required=True)
    propose.add_argument("--mechanism", default="")
    propose.add_argument("--falsifier", default="")
    propose.add_argument("--note", default="")
    propose.add_argument("--session", default=None, help="PT session YYYY-MM-DD.")
    _add_shared(propose)

    confirm = sub.add_parser("confirm", help="Attach an allowlisted confirmation (no prices).")
    _add_id(confirm)
    confirm.add_argument("--source", required=True, choices=CONFIRMATION_SOURCES)
    confirm.add_argument("--note", default="")
    confirm.add_argument(
        "--evidence-ref",
        default="",
        help="Citation to existing evidence (tape row / shortlist id). Not a price.",
    )
    _add_shared(confirm)

    advance = sub.add_parser("advance", help="candidate→paper→validated→live_allow.")
    _add_id(advance)
    _add_shared(advance)

    reject = sub.add_parser("reject", help="Reject from candidate/paper/validated.")
    _add_id(reject)
    reject.add_argument("--reason", required=True)
    _add_shared(reject)

    kill = sub.add_parser("kill", help="Kill an open hypothesis.")
    _add_id(kill)
    kill.add_argument("--reason", required=True)
    _add_shared(kill)

    retire = sub.add_parser("retire", help="Retire a validated or live_allow hypothesis.")
    _add_id(retire)
    retire.add_argument("--reason", required=True)
    _add_shared(retire)

    listing = sub.add_parser("list", help="List hypotheses (optional filters).")
    listing.add_argument("--session", default=None)
    listing.add_argument("--stage", default=None, choices=STAGES)
    listing.add_argument("--category", default=None, choices=CATEGORIES)
    _add_shared(listing)

    status = sub.add_parser("status", help="Show one hypothesis snapshot.")
    _add_id(status)
    _add_shared(status)

    score = sub.add_parser("score-day", help="Observational session counts. No P&L.")
    score.add_argument("--session", default=None, help="PT session YYYY-MM-DD.")
    _add_shared(score)
    return parser


def _factory(args: argparse.Namespace) -> StrategyFactory:
    return StrategyFactory(pack=args.pack, config_path=args.config)


def _error(exc: FactoryError) -> dict[str, Any]:
    return {
        "kind": "strategy_factory_error",
        "ok": False,
        "reasons": [exc.code],
        "note": str(exc),
        "live_gate": LIVE_GATE,
        "places_orders": False,
        "invented": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        factory = _factory(args)
        if args.command == "propose":
            hyp = factory.propose(
                hyp_id=args.hyp_id,
                category=args.category,
                title=args.title,
                mechanism=args.mechanism,
                falsifier=args.falsifier,
                note=args.note,
                session=args.session,
                now=args.now,
            )
            doc = hyp.to_dict()
        elif args.command == "confirm":
            hyp = factory.confirm(
                hyp_id=args.hyp_id,
                source=args.source,
                note=args.note,
                evidence_ref=args.evidence_ref,
                now=args.now,
            )
            doc = hyp.to_dict()
        elif args.command == "advance":
            doc = factory.advance(hyp_id=args.hyp_id, now=args.now).to_dict()
        elif args.command == "reject":
            doc = factory.reject(
                hyp_id=args.hyp_id, reason=args.reason, now=args.now
            ).to_dict()
        elif args.command == "kill":
            doc = factory.kill(hyp_id=args.hyp_id, reason=args.reason, now=args.now).to_dict()
        elif args.command == "retire":
            doc = factory.retire(
                hyp_id=args.hyp_id, reason=args.reason, now=args.now
            ).to_dict()
        elif args.command == "list":
            rows = factory.list_hypotheses(
                session=args.session,
                stage=args.stage,
                category=args.category,
            )
            doc = {
                "kind": "strategy_factory_list",
                "live_gate": LIVE_GATE,
                "places_orders": False,
                "count": len(rows),
                "hypotheses": [item.to_dict() for item in rows],
            }
        elif args.command == "status":
            doc = factory.status(args.hyp_id)
        else:
            doc = factory.score_day(session=args.session, now=args.now)
        _write_out(args.out, doc)
        _print(doc)
        return 0
    except FactoryError as exc:
        doc = _error(exc)
        _write_out(getattr(args, "out", None), doc)
        _print(doc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
