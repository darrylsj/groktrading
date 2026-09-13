from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.strategy_factory.cli import main as factory_main
from tools.strategy_factory.config import (
    LIVE_GATE,
    REPO_CONFIG,
    FactoryError,
    load_config,
    pack_paths,
)
from tools.strategy_factory.confirm import parse_confirmation
from tools.strategy_factory.ledger import StrategyFactory

NOW = "2026-09-03T16:30:00+00:00"
SESSION = "2026-09-03"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STRATEGY_FACTORY_PACK", str(tmp_path))
    return tmp_path


def _propose_cli(hyp_id: str, **extra: str) -> int:
    argv = [
        "propose",
        "--id",
        hyp_id,
        "--category",
        extra.get("category", "flow_debit_bto"),
        "--title",
        extra.get("title", "UW print + matching ask BTO"),
        "--mechanism",
        extra.get("mechanism", "Fresh UW print + sit-2 + matching ask"),
        "--falsifier",
        extra.get("falsifier", "Print stale >60s or thesis dead"),
        "--session",
        extra.get("session", SESSION),
        "--now",
        extra.get("now", NOW),
    ]
    return factory_main(argv)


def test_desk_config_forces_live_gate_false(tmp_path: Path) -> None:
    desk = json.loads(REPO_CONFIG.read_text(encoding="utf-8"))
    assert desk["live_gate"] is False
    assert desk["places_orders"] is False
    assert desk["max_active_per_category_per_session"] == 3
    assert desk["min_confirmations_for_validated"] == 2
    assert desk["min_confirmations_for_live_allow"] == 3
    assert desk["require_falsifier_for_live_allow"] is True
    assert desk["require_mechanism_for_validated"] is True
    cfg = load_config(explicit=REPO_CONFIG)
    assert cfg.live_gate is LIVE_GATE
    assert cfg.live_gate is False
    override = tmp_path / "strategy_factory.json"
    override.write_text(
        json.dumps({**desk, "live_gate": True, "places_orders": True}),
        encoding="utf-8",
    )
    forced = load_config(explicit=override)
    assert forced.live_gate is False
    assert forced.places_orders is False


def test_propose_writes_pack_paths(pack: Path) -> None:
    factory = StrategyFactory(pack)
    hyp = factory.propose(
        hyp_id="smoke-flow-001",
        category="flow_debit_bto",
        title="Smoke hyp",
        mechanism="named mechanism",
        session=SESSION,
        now=NOW,
    )
    assert hyp.stage == "candidate"
    assert hyp.live_gate is False
    assert hyp.places_orders is False
    assert hyp.invented is False
    paths = pack_paths(pack)
    assert paths.events.is_file()
    assert paths.ledger.is_file()
    assert paths.active.is_file()
    assert paths.events == pack / "evidence" / "strategy_factory_events.jsonl"
    assert paths.ledger == pack / "evidence" / "strategy_factory_ledger.jsonl"
    assert paths.active == pack / "state" / "strategy_factory_active.json"
    active = json.loads(paths.active.read_text(encoding="utf-8"))
    assert active["live_gate"] is False
    assert "smoke-flow-001" in active["sessions"][SESSION]["flow_debit_bto"]
    events = paths.events.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[0])["action"] == "propose"


def test_confirm_allowlist_and_invented_prices(pack: Path) -> None:
    factory = StrategyFactory(pack)
    factory.propose(
        hyp_id="hyp-confirm",
        category="gex_shadow_obs",
        title="GEX shadow",
        session=SESSION,
        now=NOW,
    )
    factory.confirm(
        hyp_id="hyp-confirm",
        source="gex_agree",
        note="cited existing pair score",
        evidence_ref="gex:fixture",
        now=NOW,
    )
    with pytest.raises(FactoryError) as unknown:
        factory.confirm(hyp_id="hyp-confirm", source="reddit_hot_take", now=NOW)
    assert unknown.value.code == "unknown_source"
    with pytest.raises(FactoryError) as prices:
        parse_confirmation(source="uw_print", extra={"ask": "1.25"}, now=NOW)
    assert prices.value.code == "invented_price_forbidden"
    with pytest.raises(FactoryError) as pnl:
        parse_confirmation(source="uw_print", extra={"pnl": "12"}, now=NOW)
    assert pnl.value.code == "invented_price_forbidden"


