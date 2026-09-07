"""End-to-end expanded daily command sequence with fixtures. No live orders."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from groktrading.research import cycle, cycle_cli
from groktrading.research.cli import demo
from groktrading.research.evaluation import evaluate
from groktrading.research.opening15 import Config, Decision, Packet, digest, window
from groktrading.research.registry import seed_registry, write_registry
from test_research_collectors import _feeds
from test_research_cycle import context, resolution


def test_day_plan_sequence_creates_outcome_context_and_loads_failures(
    tmp_path: Path, monkeypatch: Any
) -> None:
    cfg = Config.model_validate_json(Path("research/opening15.example.json").read_text())
    demo(tmp_path / "demo", cfg)
    raw = json.loads((tmp_path / "demo/packet.json").read_text())
    raw["synthetic"] = False
    raw["config"]["recommend_backend"] = "codex_cli"
    for event in raw["events"]:
        event["source"] = "tradier_production" if event["kind"] == "stock_quote" else "uw"
    packet = Packet.model_validate(raw)
    fixture = json.loads((tmp_path / "demo/decision.json").read_text())
    fixture.update(packet_hash=digest(packet.model_dump(mode="json")), synthetic=False)
    start, end = window(packet.session)
    root = tmp_path / "2026-09-08"
    root.mkdir()
    (root / "packet.json").write_text(json.dumps(packet.model_dump(mode="json")))

    monkeypatch.setattr("sys.argv", [
        "cycle_cli",
        "day-plan",
        "--session",
        "2026-09-08",
        "--out",
        str(root / "day-plan.json"),
    ])
    cycle_cli.main()
    plan = json.loads((root / "day-plan.json").read_text())
    expanded = " ".join(plan["expanded"])
    assert "outcome-context.json" in expanded and "collect-context" in expanded
    expected_run = "research.cli run --session 2026-09-08 --output " + root.as_posix()
    assert plan["baseline"][-1].endswith(expected_run)

    write_registry(root / "prompt-registry.json", seed_registry())
    ctx = context(packet)
    (root / "context.json").write_text(json.dumps(ctx.model_dump(mode="json")))

    monkeypatch.setattr(cycle, "now_utc", lambda: start - timedelta(minutes=10))
    monkeypatch.setattr(
        "sys.argv",
        ["cycle_cli", "memory", "--session", "2026-09-08", "--out", str(root / "memory.json")],
    )
    cycle_cli.main()

    failed_dir = root / "failed-select"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "fail",
            "--session",
            "2026-09-05",
            "--stage",
            "select",
            "--detail",
            "prior paper day failed closed",
            "--out",
            str(failed_dir),
        ],
    )
    cycle_cli.main()

    calls: list[str] = []

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        calls.append(name)
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=["macro"], rationale="inspect macro")
        if schema is cycle.Selection:
            return schema(
                decision=Decision.model_validate(fixture["decision"]),
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="Includes failed prior day",
            )
        return resolution(packet, fixture)

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "select",
            "--packet",
            str(root / "packet.json"),
            "--context",
            str(root / "context.json"),
            "--memory",
            str(root / "memory.json"),
            "--registry",
            str(root / "prompt-registry.json"),
            "--out",
            str(root / "selection"),
        ],
    )
    cycle_cli.main()
    assert calls[-1] == "selector_v2.md"
    selected = json.loads((root / "selection/decision.json").read_text())
    assert selected["prompt_version"] == "selector_v2"

    contract = selected["decision"]["picks"][0]["option_symbol"]
    observations = []
    for at, bid, ask in (
        (packet.knowledge_cutoff + timedelta(seconds=1), 0.95, 1.0),
        (end + timedelta(hours=6, minutes=10), 1.10, 1.15),
    ):
        observations.append(
            {
                "received_at": at.isoformat(),
                "source": "tradier_production",
                "quote": {
                    "symbol": contract,
                    "type": "option",
                    "bid": bid,
                    "ask": ask,
                    "bidsize": 1,
                    "asksize": 1,
                    "bid_date": at.timestamp() * 1000,
                    "ask_date": at.timestamp() * 1000,
                },
            }
        )
    evaluation = evaluate(packet, selected, observations)
    assert "baselines" in evaluation
    (root / "selection/evaluation.json").write_text(json.dumps(evaluation))

    uw, tradier, finnhub = _feeds()
    monkeypatch.setattr(cycle_cli, "feeds", lambda _cfg: (uw, tradier))
    monkeypatch.setattr(
        "groktrading.research.collectors.optional_finnhub", lambda: finnhub
    )
    monkeypatch.setattr(
        "groktrading.research.collectors.optional_account_id", lambda: "RESEARCH1"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "collect-context",
            "--session",
            "2026-09-08",
            "--packet",
            str(root / "packet.json"),
            "--out",
            str(root / "outcome-context.json"),
        ],
    )
    cycle_cli.main()
    assert (root / "outcome-context.json").is_file()
    from groktrading.research.cycle import Context

    Context.model_validate_json((root / "outcome-context.json").read_text())

    monkeypatch.setattr(cycle, "now_utc", lambda: end + timedelta(hours=7))
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "resolve",
            "--packet",
            str(root / "selection/packet.json"),
            "--decision",
            str(root / "selection/decision.json"),
            "--evaluation",
            str(root / "selection/evaluation.json"),
            "--context",
            str(root / "outcome-context.json"),
            "--out",
            str(root / "resolution"),
        ],
    )
    cycle_cli.main()
    assert (root / "resolution/daily-resolution.json").is_file()

    tomorrow = packet.session + timedelta(days=1)
    built = window(tomorrow)[0] - timedelta(minutes=10)
    monkeypatch.setattr(cycle, "now_utc", lambda: built)
    monkeypatch.setattr("groktrading.research.cycle_cli.now_utc", lambda: built)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cycle_cli",
            "memory",
            "--session",
            tomorrow.isoformat(),
            "--records",
            str(root / "resolution/daily-resolution.json"),
            str(failed_dir / "failure-record.json"),
            "--out",
            str(tmp_path / str(tomorrow) / "memory.json"),
        ],
    )
    cycle_cli.main()
    nxt = json.loads((tmp_path / str(tomorrow) / "memory.json").read_text())
    assert nxt["days"][0]["session"] == "2026-09-08"
    assert nxt["failures"][0]["session"] == "2026-09-05"
    assert nxt["failures"][0]["status"] == "failed"
    uw.close()
    tradier.close()
    finnhub.close()


def test_tuesday_launch_command_is_clean_baseline() -> None:
    plan = cycle_cli.tuesday_commands(
        date(2026, 9, 8), Path("research-runs/2026-09-08"), allow_degraded=False
    )
    assert plan["baseline"][-1] == (
        "python -m groktrading.research.cli run --session 2026-09-08 "
        "--output research-runs/2026-09-08"
    )
    assert "--allow-degraded" not in " ".join(plan["baseline"])
    assert "Do not launch with --allow-degraded" in plan["note"]
