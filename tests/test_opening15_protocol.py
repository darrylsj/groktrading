from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from groktrading.research.protocol import (
    CONTINUE_MEAN_PERCENTILE,
    REQUIRED_SESSIONS,
    decide_protocol,
    protocol_from_paths,
)


def _report(
    session: str,
    model_net: float,
    mechanical_net: float,
    percentile: float,
    *,
    k: int = 1,
    synthetic: bool = False,
    experiment_id: str = "opening15-packet-baseline",
    prompt_version: str = "opening15-discretion-v1",
    universe: str = "packet_printed",
    policy_percentile: float | None = None,
) -> dict[str, Any]:
    same_k = None if k == 0 else percentile
    policy = policy_percentile if policy_percentile is not None else (
        same_k if k else percentile
    )
    return {
        "paper_only": True,
        "synthetic": synthetic,
        "session": session,
        "packet_hash": f"hash-{session}",
        "experiment_id": experiment_id,
        "requested_model": "gpt-6-astra",
        "recommend_backend": "codex_cli",
        "prompt_version": prompt_version,
        "selected_count": k,
        "selected_net_before_api_and_infra_usd": model_net,
        "arm": {
            "experiment_id": experiment_id,
            "requested_model": "gpt-6-astra",
            "recommend_backend": "codex_cli",
            "prompt_version": prompt_version,
            "universe": universe,
        },
        "baselines": {
            "k": k,
            "model_net_usd": model_net,
            "random_k": {
                "percentile": same_k,
                "seed": 20260908,
                "draws": 1000,
                "incomplete_draws": 0,
            },
            "mechanical_top_k_ask_side_premium": {"net_usd": mechanical_net},
            "abstain": {"selected_count": 0, "net_usd": 0.0},
            "fixed_k_values": [1, 2, 3],
            "fixed_k": {
                "1": {
                    "mechanical_net_usd": mechanical_net,
                    "random_k": {"percentile_of_zero": policy, "complete_draws": 1000},
                }
            },
            "scorecards": {
                "selection_quality_same_k": {
                    "defined": k > 0,
                    "random_k_percentile": same_k,
                },
                "policy_enter_or_abstain": {"policy_percentile": policy},
            },
        },
    }


def test_protocol_insufficient_under_five() -> None:
    result = decide_protocol([_report("2026-09-08", 10, 1, 80)])
    assert result["verdict"] == "insufficient"
    assert result["live_orders"] is False
    assert result["touches_live_gate_or_helsinki"] is False
    assert result["sessions_scoreable"] == 1


def test_protocol_kill_negative_and_low_percentile() -> None:
    reports = [
        _report(f"2026-09-0{i}", -10, 1, 20) for i in range(1, 6)
    ]
    result = decide_protocol(reports)
    assert result["verdict"] == "kill"
    assert any("kill:" in reason for reason in result["reasons"])


def test_protocol_kill_loses_to_mechanical_majority() -> None:
    reports = [_report(f"2026-09-0{i}", 1, 10, 55) for i in range(1, 6)]
    result = decide_protocol(reports)
    assert result["verdict"] == "kill"
    assert result["totals"]["losses_to_mechanical"] == 5


def test_protocol_continue_is_paper_only() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 6)]
    result = decide_protocol(reports)
    assert result["verdict"] == "continue"
    assert result["totals"]["mean_random_k_percentile"] >= CONTINUE_MEAN_PERCENTILE
    assert "never authorizes live" in " ".join(result["reasons"])
    assert result["continue_means"].startswith("more paper")


def test_protocol_inconclusive_mixed() -> None:
    reports = [
        _report("2026-09-01", 5, 4, 55),
        _report("2026-09-02", -1, 0, 52),
        _report("2026-09-03", 2, 3, 51),
        _report("2026-09-04", 1, 1, 50),
        _report("2026-09-05", 0, 0, 50),
    ]
    result = decide_protocol(reports)
    assert result["verdict"] == "inconclusive"
    assert "Do not go live" in " ".join(result["reasons"])


def test_protocol_ignores_sessions_after_five() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 6)]
    reports.append(_report("2026-09-08", -100, 0, 1))
    result = decide_protocol(reports)
    assert result["verdict"] == "continue"
    assert result["sessions_considered"] == REQUIRED_SESSIONS


def test_protocol_missing_baselines_not_scoreable() -> None:
    result = decide_protocol(
        [
            {
                "paper_only": True,
                "synthetic": False,
                "selected_net_before_api_and_infra_usd": 1,
                "session": f"2026-09-0{i}",
                "packet_hash": f"hash-{i}",
            }
            for i in range(1, 6)
        ]
    )
    assert result["verdict"] == "insufficient"


