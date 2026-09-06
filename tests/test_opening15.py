from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from groktrading.research import opening15
from groktrading.research.capture import FlowCapture, ReadFeed, session_open
from groktrading.research.cli import demo
from groktrading.research.evaluation import evaluate, usable_quote
from groktrading.research.opening15 import (
    Config,
    Decision,
    Packet,
    canonical,
    recommend,
    request_body,
    stamp,
    window,
    write_once,
)


@pytest.fixture
def config() -> Config:
    return Config.model_validate_json(Path("research/opening15.example.json").read_text())


@pytest.fixture
def sample(tmp_path: Path, config: Config) -> tuple[Packet, dict[str, Any], Path]:
    folder = tmp_path / "demo"
    demo(folder, config)
    packet = Packet.model_validate_json((folder / "packet.json").read_text())
    record = json.loads((folder / "decision.json").read_text())
    return packet, record, folder


def observation(contract: str, at: Any, bid: float = 1.1, ask: float = 1.15) -> dict[str, Any]:
    return {
        "received_at": at.isoformat(),
        "source": "synthetic",
        "quote": {
            "symbol": contract,
            "type": "option",
            "bid": bid,
            "ask": ask,
            "bid_date": at.timestamp() * 1000,
            "ask_date": at.timestamp() * 1000,
            "bidsize": 1,
            "asksize": 1,
        },
    }


def test_demo_is_explicitly_synthetic(sample: Any) -> None:
    packet, record, folder = sample
    report = json.loads((folder / "evaluation.json").read_text())
    assert report["synthetic"] and report["paper_only"]
    assert report["selected_net_before_api_and_infra_usd"] == pytest.approx(6.7)
    assert report["estimated_api_cost_usd"] is None
    assert len(report["rows"]) == 10
    assert sum(row["group"] == "counterfactual" for row in report["rows"]) == 9
    with pytest.raises(ValueError, match="synthetic"):
        recommend(packet, folder, "unused")


@pytest.mark.parametrize(
    "mutation",
    [
        "future_event",
        "future_receipt",
        "late_stock",
        "late_config",
        "gap",
        "incomplete",
        "duplicate",
        "empty",
    ],
)
def test_packet_rejects_invalid_evidence(sample: Any, mutation: str) -> None:
    packet, _, _ = sample
    data = packet.model_dump(mode="json")
    start, end = window(packet.session)
    if mutation == "future_event":
        data["events"][0]["event_at"] = (end + timedelta(seconds=1)).isoformat()
    elif mutation == "future_receipt":
        data["events"][0]["received_at"] = (end + timedelta(minutes=1)).isoformat()
    elif mutation == "late_stock":
        data["events"][0]["received_at"] = (end + timedelta(seconds=1)).isoformat()
    elif mutation == "late_config":
        data["config_locked_at"] = (start + timedelta(seconds=1)).isoformat()
    elif mutation == "gap":
        data["events"] = [e for e in data["events"] if e["symbol"] != packet.config.symbols[0]]
    elif mutation == "incomplete":
        data["coverage"]["flow_complete"] = False
    elif mutation == "duplicate":
        data["events"].append(data["events"][0])
    else:
        data["events"] = [e for e in data["events"] if e["kind"] != "option_trade"]
    with pytest.raises(ValidationError):
        Packet.model_validate(data)


def test_encoding_preserves_all_rows_and_quarantines_cumulative_fields(sample: Any) -> None:
    packet, _, _ = sample
    table = packet.compact()["tables"]["option_trade"]
    assert table["row_count"] == 10
    assert "raw.volume" not in table["columns"]
    for encoded in table["columns"].values():
        if "codes" in encoded:
            values = [encoded["dictionary"][i] for i in encoded["codes"]]
        else:
            values = encoded["values"]
        assert len(values) == 10
    packet.config.max_input_bytes = 1000
    with pytest.raises(ValueError, match="no silent"):
        request_body(packet)