def test_cli_smoke_hyp_reaches_paper(pack: Path) -> None:
    assert _propose_cli("smoke-flow-001") == 0
    assert (
        factory_main(
            [
                "confirm",
                "--hyp-id",
                "smoke-flow-001",
                "--source",
                "uw_print",
                "--note",
                "cited existing tape print",
                "--now",
                NOW,
            ]
        )
        == 0
    )
    assert factory_main(["advance", "--id", "smoke-flow-001", "--now", NOW]) == 0
    assert factory_main(["status", "--id", "smoke-flow-001"]) == 0
    factory = StrategyFactory(pack)
    hyp = factory.get("smoke-flow-001")
    assert hyp.stage == "paper"
    assert hyp.live_gate is False
    listing = factory.list_hypotheses(session=SESSION, stage="paper")
    assert [item.hyp_id for item in listing] == ["smoke-flow-001"]


def test_validated_and_live_allow_gates(pack: Path) -> None:
    factory = StrategyFactory(pack)
    factory.propose(
        hyp_id="gate-hyp",
        category="overnight_carry",
        title="Carry note",
        session=SESSION,
        now=NOW,
    )
    factory.advance(hyp_id="gate-hyp", now=NOW)  # candidate → paper
    with pytest.raises(FactoryError) as mech:
        factory.advance(hyp_id="gate-hyp", now=NOW)
    assert mech.value.code == "mechanism_required"
    factory.confirm(
        hyp_id="gate-hyp",
        source="mechanism_named",
        note="Pin below the wall overnight",
        now=NOW,
    )
    with pytest.raises(FactoryError) as confs:
        factory.advance(hyp_id="gate-hyp", now=NOW)
    assert confs.value.code == "confirmations_required"
    factory.confirm(hyp_id="gate-hyp", source="helsinki_fresh", now=NOW)
    factory.advance(hyp_id="gate-hyp", now=NOW)  # paper → validated
    assert factory.get("gate-hyp").stage == "validated"
    with pytest.raises(FactoryError) as fals:
        factory.advance(hyp_id="gate-hyp", now=NOW)
    assert fals.value.code == "falsifier_required"
    factory.confirm(
        hyp_id="gate-hyp",
        source="falsifier_named",
        note="spot through the wall",
        now=NOW,
    )
    factory.advance(hyp_id="gate-hyp", now=NOW)  # validated → live_allow
    hyp = factory.get("gate-hyp")
    assert hyp.stage == "live_allow"
    assert hyp.live_gate is False
    assert hyp.places_orders is False
    assert hyp.mechanism == "Pin below the wall overnight"
    assert hyp.falsifier == "spot through the wall"


def test_reject_kill_retire_transitions(pack: Path) -> None:
    factory = StrategyFactory(pack)
    factory.propose(
        hyp_id="early-reject",
        category="other",
        title="No tape",
        session=SESSION,
        now=NOW,
    )
    rejected = factory.reject(hyp_id="early-reject", reason="no mechanism", now=NOW)
    assert rejected.stage == "rejected"
    factory.propose(
        hyp_id="paper-kill",
        category="other",
        title="Dead paper",
        session=SESSION,
        now=NOW,
    )
    factory.advance(hyp_id="paper-kill", now=NOW)
    killed = factory.kill(hyp_id="paper-kill", reason="failed paper window", now=NOW)
    assert killed.stage == "killed"
    factory.propose(
        hyp_id="grad-retire",
        category="external_shadow",
        title="External shadow",
        mechanism="named",
        falsifier="named die",
        session=SESSION,
        now=NOW,
    )
    factory.confirm(hyp_id="grad-retire", source="shortlist_hit", now=NOW)
    factory.confirm(hyp_id="grad-retire", source="tradier_fresh_ask", now=NOW)
    factory.confirm(hyp_id="grad-retire", source="uw_print", now=NOW)
    factory.advance(hyp_id="grad-retire", now=NOW)
    factory.advance(hyp_id="grad-retire", now=NOW)
    factory.advance(hyp_id="grad-retire", now=NOW)
    assert factory.get("grad-retire").stage == "live_allow"
    with pytest.raises(FactoryError) as no_reject:
        factory.reject(hyp_id="grad-retire", reason="too late", now=NOW)
    assert no_reject.value.code == "invalid_transition"
    retired = factory.retire(hyp_id="grad-retire", reason="observation complete", now=NOW)
    assert retired.stage == "retired"
    assert retired.live_gate is False


