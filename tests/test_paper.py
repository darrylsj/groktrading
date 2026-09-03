from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from groktrading.models import PaperFillArtifact
from groktrading.paper import PaperLedger
from groktrading.timeutil import PT


def test_sandbox_vs_production_reconciliation(tmp_path: Path) -> None:
    now = datetime(2026, 9, 3, 8, 0, tzinfo=PT)
    ledger = PaperLedger(path=tmp_path / "paper.json", session=now.date())
    artifact = PaperFillArtifact(
        signal_id="sig-99",
        option_symbol="SPY260903C00600000",
        sandbox_fill_price=Decimal("1.40"),
        production_nbbo_ask=Decimal("1.25"),
        production_nbbo_bid=Decimal("1.20"),
        previewed=True,
        recorded_ts=now,
    )
    ledger.record(artifact, now)
    report = ledger.reconcile(artifact)
    assert report["signal_id"] == "sig-99"
    assert report["sandbox_minus_production_ask"] == "0.15"
    assert "Not P&L" in report["disclaimer"]
    ledger.mark_terminal("sig-99", now)
    assert ledger.artifacts[0].terminal is True
    assert (tmp_path / "paper.json").exists()


def test_preview_and_same_day_required(tmp_path: Path) -> None:
    now = datetime(2026, 9, 3, 8, 0, tzinfo=PT)
    ledger = PaperLedger(path=tmp_path / "paper.json", session=now.date())
    bare = PaperFillArtifact(
        signal_id="sig-1",
        option_symbol="X",
        sandbox_fill_price=None,
        production_nbbo_ask=Decimal("1"),
        production_nbbo_bid=Decimal("1"),
        previewed=False,
        recorded_ts=now,
    )
    with pytest.raises(ValueError, match="preview"):
        ledger.record(bare, now)
    next_day = datetime(2026, 9, 4, 8, 0, tzinfo=PT)
    ok = bare.model_copy(update={"previewed": True})
    with pytest.raises(ValueError, match="same-day"):
        ledger.record(ok, next_day)
