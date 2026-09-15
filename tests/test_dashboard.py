"""Desk live-board builder: funnel + ws_stats schema without live Helsinki."""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.builder import build_board, write_board
from dashboard.cli import main as dashboard_main
from dashboard.config import (
    HARD_RULES,
    I1_MAX_AGE_SEC,
    LIVE_GATE,
    NEW_WS_SUBSCRIPTIONS,
    OPPORTUNITY_WEBHOOK_RESUME,
    SCHEMA_ID,
    SIBLING_SITE_REPO,
    SIT_MATCH_STAYS_OFF,
)
from dashboard.funnel import build_funnel
from dashboard.ws_stats import build_ws_stats

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dashboard"
NOW = "2026-09-14T16:45:00+00:00"
SESSION = "2026-09-14"


def test_funnel_from_refuse_fixtures_skips_invented_and_missing_occ() -> None:
    funnel = build_funnel(FIXTURES / "uw_opportunity_refuses.jsonl")
    assert funnel["kind"] == "opportunity_funnel"
    assert funnel["schema"] == "groktrading.desk_board.funnel.v1"
    assert funnel["present"] is True
    assert funnel["empty_reason"] is None
    assert funnel["rows"] == 3
    assert funnel["skipped_invented"] == 1
    assert funnel["skipped_no_occ"] == 1
    assert funnel["refuse_reasons"] == {"I1_stale": 2, "already_run": 1}
    assert funnel["last_occs"] == [
        "QQQ260914P00580000",
        "SPY260914C00660000",
        "IWM260914P00240000",
    ]
    assert "FAKE260914C00999000" not in funnel["last_occs"]
    asks = {row["occ"]: row.get("evidence_ask") for row in funnel["refuses"]}
    assert asks["QQQ260914P00580000"] == "1.25"
    assert asks["IWM260914P00240000"] is None
    posture = funnel["posture"]
    assert posture["sit_match"] is False
    assert posture["sit_match_stays_off"] is True
    assert posture["opportunity_webhook"] == "paused"
    assert posture["opportunity_webhook_resume"] is False
    assert posture["hunt"] == "Continual15 + shortlist.json"
    assert posture["i1_max_age_sec"] == 60.0
    assert posture["unlock_i1"] is False
    assert posture["live_gate"] is False
    assert posture["places_orders"] is False
    assert posture["invented"] is False


def test_funnel_missing_refuses_is_a_reported_hole() -> None:
    missing = build_funnel(Path("/no/such/uw_opportunity_refuses.jsonl"))
    assert missing["present"] is False
    assert missing["empty_reason"] == "file_missing"
    assert missing["rows"] == 0
    assert missing["last_occs"] == []
    assert missing["refuse_reasons"] == {}
    none = build_funnel(None)
    assert none["empty_reason"] == "no_input"
    assert none["present"] is False


def test_funnel_shortlist_and_shadow_hooks() -> None:
    funnel = build_funnel(
        FIXTURES / "uw_opportunity_refuses.jsonl",
        shortlist=FIXTURES / "shortlist.json",
        shadow_summary=FIXTURES / "shadow_summary.json",
    )
    shortlist = funnel["shortlist"]
    assert shortlist["present"] is True
    assert shortlist["ranked_at"] == "2026-09-14T16:29:50Z"
    assert shortlist["emit_sit_match"] is False
    assert shortlist["candidate_occs"] == ["QQQ260914P00580000"]
    assert shortlist["candidates"][0]["underlying"] == "QQQ"
    shadow = funnel["shadow_summary"]
    assert shadow["present"] is True
    assert shadow["kind"] == "shadow_bets_summary"
    assert shadow["opened"] == 3
    assert shadow["marked"] == 2
    assert shadow["unmarked"] == 1
    assert shadow["pnl"] is None
    assert shadow["one_lot_usd"] == "5.00"
    assert shadow["labels"]["yes_latency_fix_wake"] == 2


def test_funnel_does_not_invent_shortlist_or_shadow_when_absent() -> None:
    funnel = build_funnel(FIXTURES / "uw_opportunity_refuses.jsonl")
    assert funnel["shortlist"]["present"] is False
    assert funnel["shortlist"]["empty_reason"] == "no_input"
    assert funnel["shortlist"]["candidate_occs"] == []
    assert funnel["shadow_summary"]["present"] is False
    assert funnel["shadow_summary"]["pnl"] is None