def test_protocol_rejects_five_copies_of_one_synthetic_day() -> None:
    one = _report("2026-09-08", 20, 1, 70, synthetic=True)
    result = decide_protocol([one] * 5)
    assert result["verdict"] == "rejected"
    assert result["live_orders"] is False
    assert result["touches_live_gate_or_helsinki"] is False
    blob = " ".join(result["reasons"]).lower()
    assert "synthetic" in blob
    assert "duplicate" in blob or "copies" in blob


def test_protocol_rejects_duplicate_real_sessions() -> None:
    result = decide_protocol([_report("2026-09-08", 20, 1, 70)] * 5)
    assert result["verdict"] == "rejected"
    assert any("duplicate" in reason.lower() for reason in result["reasons"])


def test_protocol_insufficient_when_only_one_random_percentile() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 6)]
    for report in reports[1:]:
        report["baselines"]["random_k"]["percentile"] = None
        report["baselines"]["scorecards"]["policy_enter_or_abstain"]["policy_percentile"] = None
        report["baselines"]["fixed_k"]["1"]["random_k"]["percentile_of_zero"] = None
    result = decide_protocol(reports)
    assert result["verdict"] == "insufficient"
    assert "percentile" in " ".join(result["reasons"]).lower()
    assert result["verdict"] != "continue"


def test_protocol_rejects_inconsistent_experiment_identity() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 6)]
    reports[2]["prompt_version"] = "selector_alt"
    reports[2]["arm"]["prompt_version"] = "selector_alt"
    result = decide_protocol(reports)
    assert result["verdict"] == "rejected"
    assert any("identity" in reason.lower() for reason in result["reasons"])


def test_protocol_rejects_missing_experiment_identity() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 6)]
    for key in ("experiment_id", "requested_model", "recommend_backend", "prompt_version"):
        reports[0].pop(key, None)
        reports[0]["arm"].pop(key, None)
    result = decide_protocol(reports)
    assert result["verdict"] == "rejected"
    assert any("missing" in reason.lower() for reason in result["reasons"])


def test_protocol_rejects_mixed_tuesday_and_expanded_arms() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 5)]
    reports.append(
        _report(
            "2026-09-09",
            20,
            1,
            70,
            experiment_id="opening15-expanded-select",
            prompt_version="selector_v2",
            universe="hygiene_shortlist",
        )
    )
    result = decide_protocol(reports)
    assert result["verdict"] == "rejected"
    blob = " ".join(result["reasons"]).lower()
    assert "identity" in blob
    assert "expanded" in blob or "baseline" in blob


def test_protocol_abstain_day_is_scoreable_via_fixed_k() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 5)]
    reports.append(_report("2026-09-09", 0, 0, 70, k=0))
    result = decide_protocol(reports)
    assert result["verdict"] != "insufficient"
    assert result["sessions_scoreable"] == 5
    abstain = next(item for item in result["sessions"] if item["session"] == "2026-09-09")
    assert abstain["k"] == 0
    assert abstain["random_k_percentile"] is None
    assert abstain["policy_percentile"] == 70


def test_protocol_abstain_without_fixed_k_is_insufficient() -> None:
    reports = [_report(f"2026-09-0{i}", 20, 1, 70) for i in range(1, 5)]
    bare = _report("2026-09-09", 0, 0, 70, k=0)
    bare["baselines"]["fixed_k"] = {}
    bare["baselines"]["scorecards"]["policy_enter_or_abstain"]["policy_percentile"] = None
    reports.append(bare)
    result = decide_protocol(reports)
    assert result["verdict"] == "insufficient"
    assert "percentile" in " ".join(result["reasons"]).lower()


def test_protocol_cli_reads_evaluation_files(tmp_path: Path, monkeypatch: Any) -> None:
    from groktrading.research import cli

    paths = []
    for i in range(5):
        path = tmp_path / f"s{i}"
        path.mkdir()
        (path / "evaluation.json").write_text(
            json.dumps(_report(f"2026-09-0{i + 1}", 20, 1, 70))
        )
        paths.append(path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "opening15",
            "protocol",
            "--output",
            str(tmp_path / "verdict"),
            "--sessions",
            *[str(p) for p in paths],
        ],
    )
    cli.main()
    verdict = json.loads((tmp_path / "verdict/protocol.json").read_text())
    assert verdict["verdict"] == "continue"
    assert protocol_from_paths(paths)["verdict"] == "continue"