def test_hallucinated_contract_and_evidence_rejected(sample: Any) -> None:
    packet, record, _ = sample
    decision = Decision.model_validate(record["decision"])
    decision.picks[0].option_symbol = "FAKE260911C00100000"
    with pytest.raises(ValueError, match="contract"):
        decision.validate_evidence(packet)
    decision = Decision.model_validate(record["decision"])
    decision.picks[0].evidence_ids = ["invented"]
    with pytest.raises(ValueError, match="invented"):
        decision.validate_evidence(packet)


def test_zero_picks_is_valid(sample: Any) -> None:
    packet, record, _ = sample
    record["decision"]["picks"] = []
    result = evaluate(packet, record, [])
    assert result["selected_count"] == 0
    assert result["selected_net_before_api_and_infra_usd"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("bid", -1),
        ("bid", float("nan")),
        ("ask", 0),
        ("ask", float("inf")),
        ("bidsize", 0),
        ("delayed", True),
        ("type", "stock"),
    ],
)
def test_unusable_quote(field: str, value: Any, sample: Any) -> None:
    _, record, _ = sample
    at = stamp(record["received_at"])
    row = observation("A", at)["quote"]
    row[field] = value
    assert not usable_quote(row, at, 30)


def test_no_backdated_entry_and_missing_exit_not_zero(sample: Any) -> None:
    packet, record, _ = sample
    at = stamp(record["received_at"])
    contract = record["decision"]["picks"][0]["option_symbol"]
    early = observation(contract, at - timedelta(seconds=1))
    late_receipt = observation(contract, at + timedelta(seconds=1))
    late_receipt["quote"]["ask_date"] = (at - timedelta(seconds=1)).timestamp() * 1000
    result = evaluate(packet, record, [early, late_receipt])
    assert next(r for r in result["rows"] if r["group"] == "selected")["status"] == "not_filled"
    entry = observation(contract, at + timedelta(seconds=2))
    result = evaluate(packet, record, [entry])
    assert result["selected_net_before_api_and_infra_usd"] is None
    assert next(r for r in result["rows"] if r["group"] == "selected")["status"] == "missing_exit"


def test_price_limit_expiry_fees_and_exit_time(sample: Any) -> None:
    packet, record, _ = sample
    at = stamp(record["received_at"])
    contract = record["decision"]["picks"][0]["option_symbol"]
    expensive = observation(contract, at + timedelta(seconds=1), 3, 3.1)
    expired = observation(contract, at + timedelta(seconds=121), 0.9, 1)
    result = evaluate(packet, record, [expensive, expired])
    assert next(r for r in result["rows"] if r["group"] == "selected")["status"] == "not_filled"
    entry = observation(contract, at + timedelta(seconds=2), 0.9, 1)
    _, end = window(packet.session)
    exit_at = end + timedelta(hours=6, minutes=10)
    before = observation(contract, exit_at - timedelta(seconds=1), 2, 2.1)
    exit_obs = observation(contract, exit_at + timedelta(seconds=1), 1.1, 1.2)
    result = evaluate(packet, record, [exit_obs, before, entry])
    assert result["selected_net_before_api_and_infra_usd"] == pytest.approx(6.7)


def test_packet_hash_and_duplicate_output(sample: Any) -> None:
    packet, record, folder = sample
    record["packet_hash"] = "wrong"
    with pytest.raises(ValueError, match="hash"):
        evaluate(packet, record, [])
    with pytest.raises(FileExistsError):
        write_once(folder / "packet.json", {})


