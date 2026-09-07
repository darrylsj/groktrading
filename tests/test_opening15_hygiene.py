"""Universe hygiene shortlist: pre-LLM gates on the expanded select path only."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from groktrading.research import cycle
from groktrading.research.cli import demo
from groktrading.research.hygiene import (
    DEFAULT_PLANNING_EQUITY_USD,
    DEFAULT_PREMIUM_BUDGET_PCT,
    HygieneSettings,
    apply_gates,
    as_number,
    build_shortlist,
    dte_bucket,
    parse_occ,
    resolve_budget,
)
from groktrading.research.opening15 import Config, Decision, Packet, request_body, window


@pytest.fixture
def sample(tmp_path: Path) -> tuple[Packet, dict[str, Any]]:
    cfg = Config.model_validate_json(Path("research/opening15.example.json").read_text())
    demo(tmp_path / "demo", cfg)
    packet = Packet.model_validate_json((tmp_path / "demo/packet.json").read_text())
    decision = json.loads((tmp_path / "demo/decision.json").read_text())
    return packet, decision


def _context(packet: Packet, extra: list[cycle.Evidence] | None = None) -> cycle.Context:
    end = window(packet.session)[1]
    records = [
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
    ]
    if extra:
        by_id = {r.evidence_id: r for r in records}
        for item in extra:
            by_id[item.evidence_id] = item
        records = list(by_id.values())
    return cycle.Context(
        session=packet.session,
        frozen_at=end,
        records=records,
        coverage=[
            cycle.Coverage(category=c, status="available", detail="fixture")  # type: ignore[arg-type]
            for c in sorted(cycle.CATEGORIES)
        ],
    )


def _chain_evidence(
    packet: Packet,
    *,
    symbol: str,
    contract: str,
    expiration: str,
    bid: Any,
    ask: Any,
    volume: Any = None,
    open_interest: Any = None,
) -> cycle.Evidence:
    end = window(packet.session)[1]
    return cycle.Evidence(
        evidence_id=f"chain:{symbol}:{expiration}:{contract}",
        category="option_chain",
        symbols=[symbol],
        source="tradier_production",
        source_uri="fixture",
        as_of=end,
        received_at=end,
        summary=f"{symbol} {expiration} chain fixture",
        payload={
            "expiration": expiration,
            "contracts": [
                {
                    "symbol": contract,
                    "option_type": "call",
                    "strike": 100,
                    "expiration_date": expiration,
                    "bid": bid,
                    "ask": ask,
                    "volume": volume,
                    "prior_session_open_interest": open_interest,
                }
            ],
        },
    )


def _portfolio(packet: Packet, *, equity: Any = None, cash: Any = None) -> cycle.Evidence:
    end = window(packet.session)[1]
    return cycle.Evidence(
        evidence_id="portfolio:acct-fixture",
        category="portfolio",
        symbols=[],
        source="tradier_production_interim_portfolio",
        source_uri="fixture",
        as_of=end,
        received_at=end,
        summary="Tradier-backed interim portfolio fixture",
        payload={"account_alias": "acct-fixture", "cash": cash, "equity": equity},
    )


def test_example_config_documents_budget_derived_premium() -> None:
    cfg = Config.model_validate_json(Path("research/opening15.example.json").read_text())
    assert cfg.hygiene.planning_equity_usd == DEFAULT_PLANNING_EQUITY_USD
    assert cfg.hygiene.premium_budget_pct == DEFAULT_PREMIUM_BUDGET_PCT
    assert cfg.hygiene.max_debit_usd == pytest.approx(200.0)
    assert cfg.hygiene.dte_min == 0
    assert cfg.hygiene.dte_max == 45


def test_baseline_compact_omits_hygiene(sample: Any) -> None:
    packet, _ = sample
    compact = packet.compact()
    assert "hygiene" not in compact["config"]
    body = request_body(packet)
    assert "hygiene" not in json.loads(body["input"])["config"]


def test_baseline_recommend_does_not_shortlist() -> None:
    import groktrading.research.cli as research_cli
    import groktrading.research.opening15 as opening15

    assert "build_shortlist" not in Path(research_cli.__file__).read_text()
    assert "build_shortlist" not in Path(opening15.__file__).read_text()
    assert "candidates.json" not in Path(research_cli.__file__).read_text()


def test_as_number_never_invents() -> None:
    assert as_number(None) is None
    assert as_number("") is None
    assert as_number("1.25") == 1.25
    assert as_number(True) is None
    assert as_number("not-a-price") is None


def test_parse_occ_and_dte_buckets(sample: Any) -> None:
    packet, _ = sample
    parsed = parse_occ("AAPL260911C00100000")
    assert parsed is not None
    assert parsed["expiration"] == date(2026, 9, 11)
    assert dte_bucket(0) == "0-2"
    assert dte_bucket(2) == "0-2"
    assert dte_bucket(3) == "3+"
    assert dte_bucket(None) == "unknown"
    # Session 2026-09-08 → 2026-09-11 is 3 DTE (logged, not an overnight hard gate).
    artifact = build_shortlist(packet, [])
    kept = {row["contract"]: row for row in artifact["candidates"]}
    assert "AAPL260911C00100000" in kept
    assert kept["AAPL260911C00100000"]["dte"] == 3
    assert kept["AAPL260911C00100000"]["dte_bucket"] == "3+"


def test_rejects_logged_with_gate_symbol_contract_dte(sample: Any) -> None:
    packet, _ = sample
    symbol = packet.config.symbols[0]
    expensive = f"{symbol}260911C00200000"
    ctx = _context(
        packet,
        [
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=expensive,
                expiration="2026-09-11",
                bid=4.90,
                ask=5.00,
                volume=20,
                open_interest=100,
            )
        ],
    )
    artifact = build_shortlist(packet, ctx.records)
    rejected = [r for r in artifact["rejects"] if r["contract"] == expensive]
    assert rejected
    row = rejected[0]
    assert row["gate"] == "premium_budget"
    assert row["symbol"] == symbol
    assert row["contract"] == expensive
    assert row["dte"] == 3
    assert row["dte_bucket"] == "3+"
    assert "budget-derived" in row["why"]
    assert row["premium"] == 5.0
    assert expensive not in {c["contract"] for c in artifact["candidates"]}


def test_premium_cap_follows_account_equity_not_hardcoded_range(sample: Any) -> None:
    packet, _ = sample
    symbol = packet.config.symbols[0]
    contract = f"{symbol}260911C00150000"
    chain = _chain_evidence(
        packet,
        symbol=symbol,
        contract=contract,
        expiration="2026-09-11",
        bid=2.40,
        ask=2.50,
        volume=10,
        open_interest=50,
    )
    cheap_account = _context(packet, [chain, _portfolio(packet, equity=5_000)])
    rich_account = _context(packet, [chain, _portfolio(packet, equity=50_000)])
    dropped = build_shortlist(packet, cheap_account.records)
    kept = build_shortlist(packet, rich_account.records)
    cheap_budget = dropped["budget"]
    assert cheap_budget["source"] == "account_equity"
    assert cheap_budget["base_usd"] == 5_000
    assert cheap_budget["max_premium_per_share"] == pytest.approx(0.40)
    assert any(r["contract"] == contract and r["gate"] == "premium_budget" for r in dropped["rejects"])
    rich_budget = kept["budget"]
    assert rich_budget["max_premium_per_share"] == pytest.approx(4.00)
    assert any(c["contract"] == contract for c in kept["candidates"])


def test_planning_equity_used_when_portfolio_unknown(sample: Any) -> None:
    packet, _ = sample
    budget = resolve_budget(packet.config.hygiene, [])
    assert budget.source == "planning_equity"
    assert budget.base_usd == DEFAULT_PLANNING_EQUITY_USD
    assert budget.max_premium_per_share == pytest.approx(2.0)


def test_missing_price_rejected_not_invented(sample: Any) -> None:
    packet, _ = sample
    symbol = packet.config.symbols[0]
    contract = f"{symbol}260918C00100000"
    ctx = _context(
        packet,
        [
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=contract,
                expiration="2026-09-18",
                bid=None,
                ask=None,
                volume=12,
                open_interest=80,
            )
        ],
    )
    artifact = build_shortlist(packet, ctx.records)
    row = next(r for r in artifact["rejects"] if r["contract"] == contract)
    assert row["gate"] == "premium_unobserved"
    assert row["premium"] is None
    assert row["dte"] == 10
    assert "not invented" in row["why"]


def test_spread_and_volume_only_when_fields_exist(sample: Any) -> None:
    packet, _ = sample
    symbol = packet.config.symbols[0]
    wide = f"{symbol}260911C00300000"
    thin = f"{symbol}260911C00310000"
    ctx = _context(
        packet,
        [
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=wide,
                expiration="2026-09-11",
                bid=0.50,
                ask=1.50,
                volume=20,
                open_interest=40,
            ),
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=thin,
                expiration="2026-09-11",
                bid=0.95,
                ask=1.00,
                volume=0,
                open_interest=0,
            ),
        ],
    )
    artifact = build_shortlist(packet, ctx.records)
    by_contract = {r["contract"]: r for r in artifact["rejects"]}
    assert by_contract[wide]["gate"] == "spread"
    assert by_contract[thin]["gate"] == "liquidity"
    # Packet prints have bid/ask but no volume — liquidity is skipped, not invented.
    kept = {c["contract"]: c for c in artifact["candidates"]}
    printed = f"{symbol}260911C00100000"
    assert printed in kept
    assert kept[printed]["volume"] is None


def test_ask_side_tag_logged_when_present_not_required(sample: Any) -> None:
    packet, _ = sample
    event = next(e for e in packet.events if e.kind == "option_trade")
    event.raw["tags"] = ["ask_side"]
    artifact = build_shortlist(packet, [])
    row = next(c for c in artifact["candidates"] if c["contract"] == event.raw["option_chain_id"])
    assert row["ask_side_tag"] is True
    packet.config.hygiene.require_ask_side_tag = True
    event.raw["tags"] = ["bid_side"]
    rejected = build_shortlist(packet, [])
    drop = next(r for r in rejected["rejects"] if r["contract"] == event.raw["option_chain_id"])
    assert drop["gate"] == "ask_side"
    assert drop["dte"] == 3


def test_dte_window_logs_zero_two_without_forcing_overnight(sample: Any) -> None:
    packet, _ = sample
    symbol = packet.config.symbols[0]
    zero_dte = f"{symbol}260908C00100000"
    long_dte = f"{symbol}261218C00100000"
    ctx = _context(
        packet,
        [
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=zero_dte,
                expiration="2026-09-08",
                bid=0.90,
                ask=1.00,
                volume=30,
                open_interest=10,
            ),
            _chain_evidence(
                packet,
                symbol=symbol,
                contract=long_dte,
                expiration="2026-12-18",
                bid=0.90,
                ask=1.00,
                volume=30,
                open_interest=10,
            ),
        ],
    )
    artifact = build_shortlist(packet, ctx.records)
    kept = {c["contract"]: c for c in artifact["candidates"]}
    assert kept[zero_dte]["dte"] == 0
    assert kept[zero_dte]["dte_bucket"] == "0-2"
    dropped = next(r for r in artifact["rejects"] if r["contract"] == long_dte)
    assert dropped["gate"] == "dte_window"
    assert dropped["dte"] == (date(2026, 12, 18) - packet.session).days
    assert dropped["dte_bucket"] == "3+"


def test_select_writes_candidates_and_payload(sample: Any, tmp_path: Path, monkeypatch: Any) -> None:
    packet, decision = sample
    packet.synthetic = False
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    seen: list[dict[str, Any]] = []

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
        seen.append(payload)
        if schema is cycle.RetrievalRequest:
            return schema(evidence_ids=[], rationale="none")
        if schema is cycle.Selection:
            assert "candidates" in payload
            assert payload["hygiene"]["architecture"] == "gates_then_judgment"
            assert payload["candidates"]
            return schema(
                decision=Decision.model_validate(decision["decision"]),
                context_citations=["macro"],
                portfolio_assessment="fixture",
                memory_use="No prior days",
            )
        raise AssertionError(schema)

    monkeypatch.setattr(cycle, "cli_json", fake)
    monkeypatch.setattr(cycle, "now_utc", lambda: packet.knowledge_cutoff)
    cycle.select(packet, _context(packet), memory, tmp_path / "select")
    artifact = json.loads((tmp_path / "select/candidates.json").read_text())
    assert artifact["architecture"] == "gates_then_judgment"
    assert artifact["path"] == "opening15_expanded_select"
    assert artifact["stats"]["kept"] >= 1
    assert all("dte" in row for row in artifact["candidates"])
    assert all("dte" in row and "gate" in row for row in artifact["rejects"])
    cycle_input = json.loads((tmp_path / "select/cycle-input.json").read_text())
    assert cycle_input["hygiene"]["candidates_file"] == "candidates.json"


def test_select_rejects_pick_outside_shortlist(
    sample: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    packet, decision = sample
    packet.synthetic = False
    start, _ = window(packet.session)
    memory = cycle.build_memory([], packet.session, start - timedelta(minutes=5))
    decision["decision"]["picks"][0]["option_symbol"] = "AAPL260911C00999000"
    decision["decision"]["picks"][0]["max_entry_price"] = 1.0

    def fake(name: str, payload: Any, schema: Any, *args: Any) -> Any:
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
    with pytest.raises(ValueError, match="contract"):
        cycle.select(packet, _context(packet), memory, tmp_path / "bad-pick")
    assert (tmp_path / "bad-pick/candidates.json").is_file()
    assert not (tmp_path / "bad-pick/decision.json").exists()


def test_apply_gates_logs_dte_on_unknown_expiration() -> None:
    from groktrading.research.hygiene import HygieneBudget, _Observed

    item = _Observed("AAPL", "NOT-AN-OCC")
    item.sources = ["option_chain"]
    item.ask = 1.0
    settings = HygieneSettings()
    budget = HygieneBudget(
        source="planning_equity",
        base_usd=25_000,
        premium_budget_pct=0.008,
        max_debit_usd=200,
        max_premium_per_share=2.0,
    )
    kept, dropped = apply_gates(
        item,
        session=date(2026, 9, 8),
        symbols={"AAPL"},
        settings=settings,
        budget=budget,
    )
    # Unparseable DTE is logged unknown; window is not forced.
    assert dropped is None
    assert kept is not None
    assert kept["dte"] is None
    assert kept["dte_bucket"] == "unknown"
