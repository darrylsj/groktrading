from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from groktrading.research import cycle
from groktrading.research.cli import demo
from groktrading.research.opening15 import Config, Decision, Packet, digest, window


@pytest.fixture
def sample(tmp_path: Path) -> tuple[Packet, dict[str, Any], dict[str, Any]]:
    cfg = Config.model_validate_json(Path("research/opening15.example.json").read_text())
    demo(tmp_path / "demo", cfg)
    packet = Packet.model_validate_json((tmp_path / "demo/packet.json").read_text())
    packet.synthetic = False  # fixture only; never a measured result
    decision = json.loads((tmp_path / "demo/decision.json").read_text())
    evaluation = json.loads((tmp_path / "demo/evaluation.json").read_text())
    decision.update(packet_hash=digest(packet.model_dump(mode="json")), synthetic=False)
    evaluation.update(
        packet_hash=decision["packet_hash"], decision_hash=digest(decision), synthetic=False
    )
    return packet, decision, evaluation


def context(packet: Packet) -> cycle.Context:
    end = window(packet.session)[1]
    return cycle.Context(
        session=packet.session,
        frozen_at=end,
        records=[
            cycle.Evidence(
                evidence_id=c,
                category=c,  # type: ignore[arg-type]
                symbols=[],
                source="synthetic",
                source_uri="fixture",
                as_of=end,
                received_at=end,
                summary="Synthetic test evidence",
                payload={"value": 1},
            )
            for c in sorted(cycle.CATEGORIES)
        ],
        coverage=[
            cycle.Coverage(category=c, status="available", detail="fixture")  # type: ignore[arg-type]
            for c in sorted(cycle.CATEGORIES)
        ],
    )


def resolution(packet: Packet, decision: dict[str, Any]) -> cycle.Resolution:
    return cycle.Resolution(
        summary="Test summary, not measured findings",
        reviews=[
            cycle.Review(
                option_symbol=p["option_symbol"],
                diagnosis="insufficient_evidence",
                explanation="Price outcome alone cannot establish cause",
                evidence_ids=[f"outcome:{p['option_symbol']}"],
            )
            for p in decision["decision"]["picks"]
        ],
        skipped_stocks=[
            cycle.StockReflection(symbol=s, assessment="Insufficient evidence")
            for s in packet.config.symbols
        ],
        lessons=[],
        proposed_prompt_change="",
        forward_test="",
    )


def test_context_chronology_and_missing_manifest(sample: Any) -> None:
    packet, _, _ = sample
    ctx = context(packet)
    ctx.for_selection(packet)
    ctx.records[0].received_at += timedelta(seconds=1)
    with pytest.raises(ValueError, match="09:45"):
        ctx.for_selection(packet)
    data = context(packet).model_dump()
    data["coverage"].pop()
    with pytest.raises(ValueError, match="every context"):
        cycle.Context.model_validate(data)
    data = context(packet).model_dump()
    data["records"][0]["payload"] = {"nested": {"account_number": "fixture"}}
    with pytest.raises(ValueError, match="identifier"):
        cycle.Context.model_validate(data)


def test_retrieval_rejects_unknown_ids(sample: Any) -> None:
    ctx = context(sample[0])
    with pytest.raises(ValueError, match="unknown"):
        ctx.retrieve(["invented"])
    with pytest.raises(ValueError, match="duplicate"):
        ctx.retrieve(["macro", "macro"])


def test_memory_filters_future_and_caps_days(sample: Any) -> None:
    packet, decision, _ = sample
    records = [
        cycle.DailyRecord(
            session=date(2026, 8, d),
            available_at=window(date(2026, 8, d))[1],
            source_hash="fixture",
            decision_hash="fixture",
            evaluation_hash="fixture",
            status="resolved",
            resolution=resolution(packet, decision),
        )
        for d in range(1, 9)
    ]
    target = date(2026, 8, 8)
    memory = cycle.build_memory(records, target, window(target)[0] - timedelta(minutes=10))
    assert len(memory.days) == 5
    assert memory.days[0].session == date(2026, 8, 7)
    assert date(2026, 8, 8) in memory.omitted_sessions
    with pytest.raises(ValueError, match="multiple resolutions"):
        cycle.build_memory(records + [records[0]], target, memory.built_at)
    with pytest.raises(ValueError, match="before"):
        cycle.build_memory([], target, window(target)[0])


