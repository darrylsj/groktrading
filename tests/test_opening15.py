from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from groktrading.research import opening15
from groktrading.research.capture import FlowCapture, ReadFeed, session_open
from groktrading.research.cli import demo
from groktrading.research.codex_cli import (
    exec_argv,
    loads_structured,
    parse_version,
    subprocess_env,
)
from groktrading.research.evaluation import evaluate, usable_quote
from groktrading.research.opening15 import (
    Config,
    Decision,
    Packet,
    canonical,
    probe_model,
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


def _prospective(packet: Packet, backend: str = "openai_responses") -> Packet:
    body = packet.model_dump(mode="json")
    body["synthetic"] = False
    body["config"]["recommend_backend"] = backend
    for event in body["events"]:
        event["source"] = "tradier_production" if event["kind"] == "stock_quote" else "uw"
    return Packet.model_validate(body)


def test_default_recommend_backend_is_codex_cli(config: Config) -> None:
    assert config.recommend_backend == "codex_cli"


def test_responses_api_boundary_and_no_retry(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    packet = _prospective(packet, "openai_responses")
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
    packet = _prospective(packet, "openai_responses")
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
        feed.get("/accounts/123/orders/preview")
    with pytest.raises(ValueError, match="not allowed"):
        feed.get("/markets/events/session")
    assert not hasattr(feed, "post")
    allowed = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"balances": {}}))
    )
    readable = ReadFeed("https://api.tradier.com/v1", "test-only", 120, allowed)
    assert readable.get("/accounts/RESEARCH1/balances") == {"balances": {}}
    readable.close()
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
    config = config.model_copy(update={"recommend_backend": "openai_responses"})

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


def _ok(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr="")


