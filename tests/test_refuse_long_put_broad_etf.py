"""Trade Reviewer 2026-09-21: refuse_long_put_on_broad_etf at submit."""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal

import pytest

from helpers import morning_pt
from tools.live_order_gate.gate import (
    PolicyError,
    close_with_audit,
    emit_shared_intel_close,
    evaluate_submit_policy,
    refuse_long_put_on_broad_etf,
    write_thesis,
)


def _card(und: str, occ: str, side: str = "buy_to_open", **kwargs: object) -> dict:
    base: dict[str, object] = {
        "thesis_id": f"thesis_test_{und}_{occ[-8:]}",
        "written_at": "2026-09-21T20:00:00+00:00",
        "expires_at": time.time() + 600,
        "session": "2026-09-21",
        "strategy": "one_lot",
        "underlying": und,
        "legs": [{"occ": occ, "side": side, "qty": 1}],
        "side_summary": side,
        "limit": 1.03,
        "qty": 1.0,
        "thesis": "test",
        "gates": {"paper": False, "uw_print": 1.03, "recheck_ask": 1.04, "falsifier": "x"},
        "disagreement": "tape",
        "how_it_dies": "x",
        "invented": False,
        "secrets": False,
    }
    base.update(kwargs)
    return base


def _form(und: str, occ: str, side: str = "buy_to_open") -> dict[str, str]:
    return {
        "class": "option",
        "symbol": und,
        "option_symbol": occ,
        "side": side,
        "quantity": "1",
        "type": "limit",
        "price": "1.03",
    }


@pytest.mark.parametrize(
    ("und", "occ"),
    [
        ("IWM", "IWM260923P00285000"),
        ("SPY", "SPY260923P00570000"),
        ("QQQ", "QQQ260923P00480000"),
    ],
)
def test_bto_put_aborts(und: str, occ: str) -> None:
    with pytest.raises(PolicyError) as exc_info:
        refuse_long_put_on_broad_etf(_card(und, occ), _form(und, occ))
    assert exc_info.value.code == "refuse_long_put_on_broad_etf"
    assert "refuse_long_put_on_broad_etf" in str(exc_info.value)


def test_bto_call_allowed() -> None:
    refuse_long_put_on_broad_etf(
        _card("IWM", "IWM260923C00285000"),
        _form("IWM", "IWM260923C00285000"),
    )


def test_stc_put_exit_allowed() -> None:
    refuse_long_put_on_broad_etf(
        _card("IWM", "IWM260923P00285000", side="sell_to_close", strategy="exit_flatten"),
        _form("IWM", "IWM260923P00285000", side="sell_to_close"),
    )


def test_aapl_put_not_in_ban() -> None:
    refuse_long_put_on_broad_etf(
        _card("AAPL", "AAPL260923P00250000"),
        _form("AAPL", "AAPL260923P00250000"),
    )


def test_submit_policy_refuses_iwm_long_put() -> None:
    now = morning_pt()
    ticket = write_thesis(
        signal_id="iwmput1",
        option_symbol="IWM260923P00285000",
        side="buy_to_open",
        limit=Decimal("1.03"),
        strategy="must_trade_small",
        thesis="Broad ETF long put shape.",
        written_at=now - timedelta(minutes=5),
        intent="entry",
        underlying="IWM",
        falsifier="spot reclaims the level",
    )
    decision = evaluate_submit_policy(ticket, now=now, cash=Decimal("500"))
    assert decision.allowed is False
    assert "refuse_long_put_on_broad_etf" in decision.reasons


def test_close_emits_shared_intel_without_inventing_fills() -> None:
    now = morning_pt()
    ticket = write_thesis(
        signal_id="sig1stc",
        option_symbol="SPY260903C00600000",
        side="sell_to_close",
        limit=Decimal("1.40"),
        strategy="take_gain_exit",
        thesis="Flatten the long call.",
        written_at=now,
        intent="exit",
        parent_signal_id="sig1",
        underlying="SPY",
        falsifier="bid <= protect",
    )
    audit = close_with_audit(ticket, now=now, preview=True)
    assert audit["places_orders"] is False
    assert audit["shared_intel"]["ok"] is False
    assert audit["shared_intel"]["error"] == "missing_fills"

    filled = close_with_audit(
        ticket,
        now=now,
        preview=True,
        entry_fill=Decimal("1.25"),
        exit_fill=Decimal("1.40"),
    )
    shared = filled["shared_intel"]
    assert shared["ok"] is True
    assert shared["dry_run"] is True
    assert shared["trade"]["pnl_usd"] == 15.0
    assert shared["trade"]["side"] == "long_call"
    assert shared["trade"]["secrets"] is False


def test_emit_dry_run_does_not_call_appender() -> None:
    calls: list[dict] = []

    def _append(trade: dict) -> dict:
        calls.append(trade)
        return {"ok": True}

    result = emit_shared_intel_close(
        occ="QQQ260923P00480000",
        underlying="QQQ",
        entry_fill=1.0,
        exit_fill=0.9,
        exit_reason="flatten",
        opened_pt="2026-09-21 07:10 PT",
        closed_pt="2026-09-21 10:05 PT",
        dry_run=True,
        append=_append,
    )
    assert result["dry_run"] is True
    assert result["trade"]["side"] == "long_put"
    assert result["trade"]["pnl_usd"] == -10.0
    assert result["trade"]["time_of_day_bucket"] == "open"
    assert calls == []
