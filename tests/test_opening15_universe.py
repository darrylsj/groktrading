"""Eligibility manifest and expanded decision-to-outcome contract."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from groktrading.research import cycle
from groktrading.research.cli import demo
from groktrading.research.evaluation import evaluate, evaluate_core, original_evaluation_fields
from groktrading.research.hygiene import build_shortlist
from groktrading.research.opening15 import (
    EXPANDED_SELECT_EXPERIMENT_ID,
    PACKET_BASELINE_EXPERIMENT_ID,
    Config,
    Decision,
    Packet,
    digest,
    window,
)
from groktrading.research.protocol import decide_protocol
from groktrading.research.universe import (
    UNIVERSE_PACKET,
    UNIVERSE_SHORTLIST,
    apply_eligibility,
    build_shortlist_eligibility,
    packet_eligibility,
    resolve_eligibility,
    verify_eligibility,
)
from test_opening15_hygiene import _chain_evidence, _context
from test_research_cycle import resolution


@pytest.fixture
def sample(tmp_path: Path) -> tuple[Packet, dict[str, Any]]:
    cfg = Config.model_validate_json(Path("research/opening15.example.json").read_text())
    demo(tmp_path / "demo", cfg)
    packet = Packet.model_validate_json((tmp_path / "demo/packet.json").read_text())
    decision = json.loads((tmp_path / "demo/decision.json").read_text())
    return packet, decision


def test_packet_eligibility_hash_is_stable(sample: Any) -> None:
    packet, _ = sample
    first = packet_eligibility(packet)
    second = packet_eligibility(packet)
    verify_eligibility(first)
    assert first["manifest_hash"] == second["manifest_hash"]
    assert first["universe"] == UNIVERSE_PACKET
    assert first["shortlist_only_contracts"] == []
    tampered = dict(first)
    tampered["contracts"] = [*first["contracts"], "FAKE260911C00100000"]
    with pytest.raises(ValueError, match="eligibility manifest hash"):
        verify_eligibility(tampered)


def test_tuesday_evaluate_emits_identity_without_changing_core_keys(sample: Any) -> None:
    packet, record = sample
    core = evaluate_core(packet, record, [])
    full = evaluate(packet, record, [])
    assert original_evaluation_fields(full) == core
    assert full["experiment_id"] == PACKET_BASELINE_EXPERIMENT_ID
    assert full["arm"]["universe"] == UNIVERSE_PACKET
    assert full["requested_model"]
    assert full["recommend_backend"]
    assert full["prompt_version"]
    assert full["observation_coverage"]["selected_observation_inadequate"] == 0
    assert next(row["status"] for row in full["rows"] if row["group"] == "selected") == (
        "not_filled"
    )


def test_expanded_shortlist_only_contract_evaluates_and_resolves(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    packet, decision = sample
    packet.synthetic = False
    symbol = packet.config.symbols[0]
    chain_only = f"{symbol}260918C00100000"
    extra = _chain_evidence(
        packet,
        symbol=symbol,
        contract=chain_only,
        expiration="2026-09-18",
        bid=0.90,
        ask=1.00,
        volume=20,
        open_interest=40,
    )
    ctx = _context(packet, [extra])
    shortlist = build_shortlist(packet, ctx.records)
    assert chain_only in {row["contract"] for row in shortlist["candidates"]}
    eligibility = build_shortlist_eligibility(packet, ctx.records, shortlist)
    assert chain_only in eligibility["shortlist_only_contracts"]
    body = json.loads(json.dumps(decision["decision"]))
    body["picks"][0]["option_symbol"] = chain_only
    body["picks"][0]["evidence_ids"] = [extra.evidence_id]
    parsed = Decision.model_validate(body)
    apply_eligibility(parsed, packet, eligibility)
    with pytest.raises(ValueError, match="contract"):
        parsed.validate_evidence(packet)

    start, end = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        if schema is cycle.RetrievalRequest:
            assert payload["eligibility"]["declared_before_inference"] is True
            assert chain_only in payload["eligibility"]["contracts"]
            return schema(evidence_ids=[], rationale="none")
        if schema is cycle.Selection:
            return schema(
                decision=parsed,
                context_citations=[extra.evidence_id],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        return resolution(packet, {"decision": parsed.model_dump(mode="json")})

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    selected = cycle.select(packet, ctx, memory, tmp_path / "select")
    assert selected["experiment_id"] == EXPANDED_SELECT_EXPERIMENT_ID
    assert selected["eligibility_hash"] == eligibility["manifest_hash"]
    assert (tmp_path / "select/eligibility.json").is_file()

    report = evaluate(packet, selected, [])
    row = next(r for r in report["rows"] if r["option_symbol"] == chain_only)
    assert row["group"] == "selected"
    assert row["status"] == "observation_inadequate"
    assert report["selected_net_before_api_and_infra_usd"] is None
    assert report["observation_coverage"]["selected_observation_inadequate"] == 1
    assert report["arm"]["universe"] == UNIVERSE_SHORTLIST
    assert report["experiment_id"] == EXPANDED_SELECT_EXPERIMENT_ID

    from groktrading.research.opening15 import stamp

    at = stamp(selected["received_at"])
    observations = [
        {
            "received_at": (at + timedelta(seconds=2)).isoformat(),
            "source": "tradier_production",
            "quote": {
                "symbol": chain_only,
                "type": "option",
                "bid": 0.95,
                "ask": 1.0,
                "bidsize": 1,
                "asksize": 1,
                "bid_date": (at + timedelta(seconds=2)).timestamp() * 1000,
                "ask_date": (at + timedelta(seconds=2)).timestamp() * 1000,
            },
        },
        {
            "received_at": (end + timedelta(hours=6, minutes=10)).isoformat(),
            "source": "tradier_production",
            "quote": {
                "symbol": chain_only,
                "type": "option",
                "bid": 1.10,
                "ask": 1.15,
                "bidsize": 1,
                "asksize": 1,
                "bid_date": (end + timedelta(hours=6, minutes=10)).timestamp() * 1000,
                "ask_date": (end + timedelta(hours=6, minutes=10)).timestamp() * 1000,
            },
        },
    ]
    scored = evaluate(packet, selected, observations)
    closed = next(r for r in scored["rows"] if r["option_symbol"] == chain_only)
    assert closed["status"] == "closed_simulation"
    assert scored["selected_net_before_api_and_infra_usd"] == pytest.approx(6.7)

    monkeypatch.setattr(cycle, "now_utc", lambda: end + timedelta(hours=7))
    daily = cycle.resolve(packet, selected, scored, ctx, tmp_path / "resolve")
    assert daily.decision_hash == digest(selected)
    assert (tmp_path / "resolve/daily-resolution.json").is_file()


def test_protocol_refuses_to_mix_evaluated_arms(sample: Any) -> None:
    packet, record = sample
    tue = evaluate(packet, record, [])
    tue = dict(tue)
    tue["synthetic"] = False
    expanded = dict(tue)
    expanded["session"] = "2026-09-09"
    expanded["packet_hash"] = "other-hash"
    expanded["experiment_id"] = EXPANDED_SELECT_EXPERIMENT_ID
    expanded["prompt_version"] = "selector_v2"
    expanded["arm"] = dict(tue["arm"])
    expanded["arm"]["experiment_id"] = EXPANDED_SELECT_EXPERIMENT_ID
    expanded["arm"]["prompt_version"] = "selector_v2"
    expanded["arm"]["universe"] = UNIVERSE_SHORTLIST
    copies = []
    for i in range(4):
        row = dict(tue)
        row["session"] = f"2026-09-0{i + 1}"
        row["packet_hash"] = f"hash-{i}"
        copies.append(row)
    copies.append(expanded)
    result = decide_protocol(copies)
    assert result["verdict"] == "rejected"


def test_selector_prompts_declare_eligibility_universe() -> None:
    v2 = (cycle.PROMPTS / "selector_v2.md").read_text()
    v3 = (cycle.PROMPTS / "selector_v3.md").read_text()
    assert "eligibility" in v2
    assert "opening_packet" in v2
    assert "hygiene_shortlist" in v2
    assert "eligibility" in v3
    assert "cite" in v3.lower() and "abstain" in v3.lower()


def test_resolve_eligibility_requires_manifest_when_hash_present(sample: Any) -> None:
    packet, record = sample
    record = dict(record)
    record["eligibility_hash"] = "abc"
    with pytest.raises(ValueError, match="without eligibility manifest"):
        resolve_eligibility(packet, record)