def test_selection_and_resolver_roundtrip(sample: Any, tmp_path: Path, monkeypatch: Any) -> None:
    packet, decision, evaluation = sample
    start, end = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    calls: list[str] = []

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        calls.append(name)
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=["macro"], rationale="inspect macro")
        if schema is cycle.Selection:
            assert payload["retrieved"][0]["evidence_id"] == "macro"
            return schema(
                decision=Decision.model_validate(decision["decision"]),
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        return resolution(packet, decision)

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(packet, context(packet), memory, tmp_path / "select")
    assert calls == ["retrieval_v1.md", "retrieval_v1.md", "selector_v2.md"]
    assert (tmp_path / "select/packet.json").exists()
    monkeypatch.setattr(cycle, "now_utc", lambda: end + timedelta(hours=7))
    evaluation["decision_hash"] = digest(selected)
    daily = cycle.resolve(packet, selected, evaluation, context(packet), tmp_path / "resolve")
    assert daily.decision_hash == digest(selected)
    assert (tmp_path / "resolve/daily-resolution.json").exists()
    evaluation["packet_hash"] = "wrong"
    with pytest.raises(ValueError, match="hash mismatch"):
        cycle.resolve(packet, selected, evaluation, context(packet), tmp_path / "bad")


def test_schema_uses_typed_stock_reflections() -> None:
    schema = cycle.Resolution.model_json_schema()
    assert schema["properties"]["skipped_stocks"]["type"] == "array"
    assert all(
        (cycle.PROMPTS / name).is_file()
        for name in ("selector_v2.md", "retrieval_v1.md", "resolver_v1.md")
    )


def test_cli_boundary_through_evaluation_and_next_day_memory(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """Exercise real orchestration/schema/archive code; only external Codex is a fixture."""
    import subprocess

    from groktrading.research.evaluation import evaluate
    from groktrading.research.opening15 import canonical

    packet, fixture, _ = sample
    start, end = window(packet.session)
    stages: list[str] = []
    clock = [packet.knowledge_cutoff]
    monkeypatch.setattr(cycle, "now_utc", lambda: clock[0])
    monkeypatch.setenv("UW_API_TOKEN", "synthetic-test-credential")
    monkeypatch.setenv("TRADIER_ACCESS_TOKEN", "synthetic-test-credential")

    def runner(argv: Any, **kwargs: Any) -> Any:
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, "codex-cli 0.153.0", "")
        if argv[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
        assert "--ignore-rules" not in argv
        assert "UW_API_TOKEN" not in kwargs["env"]
        assert "TRADIER_ACCESS_TOKEN" not in kwargs["env"]
        assert "synthetic-test-credential" not in kwargs["input_text"]
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        output = Path(argv[argv.index("--output-last-message") + 1])
        assert schema_path.is_absolute() and output.is_absolute()
        schema = json.loads(schema_path.read_text())
        title = schema["title"]
        stages.append(title)
        if title == "RetrievalRequest":
            result: Any = {"evidence_ids": [], "rationale": "summaries sufficient for fixture"}
        elif title == "Selection":
            result = {
                "decision": fixture["decision"],
                "context_citations": ["macro", "portfolio"],
                "portfolio_assessment": "Synthetic standalone paper selection",
                "memory_use": "Empty first-day memory",
            }
        else:
            result = resolution(packet, fixture).model_dump(mode="json")
        output.write_text(canonical(result))
        return subprocess.CompletedProcess(
            argv, 0, canonical({"type": "turn.completed", "usage": {"input_tokens": 1}}), ""
        )

    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    selected = cycle.select(packet, context(packet), memory, tmp_path / "full", runner=runner)
    contract = selected["decision"]["picks"][0]["option_symbol"]
    observations = []
    for at, bid, ask in (
        (clock[0] + timedelta(seconds=1), 0.95, 1.0),
        (end + timedelta(hours=6, minutes=10), 1.10, 1.15),
    ):
        observations.append(
            {
                "received_at": at.isoformat(),
                "source": "tradier_production",  # simulated provider response
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
    assert evaluation["decision_hash"] == digest(selected)
    assert evaluation["selected_net_before_api_and_infra_usd"] == pytest.approx(6.7)
    clock[0] = end + timedelta(hours=7)
    daily = cycle.resolve(
        packet, selected, evaluation, context(packet), tmp_path / "after", runner=runner
    )
    tomorrow = packet.session + timedelta(days=1)
    next_memory = cycle.build_memory([daily], tomorrow, window(tomorrow)[0] - timedelta(minutes=5))
    assert next_memory.days[0].decision_hash == digest(selected)
    assert stages == ["RetrievalRequest", "Selection", "Resolution"]
    assert (tmp_path / "full/selection/response.json").is_file()
    assert (tmp_path / "after/daily-resolution.json").is_file()


@pytest.mark.parametrize("failure", ["tool", "invalid_json", "exit"])
def test_cli_stage_failure_never_creates_decision(
    sample: Any, tmp_path: Path, monkeypatch: Any, failure: str
) -> None:
    import subprocess

    packet = sample[0]
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)

    def runner(argv: Any, **kwargs: Any) -> Any:
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, "codex-cli 0.153.0", "")
        if argv[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text(
            "{" if failure == "invalid_json" else '{"evidence_ids":[],"rationale":"fixture"}'
        )
        events = '{"item":{"type":"web_search"}}' if failure == "tool" else ""
        return subprocess.CompletedProcess(argv, int(failure == "exit"), events, "")

    memory = cycle.build_memory(
        [], packet.session, window(packet.session)[0] - timedelta(minutes=5)
    )
    with pytest.raises(ValueError):
        cycle.select(packet, context(packet), memory, tmp_path / "failed", runner=runner)
    assert not (tmp_path / "failed/decision.json").exists()
    assert (tmp_path / "failed/retrieval-0/response.json").is_file()


def test_select_uses_active_registry_prompt(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from groktrading.research.registry import PromptRegistry, PromptVersion, seed_registry

    packet, decision, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    calls: list[str] = []

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        calls.append(name)
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=[], rationale="none")
        if schema is cycle.Selection:
            return schema(
                decision=Decision.model_validate(decision["decision"]),
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        raise AssertionError(schema)

    seeded = seed_registry()
    frozen_at = start - timedelta(hours=1)
    alt = PromptVersion(
        version_id="selector_alt",
        prompt_name="retrieval_v1.md",
        prompt_hash=seeded.get("retrieval_v1").prompt_hash,
        parent_version="selector_v2",
        supporting_sessions=[],
        hypothesis="Prove activating a version changes the selector prompt file",
        proposed_difference="Test double; not a production arm",
        forward_test="Equal evidence/compute",
        status="accepted",
        created_at=frozen_at,
        frozen_at=frozen_at,
    )
    registry = PromptRegistry(
        versions=[*seeded.versions, alt], active_version_id="selector_alt"
    )
    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(
        packet, context(packet), memory, tmp_path / "select-alt", registry=registry
    )
    assert calls[-1] == "retrieval_v1.md"
    assert selected["prompt_version"] == "selector_alt"


def test_select_rejects_wrong_hash_registry_prompt(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from groktrading.research.registry import PromptRegistry, PromptVersion, seed_registry

    packet, _, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    seeded = seed_registry()
    frozen_at = start - timedelta(hours=1)
    bad = PromptVersion(
        version_id="selector_bad_hash",
        prompt_name="selector_v2.md",
        prompt_hash="0" * 64,
        parent_version="selector_v2",
        supporting_sessions=[],
        hypothesis="Incorrect recorded hash must not be used for inference",
        proposed_difference="Hash does not match selector_v2.md",
        forward_test="Must raise; no fallback",
        status="accepted",
        created_at=frozen_at,
        frozen_at=frozen_at,
    )
    registry = PromptRegistry(
        versions=[*seeded.versions, bad], active_version_id="selector_bad_hash"
    )
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)

    def fail_cli(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("inference must not run on a hash mismatch")

    monkeypatch.setattr(cycle, "cli_json", fail_cli)
    with pytest.raises(ValueError, match="hash mismatch"):
        cycle.select(packet, context(packet), memory, tmp_path / "bad-hash", registry=registry)
    assert not (tmp_path / "bad-hash/decision.json").exists()


def test_select_rejects_rejected_registry_prompt(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from groktrading.research.registry import PromptRegistry, PromptVersion, seed_registry

    packet, _, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    seeded = seed_registry()
    frozen_at = start - timedelta(hours=1)
    rejected = PromptVersion(
        version_id="selector_rejected",
        prompt_name="selector_v2.md",
        prompt_hash=seeded.get("selector_v2").prompt_hash,
        parent_version="selector_v2",
        supporting_sessions=[],
        hypothesis="Rejected status must not be used for inference",
        proposed_difference="Status rejected after a recorded review",
        forward_test="Must raise; no fallback to rejected version",
        status="rejected",
        created_at=frozen_at,
        frozen_at=frozen_at,
    )
    registry = PromptRegistry(
        versions=[*seeded.versions, rejected], active_version_id="selector_rejected"
    )
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)

    def fail_cli(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("inference must not run on a rejected prompt")

    monkeypatch.setattr(cycle, "cli_json", fail_cli)
    with pytest.raises(ValueError, match="not permitted"):
        cycle.select(
            packet, context(packet), memory, tmp_path / "rejected-prompt", registry=registry
        )
    assert not (tmp_path / "rejected-prompt/decision.json").exists()


def test_memory_includes_failed_session_records(sample: Any, tmp_path: Path) -> None:
    packet, decision, _ = sample
    daily = cycle.DailyRecord(
        session=date(2026, 8, 7),
        available_at=window(date(2026, 8, 7))[1],
        source_hash="fixture",
        decision_hash="fixture",
        evaluation_hash="fixture",
        status="resolved",
        resolution=resolution(packet, decision),
    )
    failed = cycle.FailureRecord(
        session=date(2026, 8, 6),
        available_at=window(date(2026, 8, 6))[1],
        stage="select",
        error_type="ValueError",
        detail="CLI stage failed; preserve attempt, no retry",
        source_hash="fixture-fail",
        attempt_dir=str(tmp_path / "failed-day"),
    )
    path = cycle.write_failure(tmp_path / "failed-day", failed)
    loaded = cycle.load_session_record(path)
    assert isinstance(loaded, cycle.FailureRecord)
    target = date(2026, 8, 8)
    memory = cycle.build_memory(
        [daily],
        target,
        window(target)[0] - timedelta(minutes=10),
        failures=[failed],
    )
    assert memory.failures[0].session == date(2026, 8, 6)
    assert memory.brief()["failures"][0]["stage"] == "select"
    assert memory.brief()["failures"][0]["status"] == "failed"


def test_failure_record_has_no_decision_or_pnl(sample: Any, tmp_path: Path) -> None:
    packet = sample[0]
    record = cycle.failure_from_exception(
        session=packet.session,
        stage="select",
        exc=ValueError("CLI stage failed; preserve attempt, no retry"),
        directory=tmp_path / "ledger",
    )
    path = cycle.write_failure(tmp_path / "ledger", record)
    loaded = cycle.FailureRecord.model_validate_json(path.read_text())
    assert loaded.status == "failed"
    assert loaded.decision_hash is None
    assert loaded.evaluation_hash is None
    dumped = loaded.model_dump()
    assert not any(key in dumped for key in ("pnl", "net", "profit"))
    with pytest.raises(ValueError, match="pre-decision"):
        cycle.FailureRecord(
            session=packet.session,
            available_at=packet.knowledge_cutoff,
            stage="select",
            error_type="ValueError",
            detail="should not attach a decision",
            source_hash="fixture",
            attempt_dir=str(tmp_path),
            decision_hash="not-a-real-decision",
        )
