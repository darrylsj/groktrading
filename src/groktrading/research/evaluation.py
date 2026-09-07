"""Conservative quote-based paper marks. Never claims broker fills or realized P&L."""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from groktrading.research.capture import ReadFeed, provider_aggressor, quotes
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

# Additive baselines never mutate these keys or their values.
ORIGINAL_EVALUATION_KEYS = (
    "paper_only",
    "synthetic",
    "session",
    "packet_hash",
    "decision_hash",
    "selected_count",
    "selected_net_before_api_and_infra_usd",
    "estimated_api_cost_usd",
    "selected_net_after_estimated_api_usd",
    "rows",
    "limitations",
)
RANDOM_K_DRAWS = 1000
RANDOM_K_SEED = 20260908
MECHANICAL_VALIDITY_SECONDS = 300
ORIGINAL_LIMITATIONS = [
    "Hypothetical one-lot ask-in/bid-out; no broker fills",
    "Fixed 15:55 ET exit; model prose exit not executed",
    "Unfilled and missing exits remain visible",
    "Sampled quotes do not establish continuous path or queue fills",
    "Counterfactuals are not independently funded portfolio trades",
    "API estimate excludes caching; data/hosting costs not included",
]


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


def printed_universe(packet: Packet) -> list[str]:
    return sorted(
        {str(e.raw["option_chain_id"]) for e in packet.events if e.kind == "option_trade"}
    )


def session_exit(packet: Packet) -> datetime:
    return datetime.combine(packet.session, datetime.min.time(), NY).replace(hour=15, minute=55)


def index_observations(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_contract: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        symbol = str(observation["quote"].get("symbol", ""))
        by_contract.setdefault(symbol, []).append(observation)
    for values in by_contract.values():
        values.sort(key=lambda q: stamp(q["received_at"]))
    return by_contract


def mark_contract(
    packet: Packet,
    contract: str,
    observations: list[dict[str, Any]],
    available: datetime,
    *,
    validity: int,
    max_price: float,
    group: str,
    ranked_action: str,
) -> dict[str, Any]:
    """Same 15:55 ET ask-in/bid-out mark used by the model arm."""
    exit_at = session_exit(packet)
    config = packet.config
    entry: dict[str, Any] | None = None
    exit_mark: dict[str, Any] | None = None
    marks: list[float] = []
    for observation in observations:
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
            100 * (exit_mark["price"] - entry["price"]) - 2 * config.commission_per_contract_side,
            4,
        )
    return {
        "option_symbol": contract,
        "group": group,
        "ranked_action": ranked_action,
        "status": "closed_simulation" if exit_mark else "missing_exit" if entry else "not_filled",
        "entry": entry,
        "exit": exit_mark,
        "paper_net_usd": pnl,
        "sampled_best_bid": max(marks) if marks else None,
        "sampled_worst_bid": min(marks) if marks else None,
    }


def _portfolio_net(rows: list[dict[str, Any]]) -> float | None:
    if any(row["status"] == "missing_exit" for row in rows):
        return None
    return round(sum(row["paper_net_usd"] or 0 for row in rows), 4)


def mechanical_mark(
    packet: Packet,
    contract: str,
    observations: list[dict[str, Any]],
    available: datetime,
) -> dict[str, Any]:
    return mark_contract(
        packet,
        contract,
        observations,
        available,
        validity=MECHANICAL_VALIDITY_SECONDS,
        max_price=math.inf,
        group="mechanical",
        ranked_action="mechanical",
    )


def ask_side_premium(packet: Packet) -> dict[str, float]:
    """Sum UW-tagged ask-side premium per printed contract. Never infer side from NBBO."""
    premiums: dict[str, float] = {contract: 0.0 for contract in printed_universe(packet)}
    for event in packet.events:
        if event.kind != "option_trade":
            continue
        contract = str(event.raw.get("option_chain_id") or "")
        if contract not in premiums:
            continue
        if provider_aggressor(event.raw).get("label") != "ask_side":
            continue
        try:
            raw_premium = event.raw.get("premium")
            if raw_premium not in (None, ""):
                premiums[contract] += float(raw_premium)
                continue
            price = float(event.raw.get("price") or 0)
            size = float(event.raw.get("size") or 0)
            premiums[contract] += price * size * 100
        except (TypeError, ValueError):
            continue
    return premiums


def percentile_rank(value: float, samples: list[float]) -> float:
    if not samples:
        raise ValueError("percentile requires samples")
    less = sum(1 for item in samples if item < value)
    equal = sum(1 for item in samples if item == value)
    return round(100.0 * (less + 0.5 * equal) / len(samples), 4)


def random_k_rng(packet_hash: str) -> random.Random:
    return random.Random(int(digest(f"{RANDOM_K_SEED}:{packet_hash}")[:16], 16))


def _draw_net(marks: dict[str, dict[str, Any]], contracts: list[str]) -> float | None:
    return _portfolio_net([marks[c] for c in contracts])


