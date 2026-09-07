from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from groktrading.research.cli import demo
from groktrading.research.evaluation import (
    ORIGINAL_EVALUATION_KEYS,
    RANDOM_K_DRAWS,
    compute_baselines,
    evaluate,
    evaluate_core,
    original_evaluation_fields,
    percentile_rank,
)
from groktrading.research.opening15 import Config, Packet, canonical, digest, stamp, window


@pytest.fixture
def config() -> Config:
    return Config.model_validate_json(Path("research/opening15.example.json").read_text())


@pytest.fixture
def sample(tmp_path: Path, config: Config) -> tuple[Packet, dict[str, Any], list[dict[str, Any]]]:
    folder = tmp_path / "demo"
    demo(folder, config)
    packet = Packet.model_validate_json((folder / "packet.json").read_text())
    record = json.loads((folder / "decision.json").read_text())
    _, end = window(packet.session)
    available = stamp(record["received_at"])
    observations = []
    for symbol in config.symbols:
        for at, bid, ask in (
            (available + timedelta(seconds=1), 0.95, 1.0),
            (end + timedelta(hours=6, minutes=10), 1.1, 1.15),
        ):
            observations.append(
                {
                    "received_at": at.isoformat(),
                    "source": "synthetic",
                    "quote": {
                        "symbol": f"{symbol}260911C00100000",
                        "type": "option",
                        "bid": bid,
                        "ask": ask,
                        "bidsize": 1,
                        "asksize": 1,
                        "bid_date": at.timestamp() * 1000,
                        "ask_date": at.timestamp() * 1000,
                    },
                }
            )
    return packet, record, observations


def test_evaluate_original_keys_byte_identical(sample: Any) -> None:
    packet, record, observations = sample
    core = evaluate_core(packet, record, observations)
    full = evaluate(packet, record, observations)
    assert tuple(core) == ORIGINAL_EVALUATION_KEYS
    assert canonical(original_evaluation_fields(full)) == canonical(core)
    assert full["baselines"]["same_packet_hash"] == core["packet_hash"]
    assert "baselines" not in core
    assert full["experiment_id"]
    assert full["arm"]["universe"] == "packet_printed"
    assert full["baselines"]["fixed_k_values"] == [1, 2, 3]
    assert full["baselines"]["scorecards"]["selection_quality_same_k"]["defined"] is True
    assert "arm" not in core


def test_baselines_share_packet_and_1555_exit(sample: Any) -> None:
    packet, record, observations = sample
    report = evaluate(packet, record, observations)
    baselines = report["baselines"]
    assert baselines["same_packet_hash"] == report["packet_hash"]
    assert baselines["same_exit"] == "15:55 ET"
    assert baselines["k"] == report["selected_count"] == 1
    assert baselines["model_net_usd"] == report["selected_net_before_api_and_infra_usd"]
    assert baselines["abstain"] == {"selected_count": 0, "net_usd": 0.0}
    assert baselines["random_k"]["draws"] == RANDOM_K_DRAWS
    assert baselines["random_k"]["complete_draws"] == RANDOM_K_DRAWS
    assert baselines["random_k"]["percentile"] is not None
    assert 0 <= baselines["random_k"]["percentile"] <= 100
    assert baselines["latency"]["decision_minus_knowledge_cutoff_seconds"] >= 0
    assert baselines["latency"]["entries"]


def test_abstain_and_zero_picks_baselines(sample: Any) -> None:
    packet, record, observations = sample
    record = dict(record)
    record["decision"] = dict(record["decision"])
    record["decision"]["picks"] = []
    report = evaluate(packet, record, observations)
    assert report["selected_count"] == 0
    assert report["selected_net_before_api_and_infra_usd"] == 0
    assert report["baselines"]["k"] == 0
    assert report["baselines"]["random_k"]["percentile"] is None
    assert report["baselines"]["mechanical_top_k_ask_side_premium"]["option_symbols"] == []
    assert report["baselines"]["mechanical_top_k_ask_side_premium"]["net_usd"] == 0.0
    assert report["baselines"]["abstain"]["net_usd"] == 0.0
    assert report["baselines"]["scorecards"]["selection_quality_same_k"]["defined"] is False
    assert report["baselines"]["scorecards"]["policy_enter_or_abstain"]["entered"] is False
    assert report["baselines"]["fixed_k"]["1"]["random_k"]["percentile_of_zero"] is not None
    assert report["baselines"]["scorecards"]["policy_enter_or_abstain"]["policy_percentile"] is not None


def test_mechanical_top_k_uses_ask_side_premium_only(sample: Any) -> None:
    packet, record, observations = sample
    data = packet.model_dump(mode="json")
    high = None
    low = None
    for event in data["events"]:
        if event["kind"] != "option_trade":
            continue
        symbol = event["symbol"]
        event["raw"]["tags"] = ["ask_side"]
        event["raw"]["premium"] = 5000 if symbol == packet.config.symbols[1] else 1
        if symbol == packet.config.symbols[1]:
            high = event["raw"]["option_chain_id"]
        if symbol == packet.config.symbols[0]:
            low = event["raw"]["option_chain_id"]
    packet = Packet.model_validate(data)
    record = dict(record)
    record["packet_hash"] = digest(packet.model_dump(mode="json"))
    report = evaluate(packet, record, observations)
    top = report["baselines"]["mechanical_top_k_ask_side_premium"]
    assert top["k"] == 1
    assert top["option_symbols"] == [high]
    assert top["premium_by_contract"][high] == 5000
    assert low not in top["option_symbols"]


def test_random_k_is_seeded_and_reproducible(sample: Any) -> None:
    packet, record, observations = sample
    first = evaluate(packet, record, observations)["baselines"]["random_k"]
    second = evaluate(packet, record, observations)["baselines"]["random_k"]
    assert first == second
    assert first["complete_draws"] == RANDOM_K_DRAWS


def test_percentile_rank_midrank() -> None:
    assert percentile_rank(5, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 45.0
    assert percentile_rank(1, [1, 1, 1]) == 50.0


def test_baselines_do_not_mutate_core_rows(sample: Any) -> None:
    packet, record, observations = sample
    core = evaluate_core(packet, record, observations)
    snapshot = canonical(core["rows"])
    compute_baselines(packet, record, observations, core)
    assert canonical(core["rows"]) == snapshot
    assert canonical({key: core[key] for key in ORIGINAL_EVALUATION_KEYS}) == canonical(core)