def _codex_runner(
    decision_text: str,
    *,
    version: str = "codex-cli 0.153.0",
    login_code: int = 0,
    exec_code: int = 0,
    events: str | None = None,
) -> Any:
    calls: list[list[str]] = []

    def runner(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv[1:] == ["--version"]:
            return _ok(version)
        if argv[1:3] == ["login", "status"]:
            return _ok("logged in", login_code)
        assert argv[1] == "exec"
        assert argv[-1] == "-"
        assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
        assert "--ephemeral" in argv
        assert "--ignore-user-config" in argv
        assert "--yolo" not in argv and "--search" not in argv
        assert "--output-schema" in argv and "--output-last-message" in argv
        assert env is not None and "OPENAI_API_KEY" not in env
        assert input_text and (
            "FROZEN_PACKET_JSON" in input_text or "capability check" in input_text
        )
        message = Path(argv[argv.index("--output-last-message") + 1])
        message.write_text(decision_text)
        payload = events or canonical(
            {
                "type": "turn.completed",
                "model": "gpt-6-astra",
                "usage": {"input_tokens": 1, "output_tokens": 2},
            }
        )
        return _ok(payload + "\n", exec_code)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_codex_cli_recommend_mocked_subprocess(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    packet = _prospective(packet, "codex_cli")
    monkeypatch.setattr(opening15, "now_utc", lambda: stamp(record["received_at"]))
    runner = _codex_runner(canonical(record["decision"]))
    directory = folder / "codex-ok"
    result = recommend(packet, directory, runner=runner)
    assert result["recommend_backend"] == "codex_cli"
    assert result["codex_version"] == "codex-cli 0.153.0"
    assert result["returned_model"] == "gpt-6-astra"
    assert result["usage"]["output_tokens"] == 2
    request = json.loads((directory / "request.json").read_text())
    assert request["codex_version"] == "codex-cli 0.153.0"
    assert request["body"]["store"] is False
    assert "Authorization" not in canonical(request)
    assert "OPENAI_API_KEY" not in canonical(request)
    assert (directory / "response.json").exists()
    assert (directory / "decision.json").exists()
    execs = [c for c in runner.calls if c[1] == "exec"]
    assert len(execs) == 1
    with pytest.raises(FileExistsError):
        recommend(packet, directory, runner=runner)
    assert len([c for c in runner.calls if c[1] == "exec"]) == 1


def test_codex_cli_refusal_persisted_without_decision(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    packet = _prospective(packet, "codex_cli")
    monkeypatch.setattr(opening15, "now_utc", lambda: stamp(record["received_at"]))
    directory = folder / "codex-refusal"
    runner = _codex_runner("not-json", exec_code=0)
    with pytest.raises(ValueError, match="incomplete/refused"):
        recommend(packet, directory, runner=runner)
    assert (directory / "response.json").exists()
    assert not (directory / "decision.json").exists()


def test_codex_cli_requires_login_and_min_version(sample: Any, monkeypatch: Any) -> None:
    packet, record, folder = sample
    packet = _prospective(packet, "codex_cli")
    monkeypatch.setattr(opening15, "now_utc", lambda: stamp(record["received_at"]))
    old = _codex_runner(canonical(record["decision"]), version="codex-cli 0.140.0")
    with pytest.raises(ValueError, match="0.153.0"):
        recommend(packet, folder / "old-cli", runner=old)
    logged_out = _codex_runner(canonical(record["decision"]), login_code=1)
    with pytest.raises(ValueError, match="not logged in"):
        recommend(packet, folder / "logged-out", runner=logged_out)


def test_codex_cli_probe_mocked(tmp_path: Path, config: Config) -> None:
    runner = _codex_runner(canonical({"status": "ok"}))
    result = probe_model(config, tmp_path, runner=runner)
    assert result["recommend_backend"] == "codex_cli"
    assert result["structured_outputs"] is True
    assert result["orders"] is False
    assert result["codex_version"] == "codex-cli 0.153.0"
    assert (tmp_path / "probe-response.json").exists()


def test_codex_helpers_and_secret_env_filter() -> None:
    assert parse_version("codex-cli 0.153.0") == (0, 153, 0)
    assert loads_structured('```json\n{"status":"ok"}\n```') == {"status": "ok"}
    argv = exec_argv(
        model="gpt-6-astra",
        reasoning_effort="high",
        schema_path=Path("/tmp/schema.json"),
        message_path=Path("/tmp/out.json"),
        work_dir=Path("/tmp/work"),
    )
    assert argv[:2] == ["codex", "exec"]
    names = ("OPENAI" + "_API_KEY", "TRADIER" + "_ACCESS_TOKEN", "UW" + "_API_TOKEN")
    raw_env = {"PATH": "/usr/bin", "HOME": "/home/op", "CODEX_HOME": "/home/op/.codex"}
    raw_env[names[0]] = "placeholder-openai"
    raw_env[names[1]] = "placeholder-tradier"
    raw_env[names[2]] = "placeholder-uw"
    env = subprocess_env(raw_env)
    assert env["CODEX_HOME"].endswith(".codex")
    assert "OPENAI_API_KEY" not in env
    assert "TRADIER_ACCESS_TOKEN" not in env


def test_market_credentials_do_not_require_openai_key(monkeypatch: Any) -> None:
    from groktrading.research.capture import market_credentials, openai_api_key

    monkeypatch.setenv("UW_API_TOKEN", "uw-test")
    monkeypatch.setenv("TRADIER_ACCESS_TOKEN", "tradier-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert market_credentials() == ("uw-test", "tradier-test")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        openai_api_key()


def test_codex_probe_resolves_relative_output_paths(
    tmp_path: Path, config: Config, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    original = _codex_runner('{"status":"ok"}', events='{"type":"turn.completed"}')

    def runner(argv: Any, **kwargs: Any) -> Any:
        if argv[1] == "exec":
            assert Path(argv[argv.index("--output-schema") + 1]).is_absolute()
            assert Path(argv[argv.index("--output-last-message") + 1]).is_absolute()
            assert Path(argv[argv.index("--cd") + 1]).is_absolute()
            assert "--ignore-rules" not in argv
        return original(argv, **kwargs)

    result = probe_model(config, Path("relative-probe"), runner=runner)
    assert result["returned_model"] is None
    assert (tmp_path / "relative-probe/probe-response.json").is_file()
