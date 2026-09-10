"""Two-sided finite-volume transport with stochastic source/sink and queue depletion.

This is a reduced fluid/queue research model, not literal Navier-Stokes. Empty
outer books are censored rather than extrapolated into profitable price jumps.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import numpy as np
from numpy.typing import NDArray

from .schema import BookFrame, Config, Forecast, Parameters, digest

Array = NDArray[np.float64]


def transport(q: Array, diffusion: float, drift: float) -> Array:
    """One-second upwind conservative flux, no flux at outer boundaries.

    Grid spacing is one tick. CFL: 2*D + abs(v) <= 1. No sources here.
    Positive drift is toward larger array indexes (away from touch).
    """
    if diffusion < 0 or 2 * diffusion + abs(drift) > 1:
        raise ValueError("unstable transport step")
    flux = diffusion * (q[:, :-1] - q[:, 1:])
    flux += max(drift, 0) * q[:, :-1] + min(drift, 0) * q[:, 1:]
    out = q.copy()
    out[:, :-1] -= flux
    out[:, 1:] += flux
    return out


def consume(q: Array, demand: Array) -> Array:
    """Consume nearest occupied queues first; return unfilled demand."""
    before = np.cumsum(q, axis=1) - q
    taken = np.minimum(q, np.maximum(demand[:, None] - before, 0))
    q -= taken
    return cast(Array, np.maximum(demand - taken.sum(axis=1), 0))


def evolve(
    last: BookFrame,
    rates: dict[str, float],
    config: Config,
    params: Parameters,
    rng: np.random.Generator,
) -> tuple[Array, Array, Array]:
    """Fixed observed domain, moving best quotes, fluid depth and discrete arrivals.

    Liquidity may improve a quote inside the spread, allowing either best quote
    to move in either direction. No new liquidity is invented outside the domain.
    Two cells nearest each touch retain their queues without spatial diffusion.
    """
    bp, b0 = grid(last, "bid", config.grid_cells)
    ap, a0 = grid(last, "ask", config.grid_cells)
    ticks = np.arange(round(bp[-1] / last.tick), round(ap[-1] / last.tick) + 1)
    prices = ticks.astype(float) * last.tick
    n = len(prices)
    if n > config.grid_cells * 2 + 100:
        raise ValueError("spread_exceeds_grid_budget")
    bid = np.zeros((config.paths, n), dtype=float)
    ask = np.zeros_like(bid)
    bid[:, np.rint(bp / last.tick).astype(int) - ticks[0]] = b0
    ask[:, np.rint(ap / last.tick).astype(int) - ticks[0]] = a0
    indexes = np.arange(n)[None, :]
    rows = np.arange(config.paths)
    failed = np.zeros(config.paths, dtype=bool)

    def touches() -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        bi = (n - 1 - np.argmax((bid >= 1)[:, ::-1], axis=1)).astype(np.int64)
        ai = np.argmax(ask >= 1, axis=1).astype(np.int64)
        return bi, ai

    for _ in range(config.horizon_seconds):
        bi, ai = touches()
        bid_priority = rng.random(config.paths) < 0.5
        failed |= ~np.any(bid >= 1, axis=1) | ~np.any(ask >= 1, axis=1)
        for side, q, touch, is_bid in (("bid", bid, bi, True), ("ask", ask, ai, False)):
            # No-flux interface two ticks behind touch. Transport conserves shares.
            deep = indexes < touch[:, None] - 1 if is_bid else indexes > touch[:, None] + 1
            allowed = deep[:, :-1] & deep[:, 1:]
            d, v = params.diffusion_ticks2_per_second, params.drift_ticks_per_second
            flux = (
                d * (q[:, :-1] - q[:, 1:]) + max(v, 0) * q[:, :-1] + min(v, 0) * q[:, 1:]
            ) * allowed
            q[:, :-1] -= flux
            q[:, 1:] += flux
            hazard = min(rates[side + "_cancel"] / max(q.sum(axis=1).mean(), 1), 1)
            q *= 1 - hazard
            intensity = rng.gamma(4, max(rates[side + "_add"], 1e-12) / 4, config.paths)
            total = rng.poisson(intensity)
            improve = rng.binomial(total, params.inside_spread_fraction) * (ai - bi >= 2)
            improved_index = np.minimum(bi + 1, n - 1) if is_bid else np.maximum(ai - 1, 0)
            # Random priority avoids systematically giving bids the sole free price.
            if side == "bid":
                improve = improve * ((ai - bi != 2) | bid_priority)
            if side == "ask":
                improve = improve * (bid[rows, improved_index] < 1)
            q[rows, improved_index] += improve
            distance = touch[:, None] - indexes if is_bid else indexes - touch[:, None]
            weights = np.exp(-np.clip(distance, 0, 100) / 8) * (distance >= 0)
            weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1)
            q += rng.poisson((total - improve)[:, None] * weights)
        for q, key, reverse in ((ask, "buy", False), (bid, "sell", True)):
            intensity = rng.gamma(4, max(rates[key], 1e-12) / 4, config.paths)
            failed |= (
                consume(q[:, ::-1] if reverse else q, rng.poisson(intensity).astype(float)) > 1e-8
            )
        bi, ai = touches()
        failed |= (bi >= ai) | (bi == 0) | (ai == n - 1)
    bi, ai = touches()
    failed |= ~np.any(bid >= 1, axis=1) | ~np.any(ask >= 1, axis=1)
    mids = (prices[bi] + prices[ai]) / 2
    spreads = prices[ai] - prices[bi]
    return mids, spreads, failed.astype(float)


def grid(frame: BookFrame, side: str, cells: int) -> tuple[Array, Array]:
    levels = frame.bids if side == "bid" else frame.asks
    sign = -1 if side == "bid" else 1
    # Only span observed prices. Gaps inside that span are true zero-depth cells.
    n = min(cells, round(abs(levels[-1].price - levels[0].price) / frame.tick) + 1)
    prices = levels[0].price + sign * frame.tick * np.arange(n, dtype=float)
    depth = np.zeros(n, dtype=float)
    for level in levels:
        j = round(abs(level.price - levels[0].price) / frame.tick)
        if j < n:
            depth[j] = level.size
    return prices, depth


def forecast(
    history: list[BookFrame],
    at: datetime,
    config: Config,
    params: Parameters,
    options_flow: float = 0,
) -> Forecast:
    if not history or params.trained_through >= at:
        raise ValueError("missing history or model not trained before cutoff")
    frames = [
        f
        for f in history
        if at - timedelta(seconds=config.lookback_seconds) <= f.interval_start
        and f.received_at <= at
    ]
    if not frames:
        raise ValueError("insufficient_history")
    last = frames[-1]
    if any(f.symbol != last.symbol or f.source != last.source for f in frames):
        raise ValueError("mixed book identity")
    if params.source != last.source:
        raise ValueError("model source mismatch")
    if any(not f.complete or not f.trading for f in frames):
        raise ValueError("incomplete_or_halted_book")
    if any(
        (f.received_at - f.interval_start).total_seconds() > config.max_gap_seconds for f in frames
    ):
        raise ValueError("oversized_flow_interval")
    if (at - last.event_at).total_seconds() > config.max_age_seconds:
        raise ValueError("stale_book")
    if any(
        (b.interval_start - a.received_at).total_seconds() > config.max_gap_seconds
        or b.interval_start < a.received_at
        for a, b in zip(frames, frames[1:], strict=False)
    ):
        raise ValueError("gapped_or_overlapping_flow_intervals")
    elapsed = sum((f.received_at - f.interval_start).total_seconds() for f in frames)
    if elapsed < config.min_history_seconds:
        raise ValueError("insufficient_history")
    rates = {
        k: sum(getattr(f.flows, k) for f in frames) / elapsed
        for k in ("bid_add", "ask_add", "bid_cancel", "ask_cancel", "buy", "sell")
    }
    flow_ratio = options_flow / max((rates["buy"] + rates["sell"]) * 60, 1)
    forcing = np.clip(params.options_beta * flow_ratio, -1, 1)
    rates["buy"] *= float(np.exp(forcing))
    rates["sell"] *= float(np.exp(-forcing))
    seed = int(digest([config.seed, last.symbol, at.isoformat()])[:16], 16)
    rng = np.random.default_rng(seed)
    mids, spreads, failed = evolve(last, rates, config, params, rng)
    fraction = float(failed.mean())
    # Preserve all paths. Failed paths are never used by the trading policy.
    mids[failed.astype(bool)] = last.mid
    return Forecast(
        symbol=last.symbol,
        at=at,
        expires_at=at + timedelta(seconds=60),
        mid=last.mid,
        future_mids=tuple(mids.tolist()),
        future_spreads=tuple(spreads.tolist()),
        domain_failure_fraction=fraction,
        # A censored path has no known distribution; no conditioning on survivors.
        status="out_of_domain" if fraction > 0 else "valid",
        model_hash=digest([params.model_dump(mode="json"), config.model_dump(mode="json")]),
        data_hash=digest(
            {"frames": [f.model_dump(mode="json") for f in frames], "options_flow": options_flow}
        ),
    )


def calibrate(frames: list[BookFrame], cells: int = 64) -> Parameters:
    """Fit effective spatial smoothing/drift on completed training transitions.

    Scores normalized depth shapes in fixed absolute-price coordinates. Arrival,
    cancellation and execution *rates* are estimated online from trailing frames.
    This modest fit does not identify individual traders' quote migration.
    """
    if len(frames) < 3 or len({f.source for f in frames}) != 1:
        raise ValueError("need >=3 homogeneous training frames")
    ordered = sorted(frames, key=lambda f: (f.symbol, f.received_at))
    pairs = [
        (a, b)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if a.symbol == b.symbol
        and a.complete
        and b.complete
        and a.trading
        and b.trading
        and a.tick == b.tick
        and 0 < (b.received_at - a.received_at).total_seconds() <= 2
    ]
    if not pairs:
        raise ValueError("no valid training transitions")
    scores: list[tuple[float, float, float]] = []
    for diffusion in (0.0, 0.02, 0.10):
        for drift in (-0.05, 0.0, 0.05):
            loss = 0.0
            for a, b in pairs:
                dt = (b.received_at - a.received_at).total_seconds()
                for side, sign in (("bid", -1), ("ask", 1)):
                    prices, q = grid(a, side, cells)
                    target_map = {
                        round(x.price / a.tick): x.size
                        for x in (b.bids if side == "bid" else b.asks)
                    }
                    target = np.array(
                        [target_map.get(round(p / a.tick), 0) for p in prices], dtype=float
                    )
                    pred = transport(q[None, :], diffusion * dt, sign * drift * dt)[0]
                    pred /= max(pred.sum(), 1)
                    target /= max(target.sum(), 1)
                    loss += float(np.square(pred - target).mean())
            scores.append((loss, diffusion, drift))
    _, diffusion, drift = min(scores, key=lambda x: (x[0], x[1], abs(x[2])))
    return Parameters(
        trained_through=max(f.received_at for f in frames),
        source=frames[0].source,
        diffusion_ticks2_per_second=diffusion,
        drift_ticks_per_second=drift,
        training_hash=digest([f.model_dump(mode="json") for f in ordered]),
        observations=len(pairs),
    )
