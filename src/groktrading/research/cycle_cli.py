"""File-based CLI for expanded selection, resolution and next-session memory."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from groktrading.research.cycle import Context, DailyRecord, Memory, build_memory, resolve, select
from groktrading.research.opening15 import Packet, now_utc, write_once


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    memory = commands.add_parser("memory")
    memory.add_argument("--session", required=True, type=date.fromisoformat)
    memory.add_argument("--records", nargs="*", default=[], type=Path)
    memory.add_argument("--out", required=True, type=Path)
    for name in ("select", "resolve"):
        command = commands.add_parser(name)
        command.add_argument("--packet", required=True, type=Path)
        command.add_argument("--context", required=True, type=Path)
        command.add_argument("--out", required=True, type=Path)
        if name == "select":
            command.add_argument("--memory", required=True, type=Path)
            command.add_argument("--allow-degraded", action="store_true")
        else:
            command.add_argument("--decision", required=True, type=Path)
            command.add_argument("--evaluation", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "memory":
        records = [DailyRecord.model_validate_json(p.read_text()) for p in args.records]
        result = build_memory(records, args.session, now_utc())
        write_once(args.out, result.model_dump(mode="json"))
    else:
        packet = Packet.model_validate_json(args.packet.read_text())
        context = Context.model_validate_json(args.context.read_text())
        if args.command == "select":
            select(
                packet,
                context,
                Memory.model_validate_json(args.memory.read_text()),
                args.out,
                args.allow_degraded,
            )
        else:
            resolve(
                packet,
                json.loads(args.decision.read_text()),
                json.loads(args.evaluation.read_text()),
                context,
                args.out,
            )


if __name__ == "__main__":
    main()
