from __future__ import annotations

import json
from pathlib import Path

from groktrading.cli import account_events_main, finnhub_tape_main, tape_skeleton_main


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
