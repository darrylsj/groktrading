"""Pre-registered Opening15 paper decision protocol. Reads evaluate() output only.

No path into the live gate, order FSM, Helsinki units, or any broker. A continue
verdict means more paper sessions or a wider paper universe — never live orders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from groktrading.research.evaluation import RANDOM_K_DRAWS, RANDOM_K_SEED

REQUIRED_SESSIONS = 5
KILL_MEAN_PERCENTILE = 40.0
KILL_MAJORITY = 4
CONTINUE_MEAN_PERCENTILE = 60.0
Verdict = Literal["insufficient", "rejected", "kill", "continue", "inconclusive"]


def load_evaluation(path: Path) -> dict[str, Any]:
    target = path / "evaluation.json" if path.is_dir() else path
    payload: dict[str, Any] = json.loads(target.read_text())
    return payload


def _scoreable(report: dict[str, Any]) -> bool:
    if report.get("paper_only") is not True:
        return False
    if report.get("synthetic") is not False:
        return False
    if "baselines" not in report:
        return False
    if "selected_net_before_api_and_infra_usd" not in report:
        return False
    return report["selected_net_before_api_and_infra_usd"] is not None


def _experiment_identity(report: dict[str, Any]) -> tuple[Any, ...]:
    """Stable experiment fingerprint. Missing optional fields are None (must match)."""
    baselines = report.get("baselines") or {}
    random_k = baselines.get("random_k") or {}
    return (
        report.get("experiment_id"),
        report.get("requested_model"),
        report.get("recommend_backend"),
        report.get("prompt_version"),
        random_k.get("seed"),
        random_k.get("draws"),
    )


def _reject_invalid_inputs(reports: list[dict[str, Any]]) -> list[str]:
    """Return reject reasons. Duplicate or synthetic sets cannot yield kill/continue."""
    reasons: list[str] = []
    if any(report.get("synthetic") is True for report in reports):
        reasons.append(
            "rejected: synthetic evaluation(s) cannot produce kill/continue; "
            "use distinct real paper sessions only"
        )
    sessions = [report.get("session") for report in reports]
    hashes = [report.get("packet_hash") for report in reports]
    if any(item in (None, "") for item in sessions) or len(set(sessions)) != len(sessions):
        reasons.append(
            "rejected: sessions must be distinct real dates; "
            "duplicate or missing session identity is not a five-session block"
        )
    if any(item in (None, "") for item in hashes) or len(set(hashes)) != len(hashes):
        reasons.append(
            "rejected: packet_hash values must be distinct; "
            "five copies of one day are not five sessions"
        )
    identities = [_experiment_identity(report) for report in reports]
    if identities and len(set(identities)) != 1:
        reasons.append(
            "rejected: inconsistent experiment identity across the set "
            "(experiment_id / model / backend / prompt_version / random-K seed and draws)"
        )
    return reasons


def _session_metrics(report: dict[str, Any]) -> dict[str, Any]:
    baselines = report["baselines"]
    mechanical = baselines.get("mechanical_top_k_ask_side_premium") or {}
    random_k = baselines.get("random_k") or {}
    return {
        "session": report.get("session"),
        "packet_hash": report.get("packet_hash"),
        "model_net_usd": report["selected_net_before_api_and_infra_usd"],
        "mechanical_net_usd": mechanical.get("net_usd"),
        "random_k_percentile": random_k.get("percentile"),
        "k": baselines.get("k", report.get("selected_count")),
        "abstain_net_usd": (baselines.get("abstain") or {}).get("net_usd", 0.0),
    }


def decide_protocol(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the pre-registered five-session rule. Extra reports after five are ignored."""
    considered = reports[:REQUIRED_SESSIONS]
    reject_reasons = _reject_invalid_inputs(considered)
    if reject_reasons:
        return _result("rejected", reject_reasons, [], considered)
    scoreable = [report for report in considered if _scoreable(report)]
    metrics = [_session_metrics(report) for report in scoreable]
    reasons: list[str] = []
    if len(scoreable) < REQUIRED_SESSIONS:
        verdict: Verdict = "insufficient"
        reasons.append(
            f"{len(scoreable)} scoreable session(s) of {REQUIRED_SESSIONS} required; "
            "do not act. Collect more paper sessions."
        )
        return _result(verdict, reasons, metrics, considered)

    model_total = round(sum(float(item["model_net_usd"]) for item in metrics), 4)
    mechanical_known = [
        item for item in metrics if item["mechanical_net_usd"] is not None
    ]
    mechanical_total = round(
        sum(float(item["mechanical_net_usd"]) for item in mechanical_known), 4
    )
    percentiles = [
        float(item["random_k_percentile"])
        for item in metrics
        if item["random_k_percentile"] is not None
    ]
    if (
        len(percentiles) < REQUIRED_SESSIONS
        or len(mechanical_known) < REQUIRED_SESSIONS
    ):
        reasons.append(
            f"insufficient: need {REQUIRED_SESSIONS} known random-K percentiles and "
            f"{REQUIRED_SESSIONS} mechanical nets; got {len(percentiles)} percentile(s) "
            f"and {len(mechanical_known)} mechanical mark(s). Do not kill or continue."
        )
        return _result("insufficient", reasons, metrics, considered)
    mean_percentile = (
        round(sum(percentiles) / len(percentiles), 4) if percentiles else None
    )
    losses_to_mechanical = sum(
        1
        for item in mechanical_known
        if float(item["model_net_usd"]) < float(item["mechanical_net_usd"])
    )
    losses_to_random = sum(
        1
        for item in metrics
        if item["random_k_percentile"] is not None
        and float(item["random_k_percentile"]) < 50
    )

    kill = False
    if mean_percentile is not None and model_total < 0 and mean_percentile < KILL_MEAN_PERCENTILE:
        kill = True
        reasons.append(
            f"kill: model total {model_total} < 0 and mean random-K percentile "
            f"{mean_percentile} < {KILL_MEAN_PERCENTILE}"
        )
    if len(mechanical_known) == REQUIRED_SESSIONS and losses_to_mechanical >= KILL_MAJORITY:
        kill = True
        reasons.append(
            f"kill: model lost to mechanical top-K on {losses_to_mechanical}/"
            f"{REQUIRED_SESSIONS} sessions"
        )
    if losses_to_random >= KILL_MAJORITY and model_total <= 0:
        kill = True
        reasons.append(
            f"kill: model lost to random-K (percentile < 50) on {losses_to_random}/"
            f"{REQUIRED_SESSIONS} sessions and total {model_total} <= 0"
        )

    continue_ok = (
        mean_percentile is not None
        and mean_percentile >= CONTINUE_MEAN_PERCENTILE
        and len(mechanical_known) == REQUIRED_SESSIONS
        and model_total > mechanical_total
        and model_total > 0
    )
    if continue_ok and not kill:
        verdict = "continue"
        reasons.append(
            "continue: five paper sessions beat mechanical total and have mean "
            f"random-K percentile {mean_percentile} >= {CONTINUE_MEAN_PERCENTILE}. "
            "This authorizes more paper sessions or a wider paper universe only. "
            "It never authorizes live orders, --allow-degraded as a live claim, "
            "Helsinki restart, or gate/FSM changes."
        )
    elif kill:
        verdict = "kill"
        if not reasons:
            reasons.append("kill: pre-registered stop rule matched")
    else:
        verdict = "inconclusive"
        reasons.append(
            "inconclusive: five scoreable paper sessions exist but neither the "
            "kill nor the continue rule matched. Keep paper-only. Do not go live."
        )

    return _result(
        verdict,
        reasons,
        metrics,
        considered,
        totals={
            "model_net_usd": model_total,
            "mechanical_net_usd": mechanical_total if mechanical_known else None,
            "mean_random_k_percentile": mean_percentile,
            "losses_to_mechanical": losses_to_mechanical,
            "losses_to_random_k": losses_to_random,
        },
    )


def _result(
    verdict: Verdict,
    reasons: list[str],
    metrics: list[dict[str, Any]],
    considered: list[dict[str, Any]],
    totals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "paper_only": True,
        "live_orders": False,
        "touches_live_gate_or_helsinki": False,
        "verdict": verdict,
        "required_sessions": REQUIRED_SESSIONS,
        "sessions_considered": len(considered),
        "sessions_scoreable": len(metrics),
        "random_k_draws": RANDOM_K_DRAWS,
        "random_k_seed": RANDOM_K_SEED,
        "reasons": reasons,
        "sessions": metrics,
        "totals": totals,
        "continue_means": (
            "more paper sessions or a wider paper universe; never live trading"
        ),
    }


def protocol_from_paths(paths: list[Path]) -> dict[str, Any]:
    return decide_protocol([load_evaluation(path) for path in paths[:REQUIRED_SESSIONS]])
