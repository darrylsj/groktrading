from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from groktrading.timeutil import UTC
from tools.shadow_bets.cli import main as shadow_main
from tools.shadow_bets.config import (
    HOST_OPP_WEBHOOK,
    I1_MAX_AGE_SEC,
    LIVE_GATE,
    PACK_SYNC_PATH,
    SHORTLIST_OPP_MAX_AGE_SEC,
    SHORTLIST_OPP_MIN_INTERVAL_SEC,
    SHORTLIST_OPP_OCC_DEBOUNCE_SEC,
    SIT_MATCH_STAYS_OFF,
    WAKE_REENABLE_BUDGET_SEC,
    ShadowBetsError,
    assert_i1_unlocked,
    pack_paths,
)
from tools.shadow_bets.ledger import ShadowBook, infer_label

NOW = "2026-09-14T16:45:00+00:00"
SESSION = "2026-09-14"
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_bets"


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SHADOW_BETS_PACK", str(tmp_path))
    return tmp_path


def test_i1_stays_sixty_and_widen_forbidden() -> None:
    assert I1_MAX_AGE_SEC == 60.0
    assert assert_i1_unlocked(None) == 60.0
    assert assert_i1_unlocked(45.0) == 45.0
    with pytest.raises(ShadowBetsError) as widened:
        assert_i1_unlocked(300.0)
    assert widened.value.code == "i1_widen_forbidden"
    with pytest.raises(ShadowBetsError) as infinite:
        assert_i1_unlocked(float("inf"))
    assert infinite.value.code == "i1_invalid_max_age"


def test_infer_yes_latency_fix_wake_from_hops() -> None:
    executed = datetime(2026, 9, 14, 16, 30, 1, tzinfo=UTC)
    row = {
        "reason": "I1_stale",
        "executed_at": executed.isoformat(),
        "emitted_at": (executed + timedelta(seconds=11)).isoformat(),
        "consumed_at": (executed + timedelta(seconds=159)).isoformat(),
    }
    assert infer_label(row) == "yes_latency_fix_wake"
    fresh = {
        "reason": "I1_stale",
        "executed_at": executed.isoformat(),
        "emitted_at": (executed + timedelta(seconds=5)).isoformat(),
        "consumed_at": (executed + timedelta(seconds=20)).isoformat(),
    }
    assert infer_label(fresh) == "yes_fresh_wake"
    assert infer_label({"reason": "already_run"}) == "no_latency_fix_wake"
    assert infer_label({"reason": "I1_stale"}) == "yes_latency_fix_wake"


def test_open_mark_summarize_from_fixtures(pack: Path) -> None:
    book = ShadowBook(pack)
    opened = book.open_from_refuses(FIXTURES / "refuses.jsonl", session=SESSION, now=NOW)
    assert opened["opened"] == 3
    assert opened["live_gate"] is False
    assert opened["unlock_i1"] is False
    assert opened["i1_max_age_sec"] == 60.0
    labels = {bet["occ"]: bet["label"] for bet in opened["bets"]}
    assert labels["QQQ260914P00580000"] == "yes_latency_fix_wake"
    assert labels["SPY260914C00660000"] == "no_latency_fix_wake"
    assert labels["IWM260914P00240000"] == "yes_latency_fix_wake"
    paths = pack_paths(pack)
    assert paths.events.is_file()
    assert paths.ledger.is_file()
    assert paths.session.is_file()

    marked = book.mark_session(FIXTURES / "marks.jsonl", session=SESSION, now=NOW)
    assert marked["marked"] == 2
    assert marked["unmarked"] == 1
    assert "IWM260914P00240000" in "".join(marked["unmarked_ids"])

    summary = book.summarize(session=SESSION, now=NOW)
    assert summary["kind"] == "shadow_bets_summary"
    assert summary["opened"] == 3
    assert summary["marked"] == 2
    assert summary["unmarked"] == 1
    assert summary["scored"] == 2
    assert summary["hits"] == 1
    assert summary["hit_rate"] == 0.5
    assert summary["one_lot_usd"] == "5.00"
    assert summary["pnl"] is None
    assert summary["invented"] is False
    assert summary["places_orders"] is False
    assert summary["live_gate"] is LIVE_GATE
    assert summary["unlock_i1"] is False
    assert summary["labels"]["yes_latency_fix_wake"] == 2
    assert summary["labels"]["no_latency_fix_wake"] == 1


def test_never_invents_nbbo_or_synthetic(pack: Path) -> None:
    book = ShadowBook(pack)
    book.open_from_refuses(FIXTURES / "refuses.jsonl", session=SESSION, now=NOW)
    invented = book.mark_session(
        [
            {
                "occ": "QQQ260914P00580000",
                "bid": "9.99",
                "source": "tradier_production",
                "invented": True,
            }
        ],
        session=SESSION,
        now=NOW,
    )
    assert invented["marked"] == 0
    assert invented["rejected_marks"][0]["reason"] == "invented_nbbo_forbidden"
    synthetic = book.mark_session(
        [
            {
                "occ": "QQQ260914P00580000",
                "bid": "1.40",
                "source": "synthetic",
            }
        ],
        session=SESSION,
        now=NOW,
    )
    assert synthetic["marked"] == 0
    assert synthetic["rejected_marks"][0]["reason"] == "mark_source_not_tradier"
    missing = book.mark_session([], session=SESSION, now=NOW)
    assert missing["marked"] == 0
    assert missing["unmarked"] == 3
    summary = book.summarize(session=SESSION, now=NOW)
    assert summary["scored"] == 0
    assert summary["one_lot_usd"] is None
    assert summary["pnl"] is None


