"""Reproducible CLI: synthetic demo, calibration, validation tuning, and paper replay."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .engine import PaperEngine
from .feeds import QuoteTerms, databento_events, tradier_snapshot
from .schema import BookFrame, Config, Event, Flows, Level, Parameters, Quote, parse_event
from .simulator import calibrate


def read_events(path: Path) -> Iterator[Event]:
    with path.open() as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield parse_event(json.loads(line))
                except (ValueError, KeyError) as exc:
                    raise ValueError(f"{path.name}:{line_no}: invalid event: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def write_events(path: Path, events: Iterable[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally overwriting a captured tape.
    with path.open("x") as stream:
        for event in events:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()


def replay(
    events: Iterable[Event],
    config: Config,
    params: Parameters,
    model: Literal["fluid", "persistence"] = "fluid",
) -> dict[str, Any]:
    engine = PaperEngine(config, params, model)
    for event in events:
        engine.ingest(event)
    return engine.report()


def synthetic_events(start: datetime, seconds: int) -> Iterator[Event]:
    """Deliberately stylized plumbing fixture, not a market-calibrated generator."""
    for second in range(seconds):
        at = start + timedelta(seconds=second)
        # Quote changes avoid every decision boundary, exercising delayed fills.
        mid = 100 + ((second + 1) // 5) * 0.01
        frame = BookFrame(
            event_id=f"demo-book-{at.isoformat()}",
            symbol="AAPL",
            source="synthetic",
            interval_start=at - timedelta(seconds=1),
            event_at=at,
            received_at=at,
            bids=tuple(
                Level(price=round(mid - 0.01 - j * 0.01, 2), size=40 if j == 0 else 120)
                for j in range(64)
            ),
            asks=tuple(
                Level(price=round(mid + 0.01 + j * 0.01, 2), size=15 if j == 0 else 80)
                for j in range(64)
            ),
            flows=Flows(bid_add=30, ask_add=30, bid_cancel=3, ask_cancel=3, buy=45, sell=5),
        )
        yield frame
        yield Quote(
            event_id=f"demo-stock-{at.isoformat()}",
            symbol="AAPL",
            underlying="AAPL",
            asset="stock",
            source="synthetic",
            event_at=at,
            received_at=at,
            bid=frame.bids[0].price,
            ask=frame.asks[0].price,
            bid_size=40,
            ask_size=15,
        )
        for asset, delta in (("call", 0.55), ("put", -0.45)):
            premium = 2 + delta * (mid - 100)
            yield Quote(
                event_id=f"demo-{asset}-{at.isoformat()}",
                symbol=f"DEMO_AAPL_{asset}",
                underlying="AAPL",
                asset="call" if asset == "call" else "put",
                source="synthetic",
                event_at=at,
                received_at=at,
                bid=round(premium - 0.01, 2),
                ask=round(premium + 0.01, 2),
                bid_size=20,
                ask_size=20,
                multiplier=100,
                delta=delta,
                gamma=0.02,
                theta_per_day=-0.03,
                vega_per_vol_point=0.01,
                greeks_at=at,
                expires_at=start + timedelta(days=7),
                iv=0.25,
            )


def summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "mode",
        "model",
        "fill_count",
        "realized_pnl",
        "fees",
        "final_mark",
        "max_drawdown_dollars",
        "forecast_mse",
        "zero_return_mse",
    )
    return {k: report[k] for k in keys}


def tune(events: list[Event], config: Config, params: Parameters) -> tuple[Config, dict[str, Any]]:
    """Select on a separate validation tape; freeze cutoff for future test replay.

    Calibration must predate the entire validation tape. A fixed six-point grid
    selects expected-loss penalty and minimum dollar improvement after costs.
    This optimizes validation P&L only, never claims future optimality.
    """
    if not events or params.trained_through >= events[0].received_at:
        raise ValueError("calibration must precede validation tape")
    if config.selected_through is not None and config.selected_through >= events[0].received_at:
        raise ValueError("validation tape overlaps prior policy selection")
    results = []
    best: tuple[float, Config] | None = None
    for risk in (0.0, 0.5):
        for improvement in (0.25, 1.0, 2.0):
            candidate = config.model_copy(
                update={"downside_weight": risk, "minimum_improvement": improvement}
            )
            report = replay(events, candidate, params)
            pnl = report["final_mark"]["net_pnl"]
            results.append({"risk": risk, "minimum_improvement": improvement, **summary(report)})
            if pnl is not None and report["forecast_outcomes"] and (best is None or pnl > best[0]):
                best = float(pnl), candidate
    if best is None:
        raise ValueError("no scoreable validation result")
    selected = best[1].model_copy(update={"selected_through": events[-1].received_at})
    return selected, {
        "selection_metric": "validation_net_liquidation_pnl",
        "validation_start": events[0].received_at,
        "validation_end": events[-1].received_at,
        "candidates": results,
        "warning": "Selection performance is not held-out test performance.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="offline synthetic stock/options fixture")
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument("--minutes", type=int, default=8)
    fit = commands.add_parser("calibrate", help="fit depth transport on training data only")
    fit.add_argument("--events", type=Path, required=True)
    fit.add_argument("--out", type=Path, required=True)
    for command in ("replay", "tune"):
        sub = commands.add_parser(command)
        sub.add_argument("--events", type=Path, required=True)
        sub.add_argument("--parameters", type=Path, required=True)
        sub.add_argument("--config", type=Path)
        sub.add_argument("--out", type=Path, required=True)
        if command == "replay":
            sub.add_argument("--model", choices=("fluid", "persistence"), default="fluid")
    capture = commands.add_parser("capture-databento", help="read-only, one-symbol XNAS MBO")
    capture.add_argument("--symbol", required=True)
    capture.add_argument("--start", help="historical range; start before daily clear")
    capture.add_argument("--end")
    capture.add_argument("--delivery-delay-ms", type=float, default=100)
    capture.add_argument("--out", type=Path, required=True)
    quotes = commands.add_parser("quote-tradier", help="one read-only production quote snapshot")
    quotes.add_argument("--terms", type=Path, required=True)
    quotes.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "demo":
        if not 4 <= args.minutes <= 60:
            parser.error("demo minutes must be between 4 and 60")
        args.out.mkdir(parents=True, exist_ok=True)
        events = list(
            synthetic_events(datetime(2026, 1, 5, 14, 28, tzinfo=UTC), (args.minutes + 2) * 60)
        )
        cut = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        training = [e for e in events if isinstance(e, BookFrame) and e.received_at < cut]
        params = calibrate(training)
        config = Config(symbols=("AAPL",), paths=32)
        write_events(args.out / "synthetic.jsonl", events)
        write_json(args.out / "parameters.json", params.model_dump(mode="json"))
        write_json(args.out / "config.json", config.model_dump(mode="json"))
        report = replay(events, config, params)
        write_json(args.out / "report.json", report)
        baseline = replay(events, config, params, "persistence")
        write_json(args.out / "baseline.json", baseline)
        print(
            json.dumps(
                {
                    "synthetic_only": True,
                    "fluid": summary(report),
                    "persistence": summary(baseline),
                },
                indent=2,
                default=str,
            )
        )
    elif args.command == "calibrate":
        frames = [e for e in read_events(args.events) if isinstance(e, BookFrame)]
        write_json(args.out, calibrate(frames).model_dump(mode="json"))
    elif args.command == "capture-databento":
        write_events(
            args.out,
            databento_events(
                args.symbol,
                start=args.start,
                end=args.end,
                historical_delay_ms=args.delivery_delay_ms,
            ),
        )
    elif args.command == "quote-tradier":
        terms = {
            s: QuoteTerms.model_validate(t) for s, t in json.loads(args.terms.read_text()).items()
        }
        write_events(args.out, tradier_snapshot(terms))
    else:
        params = Parameters.model_validate_json(args.parameters.read_text())
        config = Config.model_validate_json(args.config.read_text()) if args.config else Config()
        if args.command == "tune":
            selected, audit = tune(list(read_events(args.events)), config, params)
            write_json(args.out, selected.model_dump(mode="json"))
            write_json(args.out.with_suffix(".selection.json"), audit)
        else:
            report = replay(read_events(args.events), config, params, args.model)
            write_json(args.out, report)
            print(json.dumps(summary(report), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
