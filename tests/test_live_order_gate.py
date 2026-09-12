from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from groktrading.timeutil import PT
from helpers import morning_pt
from tools.live_order_gate.cli import main as gate_main
from tools.live_order_gate.gate import (
    PolicyError,
    assert_submit_policy,
    build_tradier_form_from_thesis,
    close_with_audit,
    evaluate_close_policy,
    evaluate_submit_policy,
    write_thesis,
)

# Fixture OCC / limits only. Not live fills. Not Friday QQQ.
_OCC = "SPY260903C00600000"
_ENTRY_LIMIT = Decimal("1.25")
_EXIT_LIMIT = Decimal("1.40")


def _entry_written(now: datetime | None = None) -> datetime:
    stamp = now or morning_pt()
    return stamp - timedelta(minutes=5)


def _entry_kwargs(now: datetime | None = None, **overrides: object) -> dict[str, object]:
    stamp = now or morning_pt()
    data: dict[str, object] = {
        "signal_id": "sig1",
        "option_symbol": _OCC,
        "side": "buy_to_open",
        "limit": _ENTRY_LIMIT,
        "strategy": "must_trade_small",
        "thesis": "I1 clearer. Do not sell credit. Exit if thesis dead.",
        "written_at": _entry_written(stamp),
        "intent": "entry",
        "underlying": "SPY",
        "falsifier": "bid <= 0.80 or thesis dead",
    }
    data.update(overrides)
    return data


def _exit_kwargs(now: datetime | None = None, **overrides: object) -> dict[str, object]:
    stamp = now or morning_pt()
    data: dict[str, object] = {
        "signal_id": "sig1stc",
        "option_symbol": _OCC,
        "side": "sell_to_close",
        "limit": _EXIT_LIMIT,
        "strategy": "take_gain_exit",
        "thesis": "Take-gain ratchet. Entry was a debit, not a credit.",
        "written_at": stamp,
        "intent": "exit",
        "parent_signal_id": "sig1",
        "underlying": "SPY",
        "falsifier": "bid <= protect",
    }
    data.update(overrides)
    return data


def test_stc_close_dry_run_from_exit_thesis() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    audit = close_with_audit(ticket, now=now, preview=True)
    assert audit["allowed"] is True
    assert audit["places_orders"] is False
    assert audit["dry_run"] is True
    assert audit["skipped_entry_cutoff"] is True
    assert audit["skipped_cash_debit"] is True
    form = audit["form"]
    assert form is not None
    assert form["side"] == "sell_to_close"
    assert form["option_symbol"] == _OCC
    assert form["quantity"] == "1"
    assert form["price"] == "1.40"
    assert form["tag"] == "sig1stc"
    assert form["preview"] == "true"
    assert form["class"] == "option"


def test_close_after_entry_cutoff_still_allowed() -> None:
    now = datetime(2026, 9, 3, 12, 45, tzinfo=PT)
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    form = close_with_audit(ticket, now=now)["form"]
    assert form is not None
    assert form["side"] == "sell_to_close"


def test_refuse_bto_after_cutoff_still() -> None:
    now = datetime(2026, 9, 3, 12, 30, tzinfo=PT)
    ticket = write_thesis(**_entry_kwargs(now, written_at=now - timedelta(minutes=2)))  # type: ignore[arg-type]
    decision = evaluate_submit_policy(ticket, now=now, cash=Decimal("600"))
    assert decision.allowed is False
    assert "entry_cutoff" in decision.reasons
    with pytest.raises(PolicyError, match="entry_cutoff"):
        assert_submit_policy(ticket, now=now, cash=Decimal("600"))


def test_bto_before_cutoff_builds_form() -> None:
    now = morning_pt()
    ticket = write_thesis(**_entry_kwargs(now))  # type: ignore[arg-type]
    form = assert_submit_policy(ticket, now=now, cash=Decimal("600"))
    assert form["side"] == "buy_to_open"
    assert form["price"] == "1.25"
    assert form["tag"] == "sig1"


def test_refuse_stc_without_thesis() -> None:
    now = morning_pt()
    decision = evaluate_close_policy(None, now=now)
    assert decision.allowed is False
    assert "thesis_required" in decision.reasons
    with pytest.raises(PolicyError, match="thesis_required"):
        close_with_audit(None, now=now)


def test_credit_and_sto_still_banned_on_entry() -> None:
    now = morning_pt()
    with pytest.raises(PolicyError) as exc:
        write_thesis(**_entry_kwargs(now, side="sell_to_open", strategy="credit_spread"))  # type: ignore[arg-type]
    assert exc.value.code == "credit_or_sto_banned"
    sto = {
        "signal_id": "sto1",
        "option_symbol": _OCC,
        "side": "sell_to_open",
        "quantity": 1,
        "limit": "1.25",
        "strategy": "must_trade_small",
        "thesis": "naked short",
        "written_at": _entry_written(now).isoformat(),
        "intent": "entry",
        "tag": "sto1",
    }
    decision = evaluate_submit_policy(sto, now=now, cash=Decimal("600"))
    assert decision.allowed is False
    banned = {"credit_or_sto_banned", "entry_side_must_be_bto"}
    assert banned.intersection(decision.reasons)