def test_cli_run_session(pack: Path) -> None:
    assert (
        shadow_main(
            [
                "run-session",
                "--session",
                SESSION,
                "--refuses",
                str(FIXTURES / "refuses.jsonl"),
                "--marks",
                str(FIXTURES / "marks.jsonl"),
                "--now",
                NOW,
            ]
        )
        == 0
    )
    book = ShadowBook(pack)
    summary = book.summarize(session=SESSION, now=NOW)
    assert summary["opened"] == 3
    assert summary["marked"] == 2
    assert shadow_main(["summarize", "--session", SESSION, "--now", NOW]) == 0


def test_cli_subcommands_and_missing_file(pack: Path) -> None:
    assert (
        shadow_main(
            [
                "open-from-refuses",
                "--session",
                SESSION,
                "--refuses",
                str(FIXTURES / "refuses.jsonl"),
                "--now",
                NOW,
            ]
        )
        == 0
    )
    assert (
        shadow_main(
            [
                "mark-session",
                "--session",
                SESSION,
                "--marks",
                str(FIXTURES / "marks.jsonl"),
                "--now",
                NOW,
            ]
        )
        == 0
    )
    assert shadow_main(["open-from-refuses", "--session", SESSION, "--refuses", "/no/such.jsonl"]) == 2


def test_opportunity_webhook_contract_stays_off() -> None:
    from tests.scripts_loader import load

    opp = load(
        "shortlist_opportunity_webhook",
        "deploy/examples/helsinki/shortlist_opportunity_webhook.py",
    )
    assert opp.SIT_MATCH_STAYS_OFF is True
    assert opp.SHORTLIST_OPP_TOP1_ONLY is True
    assert opp.SHORTLIST_OPP_MAX_AGE_SEC == 45.0
    assert opp.SHORTLIST_OPP_OCC_DEBOUNCE_SEC == 600.0
    assert opp.SHORTLIST_OPP_MIN_INTERVAL_SEC == 300.0
    assert opp.WAKE_REENABLE_BUDGET_SEC == 30.0
    assert opp.I1_MAX_AGE_SEC == 60.0
    assert opp.HOST_SCRIPT == HOST_OPP_WEBHOOK
    assert "Continual15 + shortlist.json" in opp.HUNT_WHILE_PAUSED
    now = datetime(2026, 9, 14, 16, 30, 20, tzinfo=UTC)
    fresh = {
        "occ": "QQQ260914P00580000",
        "executed_at": "2026-09-14T16:30:01Z",
    }
    allowed = opp.emit_allowed(fresh, now=now, rank=1)
    assert allowed["allow"] is True
    assert allowed["sit_match"] is False
    assert allowed["unlock_i1"] is False
    assert allowed["places_orders"] is False
    not_top1 = opp.emit_allowed(fresh, now=now, rank=2)
    assert not_top1["allow"] is False
    assert not_top1["reason"] == "not_top1"
    stale = opp.emit_allowed(
        {"occ": "QQQ260914P00580000", "executed_at": "2026-09-14T16:29:00Z"},
        now=now,
        rank=1,
    )
    assert stale["allow"] is False
    debounced = opp.emit_allowed(
        fresh,
        now=now,
        rank=1,
        last_occ_at=now - timedelta(seconds=60),
    )
    assert debounced["reason"] == "occ_debounce"
    interval = opp.emit_allowed(
        fresh,
        now=now,
        rank=1,
        last_global_at=now - timedelta(seconds=60),
    )
    assert interval["reason"] == "global_min_interval"
    assert opp.wake_fast_enough(29.9) is True
    assert opp.wake_fast_enough(30.0) is False


def test_tool_stays_observational_and_docs() -> None:
    assert SIT_MATCH_STAYS_OFF is True
    assert SHORTLIST_OPP_MAX_AGE_SEC == 45.0
    assert SHORTLIST_OPP_OCC_DEBOUNCE_SEC == 600.0
    assert SHORTLIST_OPP_MIN_INTERVAL_SEC == 300.0
    assert WAKE_REENABLE_BUDGET_SEC == 30.0
    assert PACK_SYNC_PATH.endswith("tools/shadow_bets/")
    for rel in (
        "tools/shadow_bets/cli.py",
        "tools/shadow_bets/ledger.py",
        "tools/shadow_bets/config.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "httpx" not in text
        assert "requests" not in text
        assert "import tools.live_order_gate" not in text
        assert "groktrading.feeds" not in text
        assert "groktrading.brokers" not in text
        assert "submit_option_order" not in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "SHADOW_BETS.md").read_text(encoding="utf-8")
    tool = (ROOT / "tools" / "shadow_bets" / "README.md").read_text(encoding="utf-8")
    planes = (ROOT / "docs" / "REALTIME_PLANES.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for body in (readme, doc, tool):
        assert "observational" in body.lower()
        assert "yes_latency_fix_wake" in body
        assert "live_gate" in body
        assert "Never invent" in body or "never invent" in body
    assert "docs/SHADOW_BETS.md" in readme
    assert "stays off" in planes.lower() and "stays off" in readme.lower()
    assert "TOP1_ONLY" in planes
    assert "SHORTLIST_OPP_MAX_AGE_SEC=45" in planes or "SHORTLIST_OPP_MAX_AGE_SEC = 45" in planes
    assert "600s" in planes
    assert "300s" in planes
    assert "<30s" in planes or "<30 s" in planes
    assert "Continual15 + shortlist.json" in planes
    assert HOST_OPP_WEBHOOK in planes
    assert "MUST_TRADE_SMALL_ASK_CAP" in changelog
    assert "shadow" in changelog.lower()
    assert "2026-09-14" in changelog
