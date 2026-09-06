"""Opening15 CLI: preflight, capture, recommend, monitor, report and offline demo."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from groktrading.research.capture import (
    collect,
    credentials,
    feeds,
    quotes,
    session_open,
)
from groktrading.research.evaluation import evaluate, monitor
from groktrading.research.opening15 import (
    Config,
    Decision,
    Event,
    Packet,
    digest,
    now_utc,
    probe_model,
    recommend,
    request_body,
    window,
    write_once,
)


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def demo(directory: Path, config: Config) -> None:
    """Synthetic plumbing only. The model selection is a fixture, never an AI performance result."""
    day = date(2026, 9, 8)
    start, end = window(day)
    events = []
    for index, symbol in enumerate(config.symbols):
        for minute in range(16):
            at = start + timedelta(minutes=minute)
            events.append(
                Event(
                    event_id=f"stock-{symbol}-{minute}",
                    kind="stock_quote",
                    symbol=symbol,
                    event_at=at,
                    received_at=at,
                    source="synthetic",
                    raw={"symbol": symbol, "last": 100 + index + minute / 10},
                )
            )
        at = end - timedelta(seconds=1)
        events.append(
            Event(
                event_id=f"flow-{symbol}",
                kind="option_trade",
                symbol=symbol,
                event_at=at,
                received_at=at,
                source="synthetic",
                raw={
                    "option_chain_id": f"{symbol}260911C00100000",
                    "price": "1.00",
                    "nbbo_bid": "0.95",
                    "nbbo_ask": "1.00",
                    "size": 1,
                },
            )
        )
    packet = Packet(
        session=day,
        knowledge_cutoff=end + timedelta(seconds=10),
        config=config,
        config_locked_at=start - timedelta(minutes=5),
        synthetic=True,
        events=events,
        coverage={"flow_complete": True, "limitations": ["SYNTHETIC TEST DATA"]},
    )
    decision = Decision.model_validate(
        {
            "market_assessment": "SYNTHETIC fixture; no model call",
            "data_limitations": ["synthetic"],
            "stock_assessments": [{"symbol": s, "assessment": "synthetic"} for s in config.symbols],
            "picks": [
                {
                    "option_symbol": f"{config.symbols[0]}260911C00100000",
                    "action": "enter",
                    "max_entry_price": 2,
                    "valid_for_seconds": 120,
                    "thesis": "synthetic",
                    "alternative_explanation": "synthetic",
                    "invalidation": "synthetic",
                    "proposed_exit": "15:55 ET",
                    "confidence": "low",
                    "evidence_ids": [f"flow-{config.symbols[0]}"],
                }
            ],
        }
    )
    available = end + timedelta(seconds=30)
    record = {
        "packet_hash": digest(packet.model_dump(mode="json")),
        "received_at": available.isoformat(),
        "synthetic": True,
        "returned_model": "NO_MODEL_SYNTHETIC_FIXTURE",
        "decision": decision.model_dump(mode="json"),
    }
    observations = []
    for symbol in config.symbols:
        for at, bid, ask in [
            (available + timedelta(seconds=1), 0.95, 1),
            (end + timedelta(hours=6, minutes=10), 1.1, 1.15),
        ]:
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
    write_once(directory / "packet.json", packet.model_dump(mode="json"))
    write_once(directory / "request-preview.json", request_body(packet))
    write_once(directory / "decision.json", record)
    write_once(directory / "evaluation.json", evaluate(packet, record, observations))


def main() -> None:
    parser = argparse.ArgumentParser(description="Opening15 discretionary research. NO ORDERS.")
    parser.add_argument(
        "command",
        choices=[
            "preflight",
            "model-probe",
            "capture",
            "recommend",
            "monitor",
            "report",
            "run",
            "demo",
        ],
    )
    parser.add_argument("--config", type=Path, default=Path("research/opening15.example.json"))
    parser.add_argument("--session", type=date.fromisoformat, default=date(2026, 9, 8))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = Config.model_validate(load(args.config))
        if args.command == "demo":
            demo(args.output, config)
            print("Synthetic offline demo passed; no model/API/order calls.")
            return
        if args.command == "model-probe":
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ValueError("OPENAI_API_KEY missing")
            print(json.dumps(probe_model(config, args.output, key), indent=2))
            return
        if args.command == "report":
            packet = Packet.model_validate(load(args.output / "packet.json"))
            record = load(args.output / "decision.json")
            observations = [
                json.loads(line)
                for line in (args.output / "observations.jsonl").read_text().splitlines()
            ]
            print(json.dumps(evaluate(packet, record, observations), indent=2))
            return
        if args.command == "recommend":
            packet = Packet.model_validate(load(args.output / "packet.json"))
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ValueError("OPENAI_API_KEY missing")
            recommend(packet, args.output, key)
            print("Recommendation recorded; no orders.")
            return
        uw, tradier = feeds(config)
        try:
            if args.command == "preflight":
                calendar = session_open(tradier, args.session)
                stock_rows = quotes(tradier, config.symbols + config.context_symbols)
                flow = uw.get(
                    "/api/option-trades", {"ticker_symbol": config.symbols[0], "limit": 1}
                )
                news = uw.get("/api/news/headlines", {"ticker": config.symbols[0], "limit": 1})
                _, _, key = credentials()
                with httpx.Client(timeout=20, follow_redirects=False) as client:
                    response = client.get(
                        "https://api.openai.com/v1/models/" + config.model,
                        headers={"Authorization": f"Bearer {key}"},
                    )
                if response.status_code != 200 or not calendar:
                    raise ValueError("model access or regular trading session not verified")
                result = {
                    "checked_at": now_utc().isoformat(),
                    "session": str(args.session),
                    "regular_session": calendar,
                    "model": config.model,
                    "model_catalog_access": True,
                    "stock_rows": len(stock_rows),
                    "uw_rows": len(flow.get("data", [])),
                    "news_rows": len(news.get("data", [])),
                    "limitations": [
                        "Does not prove real-time UW/option quote entitlement",
                        "Does not test a paid Responses request or rate headroom",
                    ],
                }
                write_once(args.output / "preflight.json", result)
                print(json.dumps(result, indent=2))
                return
            if args.command == "monitor":
                packet = Packet.model_validate(load(args.output / "packet.json"))
                monitor(packet, load(args.output / "decision.json"), args.output, tradier)
                return
            print(f"Opening15 starting for {args.session}: ten stocks, paper only.", flush=True)
            packet = collect(config, args.session, args.output, uw, tradier)
            print("Opening packet frozen; no orders.", flush=True)
            if args.command == "run":
                _, _, key = credentials()
                record = recommend(packet, args.output, key)
                print("Model decision frozen; starting quote-only paper monitoring.", flush=True)
                monitor(packet, record, args.output, tradier)
        finally:
            uw.close()
            tradier.close()
    except Exception as exc:
        # Do not echo provider bodies, headers, URLs, validation inputs or credentials.
        if args.output.exists():
            failure = {
                "at": now_utc().isoformat(),
                "stage": args.command,
                "error_type": type(exc).__name__,
                "detail": str(exc)
                if type(exc) is ValueError
                else "See runbook for this error type",
                "status": "failed_no_orders",
            }
            failure_path = args.output / ("failure-" + now_utc().strftime("%H%M%S%f") + ".json")
            write_once(failure_path, failure)
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        parser.exit(
            1,
            f"{args.command} failed ({detail}); no orders. "
            "Check configuration, coverage, provider access and runbook.\n",
        )


if __name__ == "__main__":
    main()
