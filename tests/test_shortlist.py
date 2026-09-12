"""Shortlist ranker contract. No secrets. No invented live prices."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from groktrading.flow_ledger import FlowLedger
from groktrading.policy import MUST_TRADE_SMALL_ASK_CAP
from groktrading.shortlist import (
    HARD_SKIP_UNDERLYINGS,
    HOST_SHORTLIST_PATH,
    MAX_CANDIDATES,
    PREMIUM_BAND_HI,
    PREMIUM_BAND_LO,
    REASON_EMPTY,
    REASON_IN_POSITION_CLEARED,
    REASON_SCHEMA,
    REASON_STALE_SHORTLIST,
    SCHEMA_ID,
    SKIP_ALREADY_RUN,
    SKIP_HARD,
    SKIP_INTC_PUT,
    SKIP_PREMIUM,
    SKIP_SPCX,
    SKIP_STALE_PRINT,
    SKIP_UNPARSEABLE_PREMIUM,
    classify_print,
    evaluate_shortlist_document,
    extract_premium,
    extract_prints,
    main,
    parse_shortlist_document,
    rank_prints,
    session_filters_from_mapping,
    shortlist_cadence_sec,
    shortlist_max_print_age_sec,
    write_shortlist,
)
from groktrading.sit_match import DEFAULT_SIT_MATCH_MAX_AGE_SEC, executed_at_iso
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 12, 16, 30, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "shortlist.json").read_text(encoding="utf-8"))


def _print(
    *,
    occ: str = "QQQ260912P00717000",
    ticker: str = "QQQ",
    executed_at: datetime | None = None,
    age_sec: float = 12.0,
    ask: str = "1.06",
    option_type: str = "put",
    already_run: bool = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    stamp = executed_at if executed_at is not None else NOW - timedelta(seconds=age_sec)
    row: dict[str, object] = {
        "occ": occ,
        "ticker": ticker,
        "executed_at": executed_at_iso(stamp),
        "nbbo_ask": ask,
        "option_type": option_type,
        "source": "option-trades",
        "already_run": already_run,
    }
    if extra:
        row.update(extra)
    return row


def test_schema_constants_are_stable() -> None:
    assert SCHEMA["title"] == "Shortlist"
    assert SCHEMA["properties"]["schema"]["const"] == SCHEMA_ID
    assert SCHEMA["properties"]["emit_sit_match"]["const"] is False
    assert SCHEMA["properties"]["cadence_sec"]["minimum"] == 5
    assert SCHEMA["properties"]["cadence_sec"]["maximum"] == 15
    assert SCHEMA["properties"]["candidates"]["maxItems"] == MAX_CANDIDATES
    assert HOST_SHORTLIST_PATH == "/opt/trading-desk/state/shortlist.json"
    assert PREMIUM_BAND_LO == Decimal("0.80")
    assert PREMIUM_BAND_HI == MUST_TRADE_SMALL_ASK_CAP == Decimal("1.50")
    assert HARD_SKIP_UNDERLYINGS == frozenset({"META", "NET", "MU", "AMD"})


def test_ranker_writes_schema_stable_document(tmp_path: Path) -> None:
    doc = rank_prints([_print()], NOW)
    path = tmp_path / "shortlist.json"
    write_shortlist(path, doc)
    raw = json.loads(path.read_text(encoding="utf-8"))
    parsed = parse_shortlist_document(raw)
    assert parsed is not None
    assert raw["schema"] == SCHEMA_ID
    assert raw["kind"] == "shortlist"
    assert raw["emit_sit_match"] is False
    assert raw["empty_reason"] is None
    assert len(raw["candidates"]) == 1
    assert raw["candidates"][0]["occ"] == "QQQ260912P00717000"
    assert set(SCHEMA["required"]) <= set(raw)
    assert set(raw) == set(SCHEMA["required"])
    cand_required = set(SCHEMA["$defs"]["candidate"]["required"])
    assert set(raw["candidates"][0]) == cand_required


def test_stale_print_is_refused() -> None:
    stale = _print(age_sec=61)
    candidate, reason = classify_print(stale, NOW, max_age_sec=60)
    assert candidate is None
    assert reason == SKIP_STALE_PRINT
    doc = rank_prints([stale], NOW, max_age_sec=60)
    assert doc.candidates == []
    assert doc.empty_reason == "no_fresh_prints"


def test_missing_executed_at_is_refused() -> None:
    row = _print()
    del row["executed_at"]
    candidate, reason = classify_print(row, NOW, max_age_sec=60)
    assert candidate is None
    assert reason == "missing_executed_at"


def test_optional_tighten_15s_refuses_20s_print() -> None:
    row = _print(age_sec=20)
    assert classify_print(row, NOW, max_age_sec=60)[0] is not None
    candidate, reason = classify_print(row, NOW, max_age_sec=15)
    assert candidate is None
    assert reason == SKIP_STALE_PRINT


def test_max_print_age_never_widens_past_i1() -> None:
    assert shortlist_max_print_age_sec({}) == DEFAULT_SIT_MATCH_MAX_AGE_SEC
    assert shortlist_max_print_age_sec({"SHORTLIST_MAX_AGE_SEC": "20"}) == 20.0
    assert shortlist_max_print_age_sec({"SHORTLIST_MAX_AGE_SEC": "300"}) == 60.0
    widened = {"SIT_MATCH_MAX_AGE_SEC": "60", "SHORTLIST_MAX_AGE_SEC": "90"}
    assert shortlist_max_print_age_sec(widened) == 60.0
    assert shortlist_max_print_age_sec({"SHORTLIST_MAX_AGE_SEC": "inf"}) is None


def test_cadence_clamps_to_5_15() -> None:
    assert shortlist_cadence_sec({}) == 10.0
    assert shortlist_cadence_sec({"SHORTLIST_CADENCE_SEC": "5"}) == 5.0
    assert shortlist_cadence_sec({"SHORTLIST_CADENCE_SEC": "15"}) == 15.0
    assert shortlist_cadence_sec({"SHORTLIST_CADENCE_SEC": "1"}) == 5.0
    assert shortlist_cadence_sec({"SHORTLIST_CADENCE_SEC": "60"}) == 15.0


def test_hard_skips_and_spcx_and_intc_puts() -> None:
    cases = [
        (_print(occ="META260918C00500000", ticker="META", option_type="call"), SKIP_HARD),
        (_print(occ="NET260918C00100000", ticker="NET", option_type="call"), SKIP_HARD),
        (_print(occ="MU260918C00100000", ticker="MU", option_type="call"), SKIP_HARD),
        (_print(occ="AMD260918C00100000", ticker="AMD", option_type="call"), SKIP_HARD),
        (_print(occ="SPCX260918P00145000", ticker="SPCX", option_type="put"), SKIP_SPCX),
        (_print(occ="INTC260918P00035000", ticker="INTC", option_type="put"), SKIP_INTC_PUT),
    ]
    for row, expected in cases:
        candidate, reason = classify_print(row, NOW, max_age_sec=60)
        assert candidate is None, row
        assert reason == expected, row
    intc_call = _print(occ="INTC260918C00035000", ticker="INTC", option_type="call")
    candidate, reason = classify_print(intc_call, NOW, max_age_sec=60)
    assert reason is None
    assert candidate is not None
    assert candidate.underlying == "INTC"


def test_premium_band_is_per_share_not_uw_notional() -> None:
    assert extract_premium({"premium": "10000", "nbbo_ask": "1.10"}) == Decimal("1.10")
    cheap = classify_print(_print(ask="0.79"), NOW, max_age_sec=60)
    rich = classify_print(_print(ask="1.51"), NOW, max_age_sec=60)
    mid = classify_print(_print(ask="1.06"), NOW, max_age_sec=60)
    assert cheap[1] == SKIP_PREMIUM
    assert rich[1] == SKIP_PREMIUM
    assert mid[0] is not None
    notional_only = _print(extra={"premium": "25000"})
    del notional_only["nbbo_ask"]
    assert classify_print(notional_only, NOW, max_age_sec=60)[1] == SKIP_UNPARSEABLE_PREMIUM


def test_already_run_and_in_position_when_detectable() -> None:
    flagged = classify_print(_print(already_run=True), NOW, max_age_sec=60)
    assert flagged[1] == SKIP_ALREADY_RUN
    session = session_filters_from_mapping(
        {"already_run_underlyings": ["QQQ"]},
        {"occs": ["SPY260912C00450000"]},
    )
    assert classify_print(_print(), NOW, max_age_sec=60, session=session)[1] == SKIP_ALREADY_RUN
    spy = _print(occ="SPY260912C00450000", ticker="SPY", option_type="call")
    assert classify_print(spy, NOW, max_age_sec=60, session=session)[1] == "in_position"
    other = _print(occ="IWM260912P00200000", ticker="IWM", option_type="put")
    assert classify_print(other, NOW, max_age_sec=60, session=session)[0] is not None


def test_ranker_caps_at_three_newest_unique_occs() -> None:
    rows = [
        _print(occ="QQQ260912P00717000", age_sec=5),
        _print(occ="SPY260912P00580000", ticker="SPY", age_sec=8),
        _print(occ="IWM260912P00200000", ticker="IWM", age_sec=9),
        _print(occ="TQQQ260912P00050000", ticker="TQQQ", age_sec=10),
        _print(occ="QQQ260912P00717000", age_sec=4, ask="1.07"),
    ]
    doc = rank_prints(rows, NOW, max_age_sec=60)
    occs = [row.occ for row in doc.candidates]
    assert len(occs) == 3
    assert occs[0] == "QQQ260912P00717000"
    assert "TQQQ260912P00050000" not in occs


def test_consume_refuses_stale_and_empty_shortlist() -> None:
    fresh = rank_prints([_print()], NOW).as_dict()
    ok = evaluate_shortlist_document(fresh, NOW, stale_sec=30)
    assert ok.allow
    assert ok.reason is None
    stale = evaluate_shortlist_document(fresh, NOW + timedelta(seconds=31), stale_sec=30)
    assert stale.allow is False
    assert stale.reason == REASON_STALE_SHORTLIST
    empty = rank_prints([], NOW, had_input=False).as_dict()
    refused = evaluate_shortlist_document(empty, NOW, stale_sec=30)
    assert refused.allow is False
    assert refused.reason == REASON_EMPTY


def test_consume_refuses_in_position_race() -> None:
    doc = rank_prints([_print()], NOW).as_dict()
    held = session_filters_from_mapping(None, {"occs": ["QQQ260912P00717000"]})
    result = evaluate_shortlist_document(doc, NOW, stale_sec=30, session=held)
    assert result.allow is False
    assert result.reason == REASON_IN_POSITION_CLEARED


def test_consume_refuses_bad_schema() -> None:
    result = evaluate_shortlist_document({"kind": "nope"}, NOW)
    assert result.allow is False
    assert result.reason == REASON_SCHEMA


def test_min_interval_is_not_a_ranker_clock() -> None:
    env = {"SIT_MATCH_MIN_INTERVAL_SEC": "300", "SIT_MATCH_MAX_AGE_SEC": "60"}
    assert shortlist_max_print_age_sec(env) == 60.0
    row = _print(age_sec=20)
    candidate, _reason = classify_print(row, NOW, max_age_sec=shortlist_max_print_age_sec(env))
    assert candidate is not None


def test_extract_prints_does_not_invent_unknown_tape() -> None:
    assert extract_prints({"hello": "world"}) == []
    assert extract_prints({"prints": [_print()]})[0]["occ"] == "QQQ260912P00717000"


def test_cli_offline_skeleton_and_prints(tmp_path: Path, monkeypatch: object) -> None:
    out = tmp_path / "shortlist.json"
    monkeypatch.delenv("SHORTLIST_PATH", raising=False)  # type: ignore[attr-defined]
    assert main(["--out", str(out)]) == 0
    empty = json.loads(out.read_text(encoding="utf-8"))
    assert empty["candidates"] == []
    assert empty["empty_reason"] == "no_input"
    assert empty["emit_sit_match"] is False

    prints = tmp_path / "prints.json"
    prints.write_text(json.dumps([_print()]), encoding="utf-8")
    clock = executed_at_iso(NOW)
    assert main(["--prints", str(prints), "--out", str(out), "--now", clock]) == 0
    filled = json.loads(out.read_text(encoding="utf-8"))
    assert len(filled["candidates"]) == 1

    monkeypatch.setenv("SHORTLIST_MAX_AGE_SEC", "inf")  # type: ignore[attr-defined]
    assert main(["--prints", str(prints), "--out", str(out), "--now", clock]) == 2


def test_ledger_input_without_network(tmp_path: Path) -> None:
    ledger_path = tmp_path / "uw_flow.sqlite"
    ledger = FlowLedger(ledger_path)
    ledger.append_row(
        {
            "executed_at": executed_at_iso(NOW - timedelta(seconds=8)),
            "ticker": "QQQ",
            "occ": "QQQ260912P00717000",
            "print": "1.06",
            "nbbo_ask": "1.06",
            "option_type": "put",
        },
        source="option-trades",
        ingested_at=NOW,
    )
    out = tmp_path / "shortlist.json"
    clock = executed_at_iso(NOW)
    assert main(["--ledger", str(ledger_path), "--out", str(out), "--now", clock]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["candidates"][0]["occ"] == "QQQ260912P00717000"
