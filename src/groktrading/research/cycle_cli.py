"""File-based CLI for expanded selection, resolution and next-session memory."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from groktrading.research.capture import feeds
from groktrading.research.collectors import (
    collect_context,
    optional_account_id,
    optional_finnhub,
    write_expanded_context,
)
from groktrading.research.cycle import (
    Context,
    FailureRecord,
    Memory,
    build_memory,
    failure_from_exception,
    load_session_record,
    resolve,
    select,
    write_failure,
)
from groktrading.research.opening15 import Config, Packet, now_utc, write_once
from groktrading.research.protocol import protocol_from_paths
from groktrading.research.registry import (
    freeze_active,
    load_registry,
    propose,
    seed_registry,
    set_status,
    write_registry,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def tuesday_commands(session: date, output: Path, *, allow_degraded: bool) -> dict[str, Any]:
    """Exact baseline vs expanded command sequence. Does not enable timers."""
    root = output.as_posix()
    degraded = " --allow-degraded" if allow_degraded else ""
    return {
        "session": session.isoformat(),
        "note": (
            "Tuesday 2026-09-08 is an operational paper pilot on the clean baseline "
            "(research.cli run). Do not launch with --allow-degraded. Expanded select "
            "requires context coverage available (except optional depth / UW dark pool / "
            "screener / tide / political) or an explicit "
            "--allow-degraded label on a later paper day. Do not present a degraded run "
            "as the full-context experiment. Passing unit tests is not live entitlement. "
            "No systemd/timers, no Helsinki restart, no live orders."
        ),
        "baseline": [
            (
                "python -m groktrading.research.cli preflight "
                f"--session {session} --output {root}/preflight"
            ),
            f"python -m groktrading.research.cli model-probe --output {root}/model-probe",
            f"python -m groktrading.research.cli run --session {session} --output {root}",
        ],
        "expanded": [
            (
                "python -m groktrading.research.cli preflight "
                f"--session {session} --output {root}/preflight"
            ),
            f"python -m groktrading.research.cli model-probe --output {root}/model-probe",
            (
                f"python -m groktrading.research.cycle_cli memory --session {session} "
                f"--out {root}/memory.json"
            ),
            (
                "python -m groktrading.research.cli capture "
                f"--session {session} --output {root} "
                "# writes packet.json and preopen context.json"
            ),
            (
                f"python -m groktrading.research.cycle_cli collect-context --session {session} "
                f"--packet {root}/packet.json --out {root}  # rebuild only if context.json absent"
            ),
            (
                f"python -m groktrading.research.cycle_cli select --packet {root}/packet.json "
                f"--context {root}/context.json --memory {root}/memory.json "
                f"--out {root}/selection{degraded}"
            ),
            (
                "python -m groktrading.research.cli monitor "
                f"--session {session} --output {root}/selection"
            ),
            (
                "python -m groktrading.research.cli report "
                f"--session {session} --output {root}/selection"
            ),
            (
                f"python -m groktrading.research.cycle_cli collect-context "
                f"--session {session} --packet {root}/packet.json "
                f"--out {root}/outcome-context.json  # post-session outcome collector"
            ),
            (
                "python -m groktrading.research.cycle_cli resolve "
                f"--packet {root}/selection/packet.json "
                f"--decision {root}/selection/decision.json "
                f"--evaluation {root}/selection/evaluation.json "
                f"--context {root}/outcome-context.json --out {root}/resolution"
            ),
            (
                "python -m groktrading.research.cycle_cli memory "
                f"--session {session + timedelta(days=1)} "
                f"--records {root}/resolution/daily-resolution.json "
                f"--out {root}/../{session + timedelta(days=1)}/memory.json"
            ),
        ],
        "if_stage_fails": (
            f"python -m groktrading.research.cycle_cli fail --session {session} "
            f"--stage <stage> --detail '<ValueError>' --out {root}/failed-<attempt>"
        ),
    }


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
            command.add_argument("--registry", type=Path)
        else:
            command.add_argument("--decision", required=True, type=Path)
            command.add_argument("--evaluation", required=True, type=Path)
    collect = commands.add_parser("collect-context")
    collect.add_argument("--session", required=True, type=date.fromisoformat)
    collect.add_argument("--config", type=Path, default=Path("research/opening15.example.json"))
    collect.add_argument("--packet", type=Path)
    collect.add_argument("--out", required=True, type=Path)
    fail = commands.add_parser("fail")
    fail.add_argument("--session", required=True, type=date.fromisoformat)
    fail.add_argument(
        "--stage",
        required=True,
        choices=(
            "memory",
            "capture",
            "context",
            "select",
            "monitor",
            "evaluate",
            "resolve",
            "day",
        ),
    )
    fail.add_argument("--detail", required=True)
    fail.add_argument("--out", required=True, type=Path)
    fail.add_argument("--error-type", default="ValueError")
    plan = commands.add_parser("day-plan")
    plan.add_argument("--session", required=True, type=date.fromisoformat)
    plan.add_argument("--out", required=True, type=Path)
    plan.add_argument("--allow-degraded", action="store_true")
    registry = commands.add_parser("registry")
    registry.add_argument("--path", required=True, type=Path)
    registry.add_argument("--seed", action="store_true")
    registry.add_argument("--propose-id")
    registry.add_argument("--parent")
    registry.add_argument("--prompt-name", default="selector_v2.md")
    registry.add_argument("--hypothesis")
    registry.add_argument("--difference")
    registry.add_argument("--forward-test")
    registry.add_argument("--status")
    registry.add_argument("--freeze")
    protocol = commands.add_parser("protocol")
    protocol.add_argument("--sessions", nargs="*", default=[], type=Path)
    protocol.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "memory":
            days = []
            failures = []
            for path in args.records:
                loaded = load_session_record(path)
                if isinstance(loaded, FailureRecord):
                    failures.append(loaded)
                else:
                    days.append(loaded)
            result = build_memory(days, args.session, now_utc(), failures=failures)
            write_once(args.out, result.model_dump(mode="json"))
        elif args.command == "protocol":
            verdict = protocol_from_paths(list(args.sessions))
            write_once(args.out, verdict)
        elif args.command == "day-plan":
            write_once(
                args.out,
                tuesday_commands(
                    args.session, args.out.parent, allow_degraded=args.allow_degraded
                ),
            )
        elif args.command == "fail":
            record = FailureRecord(
                session=args.session,
                available_at=now_utc(),
                stage=args.stage,
                error_type=args.error_type,
                detail=args.detail,
                source_hash="cli-fail",
                attempt_dir=str(args.out),
            )
            write_failure(args.out, record)
        elif args.command == "registry":
            if args.seed:
                write_registry(args.path, seed_registry())
            else:
                registry_state = load_registry(args.path)
                if args.propose_id:
                    missing_propose = (
                        not args.parent
                        or not args.hypothesis
                        or not args.difference
                        or not args.forward_test
                    )
                    if missing_propose:
                        raise ValueError(
                            "propose requires parent, hypothesis, difference and forward-test"
                        )
                    next_path = args.path.with_name(
                        args.path.stem + "-" + args.propose_id + args.path.suffix
                    )
                    write_registry(
                        next_path,
                        propose(
                            registry_state,
                            version_id=args.propose_id,
                            prompt_name=args.prompt_name,
                            parent_version=args.parent,
                            hypothesis=args.hypothesis,
                            proposed_difference=args.difference,
                            forward_test=args.forward_test,
                        ),
                    )
                elif args.status:
                    next_path = args.path.with_name(
                        args.path.stem + "-" + args.status + args.path.suffix
                    )
                    write_registry(
                        next_path,
                        set_status(registry_state, args.freeze or "", args.status),
                    )
                elif args.freeze:
                    next_path = args.path.with_name(args.path.stem + "-frozen" + args.path.suffix)
                    write_registry(next_path, freeze_active(registry_state, args.freeze, now_utc()))
                else:
                    write_once(
                        args.path.with_name(args.path.stem + "-copy.json"),
                        registry_state.model_dump(mode="json"),
                    )
        elif args.command == "collect-context":
            config = Config.model_validate(_load_json(args.config))
            packet = Packet.model_validate_json(args.packet.read_text()) if args.packet else None
            if args.out.suffix == ".json" and not args.out.is_dir():
                target = args.out
                directory = target.parent
            else:
                directory = args.out
                target = directory / "context.json"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            uw, tradier = feeds(packet.config if packet is not None else config)
            try:
                if packet is not None:
                    write_expanded_context(
                        config=packet.config,
                        session=packet.session,
                        directory=directory,
                        uw=uw,
                        tradier=tradier,
                        news_events=[],
                        flow_events=[],
                        packet=packet,
                        target=target,
                    )
                else:
                    context = collect_context(
                        config=config,
                        session=args.session,
                        uw=uw,
                        tradier=tradier,
                        finnhub=optional_finnhub(),
                        account_id=optional_account_id(),
                        directory=directory,
                    )
                    if not target.exists():
                        write_once(target, context.model_dump(mode="json"))
            finally:
                uw.close()
                tradier.close()
        else:
            packet = Packet.model_validate_json(args.packet.read_text())
            context = Context.model_validate_json(args.context.read_text())
            if args.command == "select":
                active_registry = load_registry(args.registry) if args.registry else None
                select(
                    packet,
                    context,
                    Memory.model_validate_json(args.memory.read_text()),
                    args.out,
                    args.allow_degraded,
                    registry=active_registry,
                )
            else:
                resolve(
                    packet,
                    json.loads(args.decision.read_text()),
                    json.loads(args.evaluation.read_text()),
                    context,
                    args.out,
                )
    except Exception as exc:
        if args.command in {"select", "resolve", "memory", "collect-context"}:
            session = getattr(args, "session", None)
            packet_arg = getattr(args, "packet", None)
            if session is None and packet_arg and Path(packet_arg).is_file():
                session = Packet.model_validate_json(Path(packet_arg).read_text()).session
            if session is not None and args.out:
                out_dir = args.out if args.out.suffix != ".json" else args.out.parent
                out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                write_failure(
                    out_dir,
                    failure_from_exception(
                        session=session,
                        stage=args.command if args.command != "collect-context" else "context",
                        exc=exc,
                        directory=out_dir,
                    ),
                )
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        parser.exit(1, f"{args.command} failed ({detail}); no orders.\n")


if __name__ == "__main__":
    main()