def test_write_thesis_exit_side_not_credit_ban_false_positive() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    assert ticket.side == "sell_to_close"
    assert ticket.strategy == "take_gain_exit"
    # Prose mentioning credit/sell must not trip the structural ban.
    assert "credit" in ticket.thesis.lower()


def test_exit_skips_cash_debit_even_when_cash_is_zero() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    # close_with_audit has no cash argument — debit check is not applied.
    audit = close_with_audit(ticket, now=now)
    assert audit["allowed"] is True
    assert audit["skipped_cash_debit"] is True


def test_entry_still_requires_cash_and_refuses_short_cash() -> None:
    now = morning_pt()
    ticket = write_thesis(**_entry_kwargs(now))  # type: ignore[arg-type]
    missing = evaluate_submit_policy(ticket, now=now, cash=None)
    assert missing.allowed is False
    assert "cash_required" in missing.reasons
    short = evaluate_submit_policy(ticket, now=now, cash=Decimal("50"))
    assert short.allowed is False
    assert "insufficient_cash" in short.reasons


def test_refuse_exit_thesis_on_submit_reentry() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    decision = evaluate_submit_policy(ticket, now=now, cash=Decimal("600"))
    assert decision.allowed is False
    assert "exit_thesis_not_for_submit" in decision.reasons


def test_refuse_already_closed_and_missing_parent() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    closed = evaluate_close_policy(ticket, now=now, closed_signal_ids={"sig1"})
    assert closed.allowed is False
    assert "already_closed" in closed.reasons
    orphan = write_thesis(**_exit_kwargs(now, signal_id="orphan1", parent_signal_id=None))  # type: ignore[arg-type]
    missing = evaluate_close_policy(orphan, now=now)
    assert missing.allowed is False
    assert "parent_signal_id_required" in missing.reasons


def test_tag_must_be_alphanumeric() -> None:
    now = morning_pt()
    with pytest.raises(PolicyError) as exc:
        write_thesis(**_entry_kwargs(now, signal_id="sig-1", tag="sig-1"))  # type: ignore[arg-type]
    assert exc.value.code == "tag_not_alphanumeric"


def test_entry_thesis_ttl_and_prior_session() -> None:
    now = datetime(2026, 9, 3, 11, 0, tzinfo=PT)
    stale = write_thesis(
        **_entry_kwargs(
            now,
            written_at=datetime(2026, 9, 3, 2, 0, tzinfo=PT),
            signal_id="old1",
            tag="old1",
        )
    )  # type: ignore[arg-type]
    decision = evaluate_submit_policy(stale, now=now, cash=Decimal("600"))
    assert decision.allowed is False
    assert "thesis_ttl_expired" in decision.reasons
    prior = write_thesis(
        **_entry_kwargs(
            now,
            written_at=datetime(2026, 9, 2, 10, 0, tzinfo=PT),
            signal_id="yday1",
            tag="yday1",
        )
    )  # type: ignore[arg-type]
    prior_decision = evaluate_submit_policy(prior, now=now, cash=Decimal("600"))
    assert prior_decision.allowed is False
    assert "thesis_prior_session" in prior_decision.reasons


def test_form_json_optional_must_match_thesis() -> None:
    now = morning_pt()
    ticket = write_thesis(**_exit_kwargs(now))  # type: ignore[arg-type]
    expected = build_tradier_form_from_thesis(ticket, preview=True)
    ok = close_with_audit(ticket, now=now, form=expected)
    assert ok["allowed"] is True
    bad = dict(expected)
    bad["side"] = "buy_to_open"
    mismatch = evaluate_close_policy(ticket, now=now, form=bad)
    assert mismatch.allowed is False
    assert "form_thesis_mismatch" in mismatch.reasons


def test_cli_close_dry_run_and_submit_cutoff(tmp_path: Path) -> None:
    now = morning_pt()
    exit_path = tmp_path / "exit.json"
    write_thesis(**_exit_kwargs(now), path=exit_path)  # type: ignore[arg-type]
    assert (
        gate_main(
            ["close", "--thesis", str(exit_path), "--now", now.isoformat()]
        )
        == 0
    )

    form_path = tmp_path / "form.json"
    form_path.write_text(
        json.dumps(build_tradier_form_from_thesis(write_thesis(**_exit_kwargs(now))))  # type: ignore[arg-type]
        + "\n"
    )
    assert (
        gate_main(
            [
                "close",
                "--thesis",
                str(exit_path),
                "--form-json",
                str(form_path),
                "--now",
                now.isoformat(),
            ]
        )
        == 0
    )

    cutoff = datetime(2026, 9, 3, 12, 31, tzinfo=PT)
    entry_path = tmp_path / "entry.json"
    write_thesis(
        **_entry_kwargs(cutoff, written_at=cutoff - timedelta(minutes=3)),  # type: ignore[arg-type]
        path=entry_path,
    )
    assert (
        gate_main(
            [
                "submit",
                "--thesis",
                str(entry_path),
                "--cash",
                "600",
                "--now",
                cutoff.isoformat(),
            ]
        )
        == 2
    )
