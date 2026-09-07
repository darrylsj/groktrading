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
    evaluation.pop("eligibility_hash", None)
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
    assert (tmp_path / "select/candidates.json").exists()
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
        for name in ("selector_v2.md", "selector_v3.md", "retrieval_v1.md", "resolver_v1.md")
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


def _seeded_before_open(packet: Packet):
    from groktrading.research.registry import seed_registry

    start, _ = window(packet.session)
    return seed_registry(built_at=start - timedelta(hours=1))


def _abstain_decision(decision: dict[str, Any]) -> Decision:
    body = dict(decision["decision"])
    body["picks"] = []
    body["data_limitations"] = ["fixture shadow abstain; cite-or-abstain"]
    return Decision.model_validate(body)


def test_seeded_registry_keeps_v2_active_and_v3_shadow(sample: Any) -> None:
    from groktrading.research.registry import seed_registry

    packet = sample[0]
    registry = _seeded_before_open(packet)
    assert registry.active_version_id == "selector_v2"
    assert registry.get("selector_v2").status == "accepted"
    assert registry.get("selector_v3").status == "shadow"
    assert registry.get("selector_v3").prompt_name == "selector_v3.md"
    assert (cycle.PROMPTS / "selector_v3.md").is_file()
    name, version = cycle.active_selector_prompt(registry, session=packet.session)
    assert (name, version) == ("selector_v2.md", "selector_v2")
    default_name, default_version = cycle.active_selector_prompt(None)
    assert (default_name, default_version) == ("selector_v2.md", "selector_v2")
    late = seed_registry(built_at=window(packet.session)[0] + timedelta(minutes=1))
    with pytest.raises(ValueError, match="frozen_at"):
        cycle.active_selector_prompt(late, session=packet.session)


def test_selector_v3_prompt_is_judgment_not_gates() -> None:
    text = (cycle.PROMPTS / "selector_v3.md").read_text()
    lowered = text.lower()
    assert "cite" in lowered and "abstain" in lowered
    assert "candidates" in lowered or "shortlist" in lowered
    assert "paper-only" in lowered or "paper only" in lowered
    assert "selection json" in lowered
    for banned in (
        "skip ≥",
        "skip >=",
        "first-print-only",
        "first print only",
        "within n min",
        "gex",
    ):
        assert banned not in lowered


