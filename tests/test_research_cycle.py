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