def test_ws_stats_from_health_fixtures() -> None:
    stats = build_ws_stats(
        finnhub_tape=FIXTURES / "finnhub_tape.json",
        live_tape=FIXTURES / "live_tape_health.json",
    )
    assert stats["kind"] == "ws_stats"
    assert stats["schema"] == "groktrading.desk_board.ws_stats.v1"
    assert stats["read_only"] is True
    assert stats["new_subscriptions"] is False
    assert stats["sit_match_unmute"] is False
    assert stats["sit_match_stays_off"] is True
    assert stats["opportunity_webhook_resume"] is False
    assert stats["places_orders"] is False
    finnhub = stats["finnhub_tape"]
    assert finnhub["present"] is True
    assert finnhub["connected"] is True
    assert finnhub["symbols"] == ["SPY", "QQQ"]
    assert finnhub["freshness"]["stale"] is False
    assert finnhub["freshness"]["last_event_ts"] == "2026-09-14T16:28:55Z"
    assert "option NBBO" in finnhub["note"]
    live = stats["live_tape"]
    assert live["present"] is True
    assert live["flow_n"] == 12
    assert live["flow_http"] == {"ok": 10, "timeout": 1, "errors": 1}
    assert live["errors"] == ["timeout", "http_5xx"]
    assert live["candidates"] == 2
    assert stats["missing"] == ["shortlist"]
    assert stats["shortlist"]["present"] is False
    assert stats["shortlist"]["empty_reason"] == "no_input"


def test_ws_stats_missing_helsinki_files_are_holes_not_inventions() -> None:
    stats = build_ws_stats()
    assert stats["finnhub_tape"]["present"] is False
    assert stats["finnhub_tape"]["empty_reason"] == "no_input"
    assert stats["finnhub_tape"]["connected"] is None
    assert stats["finnhub_tape"]["symbols"] == []
    assert stats["live_tape"]["present"] is False
    assert stats["live_tape"]["empty_reason"] == "no_input"
    assert stats["live_tape"]["flow_n"] is None
    assert stats["live_tape"]["candidates"] is None
    assert stats["missing"] == ["finnhub_tape", "live_tape", "shortlist"]
    absent = build_ws_stats(
        finnhub_tape=Path("/opt/trading-desk/finnhub_tape.json"),
        live_tape=Path("/opt/trading-desk/live_tape.json"),
    )
    assert absent["finnhub_tape"]["empty_reason"] == "file_missing"
    assert absent["live_tape"]["empty_reason"] == "file_missing"
    assert absent["finnhub_tape"]["present"] is False
    assert absent["live_tape"]["flow_n"] is None


def test_ws_stats_unknown_live_tape_shape_does_not_invent_counters() -> None:
    stats = build_ws_stats(live_tape=FIXTURES / "unknown_tape.json")
    live = stats["live_tape"]
    assert live["present"] is False
    assert live["empty_reason"] == "unknown_shape"
    assert live["keys_found"] == []
    assert live["flow_n"] is None
    assert live["candidates"] is None
    assert live["errors"] == []


def test_board_schema_and_hard_rules() -> None:
    board = build_board(
        refuses=FIXTURES / "uw_opportunity_refuses.jsonl",
        shortlist=FIXTURES / "shortlist.json",
        shadow_summary=FIXTURES / "shadow_summary.json",
        finnhub_tape=FIXTURES / "finnhub_tape.json",
        live_tape=FIXTURES / "live_tape_health.json",
        session=SESSION,
        now=NOW,
    )
    assert board["schema"] == SCHEMA_ID
    assert board["kind"] == "desk_board"
    assert board["session"] == SESSION
    assert board["generated_at"] == "2026-09-14T16:45:00Z"
    assert board["live_gate"] is LIVE_GATE
    assert board["places_orders"] is False
    assert board["invented"] is False
    assert board["unlock_i1"] is False
    assert board["i1_max_age_sec"] == I1_MAX_AGE_SEC
    assert board["sit_match"] is False
    assert board["sit_match_stays_off"] is SIT_MATCH_STAYS_OFF
    assert board["new_ws_subscriptions"] is NEW_WS_SUBSCRIPTIONS
    assert board["opportunity_webhook_resume"] is OPPORTUNITY_WEBHOOK_RESUME
    for rule in HARD_RULES:
        assert rule in board["hard_rules"]
    assert board["sibling_site"]["repo"] == SIBLING_SITE_REPO
    assert board["sibling_site"]["host"] == "Vercel"
    assert "docs/WEBSOCKETS.md" in board["docs"]
    assert "docs/REALTIME_PLANES.md" in board["docs"]
    assert board["funnel"]["rows"] == 3
    assert board["ws_stats"]["read_only"] is True