def test_select_without_shadow_flag_does_not_write_v3(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
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

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(
        packet,
        context(packet),
        memory,
        tmp_path / "no-shadow",
        registry=_seeded_before_open(packet),
    )
    assert calls[-1] == "selector_v2.md"
    assert "selector_v3.md" not in calls
    assert selected["prompt_version"] == "selector_v2"
    assert (tmp_path / "no-shadow/decision.json").is_file()
    assert not (tmp_path / "no-shadow" / cycle.SHADOW_V3_ARTIFACT).exists()


def test_select_shadow_v3_writes_artifact_without_swapping_active(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    packet, decision, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    calls: list[str] = []

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        calls.append(name)
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=[], rationale="none")
        if schema is cycle.Selection:
            assert payload["candidates"]
            assert payload["hygiene"]["architecture"] == "gates_then_judgment"
            assert payload["eligibility"]["declared_before_inference"] is True
            body = (
                _abstain_decision(decision)
                if name == "selector_v3.md"
                else Decision.model_validate(decision["decision"])
            )
            return schema(
                decision=body,
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        raise AssertionError(schema)

    registry = _seeded_before_open(packet)
    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(
        packet,
        context(packet),
        memory,
        tmp_path / "shadow",
        registry=registry,
        shadow_version_id="selector_v3",
    )
    assert calls.count("selector_v2.md") == 1
    assert calls.count("selector_v3.md") == 1
    assert selected["prompt_version"] == "selector_v2"
    assert registry.active_version_id == "selector_v2"
    active = json.loads((tmp_path / "shadow/decision.json").read_text())
    shadow = json.loads((tmp_path / "shadow" / cycle.SHADOW_V3_ARTIFACT).read_text())
    compare = json.loads((tmp_path / "shadow" / cycle.SHADOW_V3_COMPARE).read_text())
    assert active["prompt_version"] == "selector_v2"
    assert "role" not in active
    assert shadow["prompt_version"] == "selector_v3"
    assert shadow["role"] == "shadow"
    assert shadow["status"] == "recorded"
    assert shadow["active_prompt_version"] == "selector_v2"
    assert shadow["decision"]["picks"] == []
    assert compare["active_prompt_version"] == "selector_v2"
    assert compare["shadow_prompt_version"] == "selector_v3"
    assert compare["shadow_abstain"] is True
    assert compare["abstain_baseline"]["net_usd"] == 0.0
    assert "Do not promote" in compare["abstain_baseline"]["note"]


def test_select_shadow_v3_still_requires_hygiene_shortlist(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    packet, decision, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    bad = json.loads(json.dumps(decision))
    bad["decision"]["picks"][0]["option_symbol"] = "AAPL260911C00999000"
    bad["decision"]["picks"][0]["max_entry_price"] = 1.0

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=[], rationale="none")
        if schema is cycle.Selection:
            body = (
                Decision.model_validate(bad["decision"])
                if name == "selector_v3.md"
                else Decision.model_validate(decision["decision"])
            )
            return schema(
                decision=body,
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        raise AssertionError(schema)

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(
        packet,
        context(packet),
        memory,
        tmp_path / "shadow-hygiene",
        registry=_seeded_before_open(packet),
        shadow_version_id="selector_v3",
    )
    assert selected["prompt_version"] == "selector_v2"
    assert (tmp_path / "shadow-hygiene/decision.json").is_file()
    shadow = json.loads((tmp_path / "shadow-hygiene" / cycle.SHADOW_V3_ARTIFACT).read_text())
    assert shadow["status"] == "failed"
    assert "contract" in shadow["detail"]
    compare = json.loads((tmp_path / "shadow-hygiene" / cycle.SHADOW_V3_COMPARE).read_text())
    assert compare["shadow_status"] == "failed"
    assert compare["shadow_abstain"] is None


def test_select_shadow_v3_enforces_hash_and_requires_registry(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from groktrading.research.registry import PromptRegistry, PromptVersion

    packet, _, _ = sample
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    seeded = _seeded_before_open(packet)
    frozen_at = start - timedelta(hours=1)
    bad = PromptVersion(
        version_id="selector_v3",
        prompt_name="selector_v3.md",
        prompt_hash="0" * 64,
        parent_version="selector_v2",
        supporting_sessions=[],
        hypothesis="Incorrect recorded hash must not be used for shadow inference",
        proposed_difference="Hash does not match selector_v3.md",
        forward_test="Must raise; no fallback",
        status="shadow",
        created_at=frozen_at,
        frozen_at=frozen_at,
    )
    versions = [item for item in seeded.versions if item.version_id != "selector_v3"]
    registry = PromptRegistry(versions=[*versions, bad], active_version_id="selector_v2")
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)

    def fail_cli(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("inference must not run on a hash mismatch")

    monkeypatch.setattr(cycle, "cli_json", fail_cli)
    with pytest.raises(ValueError, match="hash mismatch"):
        cycle.select(
            packet,
            context(packet),
            memory,
            tmp_path / "shadow-hash",
            registry=registry,
            shadow_version_id="selector_v3",
        )
    assert not (tmp_path / "shadow-hash/decision.json").exists()
    with pytest.raises(ValueError, match="prompt registry"):
        cycle.select(
            packet,
            context(packet),
            memory,
            tmp_path / "shadow-noreg",
            shadow_version_id="selector_v3",
        )
    unfrozen = PromptVersion(
        version_id="selector_v3",
        prompt_name="selector_v3.md",
        prompt_hash=seeded.get("selector_v3").prompt_hash,
        parent_version="selector_v2",
        supporting_sessions=[],
        hypothesis="Unfrozen shadow must not be used for inference",
        proposed_difference="frozen_at missing",
        forward_test="Must raise; no fallback",
        status="shadow",
        created_at=frozen_at,
        frozen_at=None,
    )
    thawed = PromptRegistry(versions=[*versions, unfrozen], active_version_id="selector_v2")
    with pytest.raises(ValueError, match="not frozen"):
        cycle.select(
            packet,
            context(packet),
            memory,
            tmp_path / "shadow-unfrozen",
            registry=thawed,
            shadow_version_id="selector_v3",
        )
