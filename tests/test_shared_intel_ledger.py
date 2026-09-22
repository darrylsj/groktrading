"""Local shared-intel append. Does not SSH."""

from __future__ import annotations

import json
from pathlib import Path

from tools.shared_intel.ledger import append_shared_trade, map_exit_reason


def test_map_exit_reason_aliases() -> None:
    assert map_exit_reason("take_gain_protect") == "take_gain"
    assert map_exit_reason("dead_thesis_exit") == "dead_thesis"
    assert map_exit_reason("operator flatten") == "flatten"


def test_append_local_trades_without_ssh(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "trades.jsonl"
    monkeypatch.setenv("SHARED_INTEL_LOCAL_TRADES", str(dest))
    monkeypatch.delenv("SHARED_INTEL_MIRROR_PATH", raising=False)
    result = append_shared_trade(
        {
            "trade_id": "t1",
            "ticker": "IWM",
            "occ_symbol": "IWM260923P00285000",
            "entry_price": 1.03,
            "exit_price": 0.94,
            "size": 1,
            "pnl_usd": -9.0,
            "exit_reason": "flatten",
            "setup": "continual15_shortlist",
        }
    )
    assert result["ok"] is True
    assert result["local"] is True
    assert result["setup"] == "continual15_shortlist"
    row = json.loads(dest.read_text(encoding="utf-8"))
    assert row["book"] == "tradier_live"
    assert row["secrets"] is False
    assert "72238" not in dest.read_text(encoding="utf-8")


def test_append_refuses_missing_fills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHARED_INTEL_LOCAL_TRADES", str(tmp_path / "trades.jsonl"))
    result = append_shared_trade({"ticker": "SPY", "exit_reason": "flatten"})
    assert result["ok"] is False
    assert result["error"].startswith("missing_required:")
