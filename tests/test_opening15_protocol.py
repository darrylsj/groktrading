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
) -> dict[str, Any]:
    return {
        "paper_only": True,
        "session": session,
        "packet_hash": f"hash-{session}",
        "selected_count": k,
        "selected_net_before_api_and_infra_usd": model_net,
        "baselines": {
            "k": k,
            "model_net_usd": model_net,
            "random_k": {"percentile": percentile},
            "mechanical_top_k_ask_side_premium": {"net_usd": mechanical_net},
            "abstain": {"selected_count": 0, "net_usd": 0.0},
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
        [{"paper_only": True, "selected_net_before_api_and_infra_usd": 1, "session": "x"}]
        * 5
    )
    assert result["verdict"] == "insufficient"


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