def test_write_static_html_json_and_cli(tmp_path: Path) -> None:
    board = build_board(
        refuses=FIXTURES / "uw_opportunity_refuses.jsonl",
        finnhub_tape=FIXTURES / "finnhub_tape.json",
        live_tape=FIXTURES / "live_tape_health.json",
        session=SESSION,
        now=NOW,
    )
    written = write_board(board, out_dir=tmp_path)
    json_path = Path(written["board_json"])
    html_path = Path(written["index_html"])
    assert json_path.name == "board.json"
    assert html_path.name == "index.html"
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema"] == SCHEMA_ID
    assert loaded["funnel"]["refuse_reasons"]["I1_stale"] == 2
    html = html_path.read_text(encoding="utf-8")
    assert "Opportunity-process funnel" in html
    assert "I1_stale" in html
    assert "QQQ260914P00580000" in html
    assert "READ-ONLY" in html
    assert "sit_match stays" in html.lower() or "sit_match stays OFF" in html
    assert "darrylsj/trading-desk-live-board" in html
    assert "FAKE260914C00999000" not in html
    assert "token" not in html.lower() or "token" in "no token committed"
    payload = html.split('id="board-data">', 1)[1].split("</script>", 1)[0]
    embedded = json.loads(payload)
    assert embedded["schema"] == SCHEMA_ID
    assert embedded["ws_stats"]["new_subscriptions"] is False

    out_dir = tmp_path / "cli"
    assert (
        dashboard_main(
            [
                "build",
                "--refuses",
                str(FIXTURES / "uw_opportunity_refuses.jsonl"),
                "--session",
                SESSION,
                "--now",
                NOW,
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )
    cli_board = json.loads((out_dir / "board.json").read_text(encoding="utf-8"))
    assert cli_board["funnel"]["present"] is True
    assert cli_board["ws_stats"]["finnhub_tape"]["empty_reason"] == "no_input"
    assert cli_board["new_ws_subscriptions"] is False
    assert cli_board["opportunity_webhook_resume"] is False


def test_committed_example_is_fixture_built() -> None:
    example = json.loads((ROOT / "dashboard" / "example" / "board.json").read_text())
    board = build_board(
        refuses=FIXTURES / "uw_opportunity_refuses.jsonl",
        shortlist=FIXTURES / "shortlist.json",
        shadow_summary=FIXTURES / "shadow_summary.json",
        finnhub_tape=FIXTURES / "finnhub_tape.json",
        live_tape=FIXTURES / "live_tape_health.json",
        session=SESSION,
        now=NOW,
    )
    assert example["schema"] == board["schema"]
    assert example["funnel"]["refuse_reasons"] == board["funnel"]["refuse_reasons"]
    assert example["funnel"]["last_occs"] == board["funnel"]["last_occs"]
    assert example["ws_stats"]["live_tape"]["flow_n"] == 12
    assert example["new_ws_subscriptions"] is False
    html = (ROOT / "dashboard" / "example" / "index.html").read_text(encoding="utf-8")
    assert "QQQ260914P00580000" in html
    assert "READ-ONLY" in html


def test_cli_invalid_now_is_fail_closed(capsys: object) -> None:
    assert dashboard_main(["build", "--now", "yesterday"]) == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    doc = json.loads(captured.out)
    assert doc["ok"] is False
    assert doc["reasons"] == ["now_naive"]
    assert doc["sit_match"] is False
    assert doc["new_ws_subscriptions"] is False