def test_category_session_cap(pack: Path) -> None:
    factory = StrategyFactory(pack)
    for idx in range(3):
        factory.propose(
            hyp_id=f"cap-{idx}",
            category="i4_defined_risk_credit",
            title=f"I4 paper {idx}",
            session=SESSION,
            now=NOW,
        )
    with pytest.raises(FactoryError) as cap:
        factory.propose(
            hyp_id="cap-3",
            category="i4_defined_risk_credit",
            title="One too many",
            session=SESSION,
            now=NOW,
        )
    assert cap.value.code == "category_session_cap"
    factory.reject(hyp_id="cap-0", reason="room", now=NOW)
    fourth = factory.propose(
        hyp_id="cap-3",
        category="i4_defined_risk_credit",
        title="After reject",
        session=SESSION,
        now=NOW,
    )
    assert fourth.stage == "candidate"
    other = factory.propose(
        hyp_id="cap-other-cat",
        category="flow_debit_bto",
        title="Different category",
        session=SESSION,
        now=NOW,
    )
    assert other.stage == "candidate"


def test_score_day_and_docs_observational(pack: Path) -> None:
    factory = StrategyFactory(pack)
    factory.propose(
        hyp_id="score-1",
        category="flow_debit_bto",
        title="Score",
        session=SESSION,
        now=NOW,
    )
    factory.confirm(hyp_id="score-1", source="uw_print", now=NOW)
    factory.advance(hyp_id="score-1", now=NOW)
    doc = factory.score_day(session=SESSION, now=NOW)
    assert doc["kind"] == "strategy_factory_score_day"
    assert doc["session"] == SESSION
    assert doc["live_gate"] is False
    assert doc["places_orders"] is False
    assert doc["invented"] is False
    assert doc["pnl"] is None
    assert doc["counts"]["paper"] == 1
    assert doc["unique_confirmation_sources"] == 1
    assert factory_main(["score-day", "--session", SESSION, "--now", NOW]) == 0
    for rel in (
        "tools/strategy_factory/cli.py",
        "tools/strategy_factory/ledger.py",
        "tools/strategy_factory/confirm.py",
        "tools/strategy_factory/config.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "httpx" not in text
        assert "requests" not in text
        assert "import tools.live_order_gate" not in text
        assert "groktrading.feeds" not in text
        assert "groktrading.brokers" not in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    doc_text = (ROOT / "docs" / "STRATEGY_FACTORY.md").read_text(encoding="utf-8")
    tool_readme = (ROOT / "tools" / "strategy_factory" / "README.md").read_text(
        encoding="utf-8"
    )
    for body in (readme, doc_text, tool_readme):
        assert "observational" in body.lower()
        assert "live_gate" in body
        assert "live_order_gate" in body
    assert "docs/STRATEGY_FACTORY.md" in readme
    assert "docs/STRATEGY_FACTORY.md" in tool_readme
    assert "never invent" in doc_text.lower() or "Never invent" in doc_text
    assert "Not a replacement" in doc_text
    assert "STO_UNLOCK_PLAN.md" in doc_text