def compute_baselines(
    packet: Packet,
    record: dict[str, Any],
    observations: list[dict[str, Any]],
    core: dict[str, Any],
) -> dict[str, Any]:
    available = stamp(record["received_at"])
    universe = [row["option_symbol"] for row in core["rows"]]
    by_contract = index_observations(observations)
    mechanical = {
        contract: mechanical_mark(packet, contract, by_contract.get(contract, []), available)
        for contract in universe
    }
    k = int(core["selected_count"])
    model_net = core["selected_net_before_api_and_infra_usd"]
    premiums = ask_side_premium(packet)
    ranked = sorted(universe, key=lambda c: (-premiums.get(c, 0.0), c))
    top = ranked[:k]
    mechanical_rows = [mechanical[c] for c in top]
    mechanical_net = _portfolio_net(mechanical_rows) if k else 0.0
    draws: list[float] = []
    incomplete_draws = 0
    if k and universe:
        rng = random_k_rng(str(core["packet_hash"]))
        size = min(k, len(universe))
        for _ in range(RANDOM_K_DRAWS):
            pick = rng.sample(universe, size)
            net = _draw_net(mechanical, pick)
            if net is None:
                incomplete_draws += 1
                continue
            draws.append(net)
    percentile = (
        percentile_rank(model_net, draws) if model_net is not None and draws else None
    )
    selected_rows = [row for row in core["rows"] if row["group"] == "selected"]
    entry_lags: list[dict[str, Any]] = []
    for row in selected_rows:
        if not row.get("entry"):
            continue
        entry_lags.append(
            {
                "option_symbol": row["option_symbol"],
                "entry_minus_decision_seconds": round(
                    (stamp(row["entry"]["at"]) - available).total_seconds(), 4
                ),
            }
        )
    lag_values = [item["entry_minus_decision_seconds"] for item in entry_lags]
    return {
        "same_packet_hash": core["packet_hash"],
        "same_exit": "15:55 ET",
        "k": k,
        "model_net_usd": model_net,
        "random_k": {
            "draws": RANDOM_K_DRAWS,
            "seed": RANDOM_K_SEED,
            "k": k,
            "complete_draws": len(draws),
            "incomplete_draws": incomplete_draws,
            "percentile": percentile,
            "mean_net_usd": round(sum(draws) / len(draws), 4) if draws else None,
            "median_net_usd": (
                round(sorted(draws)[len(draws) // 2], 4) if draws else None
            ),
        },
        "mechanical_top_k_ask_side_premium": {
            "k": k,
            "option_symbols": top,
            "net_usd": mechanical_net,
            "premium_by_contract": {c: round(premiums.get(c, 0.0), 4) for c in top},
        },
        "abstain": {"selected_count": 0, "net_usd": 0.0},
        "latency": {
            "knowledge_cutoff": packet.knowledge_cutoff.isoformat(),
            "decision_received_at": available.isoformat(),
            "decision_minus_knowledge_cutoff_seconds": round(
                (available - packet.knowledge_cutoff).total_seconds(), 4
            ),
            "entries": entry_lags,
            "mean_entry_minus_decision_seconds": (
                round(sum(lag_values) / len(lag_values), 4) if lag_values else None
            ),
            "unfilled_selected": sum(1 for row in selected_rows if row["status"] == "not_filled"),
        },
    }


def evaluate_core(
    packet: Packet, record: dict[str, Any], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    if record["packet_hash"] != digest(packet.model_dump(mode="json")):
        raise ValueError("decision/packet hash mismatch")
    decision = Decision.model_validate(record["decision"])
    decision.validate_evidence(packet)
    available = stamp(record["received_at"])
    if available < packet.knowledge_cutoff:
        raise ValueError("decision predates packet")
    picks = {p.option_symbol: p for p in decision.picks}
    universe = printed_universe(packet)
    by_contract = index_observations(observations)
    rows: list[dict[str, Any]] = []
    for contract in universe:
        pick = picks.get(contract)
        eligible = pick is not None and pick.action == "enter"
        validity = pick.valid_for_seconds if pick else MECHANICAL_VALIDITY_SECONDS
        max_price = pick.max_entry_price if pick else math.inf
        rows.append(
            mark_contract(
                packet,
                contract,
                by_contract.get(contract, []),
                available,
                validity=validity,
                max_price=max_price,
                group="selected" if eligible else "counterfactual",
                ranked_action=pick.action if pick else "unranked",
            )
        )
    selected = [r for r in rows if r["group"] == "selected"]
    usage = record.get("usage", {})
    config = packet.config
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
    net = _portfolio_net(selected)
    return {
        "paper_only": True,
        "synthetic": packet.synthetic,
        "session": str(packet.session),
        "packet_hash": record["packet_hash"],
        "decision_hash": digest(record),
        "selected_count": len(selected),
        "selected_net_before_api_and_infra_usd": net,
        "estimated_api_cost_usd": estimated_api,
        "selected_net_after_estimated_api_usd": round(net - estimated_api, 4)
        if net is not None and estimated_api is not None
        else None,
        "rows": rows,
        "limitations": list(ORIGINAL_LIMITATIONS),
    }


def original_evaluation_fields(report: dict[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in ORIGINAL_EVALUATION_KEYS}


def evaluate(
    packet: Packet, record: dict[str, Any], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    core = evaluate_core(packet, record, observations)
    result = dict(core)
    result["baselines"] = compute_baselines(packet, record, observations, core)
    return result


def monitor(packet: Packet, record: dict[str, Any], directory: Path, feed: ReadFeed) -> None:
    until = datetime.combine(packet.session, datetime.min.time(), NY).replace(
        hour=15, minute=56, second=30
    )
    if now_utc().astimezone(NY).date() != packet.session or now_utc() >= until:
        raise ValueError("monitor requires the same active session")
    contracts = printed_universe(packet)
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
