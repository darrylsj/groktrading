from __future__ import annotations

import json
from pathlib import Path

from groktrading.cli import (
    account_events_main,
    finnhub_tape_main,
    flow_alerts_main,
    quote_interest_main,
    replay_scorecard_main,
    screener_snapshot_main,
    shadow_marks_main,
    tape_skeleton_main,
    tide_state_main,
    uw_ws_probe_main,
)


def test_tape_skeleton_writes_signals_only(tmp_path: Path) -> None:
    out = tmp_path / "package_tape_skeleton.json"
    assert tape_skeleton_main(["--output", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["kind"] == "package_tape_skeleton"
    assert doc["mode"] == "signals_only"
    assert doc["live_explicitly_enabled"] is False
    assert "ws_tape.py" in doc["note"]
    assert "never places orders" in doc["note"]


def test_account_events_skeleton_never_connects(tmp_path: Path) -> None:
    out = tmp_path / "account_events.json"
    assert account_events_main(["--state", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["mode"] == "signals_only"
    assert doc["places_orders"] is False
    assert doc["live_socket"] is False
    assert doc["account_events_enabled"] is False
    assert "never places orders" in doc["note"].lower()


def test_finnhub_tape_skeleton_signals_only(tmp_path: Path) -> None:
    out = tmp_path / "finnhub_tape.json"
    assert finnhub_tape_main(["--output", str(out), "--symbol", "SPY"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["mode"] == "signals_only"


def test_p1_p2_skeletons_offline_no_orders(tmp_path: Path) -> None:
    alerts = tmp_path / "flow_alerts.json"
    assert flow_alerts_main(["--state", str(alerts)]) == 0
    assert json.loads(alerts.read_text())["places_orders"] is False
    assert json.loads(alerts.read_text())["live_http"] is False

    tide = tmp_path / "tide_state.json"
    assert tide_state_main(["--state", str(tide)]) == 0
    tide_doc = json.loads(tide.read_text())
    assert tide_doc["emits_sit_match"] is False
    assert tide_doc["live_http"] is False

    interest = tmp_path / "quote_interest.json"
    assert quote_interest_main(["--state", str(interest)]) == 0
    qdoc = json.loads(interest.read_text())
    assert qdoc["live_socket"] is False
    assert qdoc["host_owned_tape"] == "ws_tape.py"

    screener = tmp_path / "screener_state.json"
    assert screener_snapshot_main(["--state", str(screener)]) == 0
    assert json.loads(screener.read_text())["emits_sit_match"] is False

    marks = tmp_path / "shadow_marks.json"
    assert shadow_marks_main(["--state", str(marks)]) == 0
    assert json.loads(marks.read_text())["pnl"] is None

    probe = tmp_path / "uw_ws.json"
    assert uw_ws_probe_main(["--state", str(probe)]) == 2
    probe_doc = json.loads(probe.read_text())
    assert probe_doc["ok"] is False
    assert probe_doc["invents_protocol"] is False
    assert probe_doc["live_socket"] is False


def test_replay_scorecard_cli_offline(tmp_path: Path) -> None:
    from groktrading.flow_ledger import FlowLedger
    from groktrading.timeutil import UTC

    now = __import__("datetime").datetime(2026, 9, 9, 16, 30, tzinfo=UTC)
    ledger_path = tmp_path / "flow.sqlite"

    class Clock:
        def now(self) -> object:
            return now

    ledger = FlowLedger(ledger_path, clock=Clock())  # type: ignore[arg-type]
    ledger.append_row(
        {
            "executed_at": "2026-09-09T16:29:40Z",
            "ticker": "NVDA",
            "occ": "NVDA260918P00170000",
            "print": "1.00",
            "nbbo_ask": "1.05",
            "option_type": "put",
        }
    )
    out = tmp_path / "scorecard.json"
    assert replay_scorecard_main(["--ledger", str(ledger_path), "--output", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["first_print"] == 1
    assert doc["pnl"] is None
    missing = tmp_path / "missing.sqlite"
    assert replay_scorecard_main(["--ledger", str(missing), "--output", str(out)]) == 2
