from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from tools.gex_shadow.score_gex_pair import (
    LIVE_GATE,
    load_records,
    main,
    parse_pair_record,
    score_gex_pairs,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gex_shadow" / "pair_fixture.jsonl"


def test_fixture_is_labeled_synthetic_not_invented() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert "invented=false" in text or '"invented":false' in text.replace(" ", "")
    assert "fixture=true" in text or '"fixture":true' in text.replace(" ", "")
    assert "Not live NBBO" in text
    rows = load_records(FIXTURE)
    assert rows
    for row in rows:
        assert row.get("invented") is False
        assert row.get("fixture") is True


def test_fixture_pair_score_baseline_vs_agree_coverage() -> None:
    rows = load_records(FIXTURE)
    doc = score_gex_pairs(rows, horizon_min=60)
    assert doc["live_gate"] is False
    assert doc["live_gate"] is LIVE_GATE
    assert doc["invented"] is False
    assert doc["places_orders"] is False
    assert doc["horizon_min"] == 60
    # First SPY / QQQ / IWM scored; DIA missing mark; duplicate SPY dropped.
    assert doc["coverage"]["unique_occ"] == 4
    assert doc["coverage"]["scored"] == 3
    assert doc["coverage"]["unscored_missing_mark"] == 1
    assert doc["coverage"]["duplicate_occ_dropped"] == 1
    assert doc["coverage"]["coverage_ratio"] == str(Decimal("3") / Decimal("4"))
    # SPY +15, QQQ -20, IWM +5 → sum 0; hits 2/3
    assert doc["baseline"]["n_scored"] == 3
    assert doc["baseline"]["hits"] == 2
    assert doc["baseline"]["one_lot_usd_sum"] == "0.00"
    assert doc["agree_only"]["n_scored"] == 2
    assert doc["agree_only"]["hits"] == 1
    assert doc["agree_only"]["one_lot_usd_sum"] == "-5.00"


def test_missing_mark_unscored_never_invented() -> None:
    rec = parse_pair_record(
        {
            "occ": "META260918C00700000",
            "decision_ask": "1.00",
            "gex": "agree",
            "invented": False,
            "fixture": True,
        }
    )
    assert rec is not None
    assert rec.scored is False
    assert rec.skip_reason == "missing_mark"
    assert rec.one_lot_usd() is None


def test_invented_true_is_unscored() -> None:
    rec = parse_pair_record(
        {
            "occ": "AAPL260918C00200000",
            "decision_ask": "1.00",
            "mark_bid": "2.00",
            "gex": "agree",
            "invented": True,
        }
    )
    assert rec is not None
    assert rec.skip_reason == "invented_mark"
    doc = score_gex_pairs(
        [
            {
                "occ": "AAPL260918C00200000",
                "decision_ask": "1.00",
                "mark_bid": "2.00",
                "gex": "agree",
                "invented": True,
            }
        ]
    )
    assert doc["live_gate"] is False
    assert doc["baseline"]["n_scored"] == 0
    assert doc["coverage"]["unscored_invented"] == 1


def test_cli_fixture_and_horizon(tmp_path: Path) -> None:
    out = tmp_path / "gex.json"
    assert (
        main(
            ["--input", str(FIXTURE), "--horizon-min", "60", "--out", str(out)]
        )
        == 0
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["live_gate"] is False
    assert doc["horizon_min"] == 60
    assert main(["--input", str(FIXTURE), "--horizon-min", "0"]) == 2