def test_responses_api_boundary_and_no_retry(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    body = packet.model_dump(mode="json")
    body["synthetic"] = False
    for event in body["events"]:
        event["source"] = "tradier_production" if event["kind"] == "stock_quote" else "uw"
    packet = Packet.model_validate(body)
    at = stamp(record["received_at"])
    monkeypatch.setattr(opening15, "now_utc", lambda: at)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/responses"
        data = json.loads(request.content)
        assert data["model"] == "gpt-6-astra"
        assert data["store"] is False and "tools" not in data
        assert data["text"]["format"]["strict"] is True
        assert "Authorization" not in canonical(data)
        calls.append(data)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-6-astra",
                "id": "mock",
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": canonical(record["decision"])}],
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        directory = folder / "prospective"
        result = recommend(packet, directory, "test-only", client)
        assert result["returned_model"] == "gpt-6-astra"
        with pytest.raises(FileExistsError):
            recommend(packet, directory, "test-only", client)
    assert len(calls) == 1


def test_refusal_persisted_without_decision(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    data = packet.model_dump(mode="json")
    data["synthetic"] = False
    for event in data["events"]:
        event["source"] = "tradier_production" if event["kind"] == "stock_quote" else "uw"
    packet = Packet.model_validate(data)
    monkeypatch.setattr(opening15, "now_utc", lambda: stamp(record["received_at"]))
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "incomplete", "output": []})
        )
    ) as client:
        directory = folder / "refusal"
        with pytest.raises(ValueError, match="incomplete"):
            recommend(packet, directory, "test-only", client)
        assert (directory / "response.json").exists()
        assert not (directory / "decision.json").exists()


def test_capped_flow_ranges_bisect_without_dropping_boundary(
    tmp_path: Path, config: Config
) -> None:
    start, end = window(__import__("datetime").date(2026, 9, 8))
    rows = [
        {
            "id": str(i),
            "underlying_symbol": "AAPL",
            "option_chain_id": "AAPL260911C00100000",
            "executed_at": (start + timedelta(milliseconds=i)).isoformat(),
        }
        for i in range(600)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        lo = float(request.url.params["newer_than"]) / 1000
        hi = float(request.url.params["older_than"]) / 1000
        assert "min_premium" not in request.url.params
        selected = [r for r in rows if lo <= stamp(r["executed_at"]).timestamp() <= hi]
        return httpx.Response(200, json={"data": selected[-500:]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    feed = ReadFeed("https://api.unusualwhales.com", "test-only", 120, client)
    feed.interval = 0
    capture = FlowCapture(feed, config, tmp_path, end + timedelta(days=1000))
    capture.interval(start, start + timedelta(seconds=1))
    assert len(capture.events) == 600
    assert capture.requests > 1
    feed.close()


def test_saturated_timestamp_fails(tmp_path: Path, config: Config) -> None:
    start, end = window(__import__("datetime").date(2026, 9, 8))
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": str(i)} for i in range(500)]})
        )
    )
    feed = ReadFeed("https://api.unusualwhales.com", "test-only", 120, client)
    feed.interval = 0
    capture = FlowCapture(feed, config, tmp_path, end + timedelta(days=1000))
    with pytest.raises(ValueError, match="saturated"):
        capture.interval(start, start + timedelta(milliseconds=1))
    feed.close()


def test_read_adapter_blocks_orders(config: Config) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    feed = ReadFeed("https://api.tradier.com/v1", "test-only", 120, client)
    with pytest.raises(ValueError, match="not allowed"):
        feed.get("/accounts/123/orders")
    assert not hasattr(feed, "post")
    feed.close()


def test_calendar_blocks_holiday_and_early_close() -> None:
    from datetime import date

    for status, end, expected in [
        ("closed", "16:00", False),
        ("open", "13:00", False),
        ("open", "16:00", True),
    ]:
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda _, status=status, end=end: httpx.Response(
                    200,
                    json={
                        "calendar": {
                            "days": {
                                "day": [
                                    {
                                        "date": "2026-09-08",
                                        "status": status,
                                        "open": {"start": "09:30", "end": end},
                                    }
                                ]
                            }
                        }
                    },
                )
            )
        )
        feed = ReadFeed("https://api.tradier.com/v1", "test-only", 120, client)
        assert session_open(feed, date(2026, 9, 8)) == expected
        feed.close()


def test_paid_probe_is_explicit_and_has_no_market_data(tmp_path: Path, config: Config) -> None:
    from groktrading.research.opening15 import probe_model

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == config.model
        assert "capability check" in body["input"]
        assert body["text"]["format"]["strict"] is True
        assert not body.get("tools")
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": config.model,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"status":"ok"}'}],
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_model(config, tmp_path, "test-only", client)
    assert result["structured_outputs"] and result["orders"] is False
    assert (tmp_path / "probe-response.json").exists()
