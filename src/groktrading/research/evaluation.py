"""Conservative quote-based paper marks. Never claims broker fills or realized P&L."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from groktrading.research.capture import ReadFeed, quotes
from groktrading.research.opening15 import (
    NY,
    Decision,
    Packet,
    canonical,
    digest,
    now_utc,
    stamp,
    write_once,
)


def usable_quote(row: dict[str, Any], received: datetime, max_age: int) -> bool:
    try:
        bid, ask = float(row["bid"]), float(row["ask"])
        bid_age = (received - stamp(row["bid_date"])).total_seconds()
        ask_age = (received - stamp(row["ask_date"])).total_seconds()
        return (
            row.get("type") == "option"
            and row.get("delayed") in (None, False)
            and math.isfinite(bid)
            and math.isfinite(ask)
            and 0 <= bid <= ask
            and ask > 0
            and 0 <= bid_age <= max_age
            and 0 <= ask_age <= max_age
            and float(row.get("bidsize", 0)) >= 1
            and float(row.get("asksize", 0)) >= 1
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def evaluate(
    packet: Packet, record: dict[str, Any], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    if record["packet_hash"] != digest(packet.model_dump(mode="json")):
        raise ValueError("decision/packet hash mismatch")
    decision = Decision.model_validate(record["decision"])
    decision.validate_evidence(packet)
    available = stamp(record["received_at"])
    if available < packet.knowledge_cutoff:
        raise ValueError("decision predates packet")
    exit_at = datetime.combine(packet.session, datetime.min.time(), NY).replace(hour=15, minute=55)
    config = packet.config
    picks = {p.option_symbol: p for p in decision.picks}
    universe = sorted(
        {str(e.raw["option_chain_id"]) for e in packet.events if e.kind == "option_trade"}
    )
    by_contract: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        symbol = str(observation["quote"].get("symbol", ""))
        by_contract.setdefault(symbol, []).append(observation)
    for values in by_contract.values():
        values.sort(key=lambda q: stamp(q["received_at"]))
    rows: list[dict[str, Any]] = []
    for contract in universe:
        pick = picks.get(contract)
        eligible = pick is not None and pick.action == "enter"
        validity = pick.valid_for_seconds if pick else 300
        max_price = pick.max_entry_price if pick else math.inf
        entry: dict[str, Any] | None = None
        exit_mark: dict[str, Any] | None = None
        marks: list[float] = []
        for observation in by_contract.get(contract, []):
            received = stamp(observation["received_at"])
            quote = observation["quote"]
            if quote.get("symbol") != contract or received < available:
                continue
            if observation.get("source") != "tradier_production":
                if not packet.synthetic or observation.get("source") != "synthetic":
                    continue
            if not usable_quote(quote, received, config.max_quote_age_seconds):
                continue
            if entry is None:
                if received > min(available + timedelta(seconds=validity), exit_at):
                    continue
                # Require a post-decision ask update, not only a late HTTP receipt of an old quote.
                if stamp(quote["ask_date"]) < available:
                    continue
                price = float(quote["ask"]) + config.slippage_per_share
                if price > max_price:
                    continue
                entry = {"at": received.isoformat(), "price": price}
                continue
            marks.append(max(0, float(quote["bid"]) - config.slippage_per_share))
            if (
                exit_at <= received <= exit_at + timedelta(seconds=90)
                and stamp(quote["bid_date"]) >= exit_at
            ):
                exit_mark = {"at": received.isoformat(), "price": marks[-1]}
                break
        pnl = None
        if entry and exit_mark:
            pnl = round(
                100 * (exit_mark["price"] - entry["price"])
                - 2 * config.commission_per_contract_side,
                4,
            )
        rows.append(
            {
                "option_symbol": contract,
                "group": "selected" if eligible else "counterfactual",
                "ranked_action": pick.action if pick else "unranked",
                "status": "closed_simulation"
                if exit_mark
                else "missing_exit"
                if entry
                else "not_filled",
                "entry": entry,
                "exit": exit_mark,
                "paper_net_usd": pnl,
                "sampled_best_bid": max(marks) if marks else None,
                "sampled_worst_bid": min(marks) if marks else None,
            }
        )
    selected = [r for r in rows if r["group"] == "selected"]
    usage = record.get("usage", {})
    cost_known = config.api_input_usd_per_million > 0 and config.api_output_usd_per_million > 0
    estimated_api = (
        (
            usage.get("input_tokens", 0) * config.api_input_usd_per_million
            + usage.get("output_tokens", 0) * config.api_output_usd_per_million
        )
        / 1e6
        if cost_known
        else None
    )
    complete = all(r["status"] != "missing_exit" for r in selected)
    net = round(sum(r["paper_net_usd"] or 0 for r in selected), 4) if complete else None
    return {
        "paper_only": True,
        "synthetic": packet.synthetic,
        "session": str(packet.session),
        "packet_hash": record["packet_hash"],
        "selected_count": len(selected),
        "selected_net_before_api_and_infra_usd": net,
        "estimated_api_cost_usd": estimated_api,
        "selected_net_after_estimated_api_usd": round(net - estimated_api, 4)
        if net is not None and estimated_api is not None
        else None,
        "rows": rows,
        "limitations": [
            "Hypothetical one-lot ask-in/bid-out; no broker fills",
            "Fixed 15:55 ET exit; model prose exit not executed",
            "Unfilled and missing exits remain visible",
            "Sampled quotes do not establish continuous path or queue fills",
            "Counterfactuals are not independently funded portfolio trades",
            "API estimate excludes caching; data/hosting costs not included",
        ],
    }


def monitor(packet: Packet, record: dict[str, Any], directory: Path, feed: ReadFeed) -> None:
    until = datetime.combine(packet.session, datetime.min.time(), NY).replace(
        hour=15, minute=56, second=30
    )
    if now_utc().astimezone(NY).date() != packet.session or now_utc() >= until:
        raise ValueError("monitor requires the same active session")
    contracts = sorted(
        {str(e.raw["option_chain_id"]) for e in packet.events if e.kind == "option_trade"}
    )
    decision = Decision.model_validate(record["decision"])
    selected = [p.option_symbol for p in decision.picks]
    remaining = [c for c in contracts if c not in selected]
    path = directory / "observations.jsonl"
    # A second monitor cannot append competing data to the same experiment.
    with path.open("x") as handle:
        while now_utc() <= until:
            begin = time.monotonic()
            # Ranked contracts first so the broad comparison universe cannot delay their entries.
            for group in (selected, remaining):
                for offset in range(0, len(group), 100):
                    batch = group[offset : offset + 100]
                    rows = quotes(feed, batch)
                    received = now_utc().isoformat()
                    for row in rows:
                        handle.write(
                            canonical(
                                {
                                    "received_at": received,
                                    "source": "tradier_production",
                                    "quote": row,
                                }
                            )
                            + "\n"
                        )
                    handle.flush()
            delay = max(
                0,
                min(
                    packet.config.poll_seconds - (time.monotonic() - begin),
                    (until - now_utc()).total_seconds(),
                ),
            )
            if delay:
                time.sleep(delay)
    observations = [json.loads(line) for line in path.read_text().splitlines()]
    write_once(directory / "evaluation.json", evaluate(packet, record, observations))
