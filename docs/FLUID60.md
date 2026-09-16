# Fluid60: one-minute fluid-book trading research

Fluid60 is a runnable, isolated stock/options research engine. It forecasts the
next 60 seconds, optimizes inventory after costs, and records paper fills from
subsequent quotes. It has no broker order client. Its settings do not replace the
live trading card, Opening15 experiment, or Helsinki services.

## Run the offline experiment

```bash
python -m pip install -e '.[dev,fluid]'
groktrading-fluid60 demo --out research-runs/fluid60-demo --minutes 8
```

The command creates a synthetic event tape, fitted transport parameters, config,
full replay report, and persistence baseline. Use a new output directory on each
run. The fixture intentionally has upward prices and buying pressure to exercise
the plumbing; its returns provide **no evidence of a market edge**. It includes
stock, call, and put quotes. A trade is optional at every minute.

The default research basket is AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD,
AVGO, PLTR. This is a configurable liquid-stock basket, not a point-in-time ranking
of the historical top ten. Select a universe using information available before
each test period when studying selection bias.

## What is optimized

At each regular-session minute, enumerate every feasible combination of:

- Keep positions, or close one existing position.
- Open one new stock lot or one standard option contract, or buy nothing.

The **whole research desk** can submit at most one buy and one sell per minute.
Sells close long positions; negative underlying forecasts can select long puts.
There are no stock shorts, naked options, or multi-leg orders. Stock lot size is
configurable. Each instrument can have only one open lot.

For each candidate inventory, the policy calculates:

`score = expected change in liquidation wealth - downside_weight × expected loss`

The comparison is against holding the current inventory. Buy costs include the
ask, slippage, fees, and contract multiplier. Future liquidation proceeds include
the modeled future bid, exit slippage, and exit fee. Existing entry costs are
sunk when deciding whether to keep a position; they remain in realized P&L.
Risk penalties are summed per instrument: independently simulated stock paths
are **not** represented as a calibrated joint portfolio distribution.

The best feasible action must improve the hold score by `minimum_improvement`
dollars. Default constraints reserve $5,000 of $25,000 initial research capital,
limit each purchase to 10% of initial capital, and reject wide/stale quotes or
insufficient displayed size. Reserve is a fixed initial-capital floor, not a
broker buying-power or settlement calculation. Entries stop at 15:59 New York
time. The default five-minute maximum holding time puts old positions into an
exit queue, oldest first, and blocks new buying until the queue clears. Missing
forecasts also request an exit. An exit can remain unfilled; it is never assumed
to have executed. This is a distinct experimental horizon, not a change to the
production policy that permits overnight positions.

## Fluid model

The state is two nonnegative liquidity densities on the observed price lattice.
Price gaps remain empty cells. The deep book evolves by a conservative finite
volume transport step, plus limit-order arrivals, cancellations, and execution:

`dq/dt = -d(v q)/dp + D d²q/dp² + arrivals - cancellations - executions`

The two cells nearest each best quote retain queues without spatial diffusion.
Market orders consume the nearest occupied queues first. Limit orders can improve
quotes inside the spread. This moving interface is important: a buy-driven price
rise must allow the bid to follow the ask. Gamma-Poisson intensities introduce
bursts. Cancellations use a depth-scaled hazard. The model simulates 60 one-second
steps and returns an ensemble of terminal midpoints and spreads.

This is a reduced fluid/queue model, not a literal incompressible Navier–Stokes
solver. It does not conserve liquidity across placements or cancellations.
Transport alone conserves shares and obeys a stability bound. Queues retain a
fluid cancellation approximation and a one-share occupancy threshold; they do
not simulate every exchange queue priority or hidden order.

`calibrate` selects effective diffusion and drift from nine candidates on
completed, historical depth-shape transitions in absolute price coordinates.
Trailing event counts estimate source/sink rates causally. The default 25%
inside-spread placement fraction and burst distribution are explicit research
priors, not fitted exchange laws. The fixed price domain spans observed depth;
if **any** simulated path reaches/exhausts a boundary, the entire forecast is
unusable for trading. No favorable survivor-only forecast is reported as valid.

The fitted model is deliberately modest. It needs real-data comparison with
order-flow imbalance, queue imbalance/microprice, and a flexible statistical
model before attributing any benefit specifically to fluid dynamics. The shipped
CLI includes a no-price-change persistence control and its forecast MSE.

## Options

Option price scenarios use a local expansion:

`dV ≈ delta × dS + 0.5 × gamma × dS² + theta_per_day / 1440 + vega_per_vol_point × dIV`

Theta is dollars per share per calendar day. Vega is dollars per share per one
volatility percentage point. The three IV scenarios are negative, zero, and
positive `option_iv_shock_points`; their equal weighting is a stress assumption,
not a learned probability distribution. The current option spread is held fixed
in this valuation approximation. Quotes, timestamped Greeks, standard 100-share
terms, and explicit expiry are required. Near-expiry contracts and excessive
underlying moves are excluded. Actual entry/exit P&L always uses subsequent
option bid/ask quotes, including the multiplier and both contract fees.

`signed_option_flow` converts provider-classified, single-leg UW trades into
`buy_or_sell_sign × size × 100 × signed_delta`. Unknown aggressor side and multi-leg
trades are excluded. Revisions affect only decisions after their receipt time.
This is an exposure-flow proxy, not observed dealer inventory or hedge demand.
`options_beta` defaults to zero and is not fitted by the current calibrator.
An independently trained coefficient can be supplied in a frozen parameter file.
The existing filtered Helsinki flow ledger lacks the balanced trades/fields
needed to substitute for this input.

## Historical data and real-time APIs

```bash
python -m pip install -e '.[fluid-feed]'

# DATABENTO_API_KEY must already be available in the process environment.
# This requests licensed historical data and may consume provider credits.
# Begin before the exchange's daily clear, not at an arbitrary intraday point.
groktrading-fluid60 capture-databento --symbol AAPL \
  --start 2026-08-03T00:00:00Z --end 2026-08-04T00:00:00Z \
  --delivery-delay-ms 100 --out research-runs/aapl-training.jsonl

# Omitting start/end subscribes live with a fresh snapshot. Stop with Ctrl-C.
groktrading-fluid60 capture-databento --symbol AAPL \
  --out research-runs/aapl-live.jsonl
```

This adapter uses **XNAS.ITCH MBO**, representing Nasdaq displayed liquidity,
not all US venues. It processes completed `F_LAST` batches, requires an initial
clear/snapshot, and emits approximately one-second book frames and stock quotes.
Adds, cancels, and modifications update resting size; trade/fill messages never
decrement it twice. A fill associated with a cancellation labels executed flow.
Snapshot placements are excluded from arrival rates. Unknown orders, sequence
regressions, suspect-book/time flags, and feed errors stop capture. Sequence
monotonicity alone does not prove a complete exchange feed. Capture is one symbol
per invocation; it currently rebuilds price totals from orders at sample time,
so benchmark throughput and receipt lag before running a full basket on Helsinki.

Historical availability is provider `ts_recv` plus the declared delivery delay;
live availability uses local receipt time. Tune this delay from measurements.
Both use actual event timestamps for freshness. A historical provider receive
timestamp does not by itself reproduce delivery latency to Helsinki. Reconnects
require a fresh reconstruction. Prices must fit the declared tick grid (the
adapter currently assumes $0.01); other tick sizes require adapter configuration
work, rather than rounding the tape. Full exchange status, auction, corporate
action, and consolidated venue handling remain integration work.

The typed `Quote` event also accepts production Tradier stock or option quotes.
`quote-tradier` makes one read-only request using `TRADIER_PRODUCTION_TOKEN`:

```bash
groktrading-fluid60 quote-tradier --terms research-runs/quote-terms.json \
  --out research-runs/quotes-001.jsonl
```

Example terms file (verify provider size/Greek units before using these scales):

```json
{
  "AAPL": {
    "underlying": "AAPL", "asset": "stock", "size_multiplier": 1,
    "theta_per_day_scale": 1, "vega_per_vol_point_scale": 1
  }
}
```

For an option, use its actual provider symbol as the key, set `asset` to `call` or
`put`, and provide its verified `expires_at` timestamp. The parser uses the older
bid/ask timestamp and does not invent missing Greek timestamps. Snapshot polling
and a historical option quote archive must be scheduled/collected separately;
this command is not an options-history downloader. The UW normalization helper
is supplied, but a new UW collector is not wired into the current Helsinki ledger.
Finnhub stock prints alone cannot reconstruct the required depth state.

For forward paper integration, feed `BookFrame`, `Quote`, and `OptionFlow` events
to `PaperEngine.ingest` in receipt order and drive `advance` at minute boundaries.
The engine exposes new decisions, fills, and reports in memory. Account for
processing/forecast latency in the chosen delay. Persist raw arrivals outside
this engine before processing. It is a single-process research engine without
durable restart recovery or production throughput guarantees.

## Train, validate, then test

```bash
groktrading-fluid60 calibrate --events research-runs/train.jsonl \
  --out research-runs/parameters.json

groktrading-fluid60 tune --events research-runs/validation.jsonl \
  --parameters research-runs/parameters.json \
  --out research-runs/selected-config.json

groktrading-fluid60 replay --events research-runs/test.jsonl \
  --parameters research-runs/parameters.json --config research-runs/selected-config.json \
  --out research-runs/test-fluid.json

groktrading-fluid60 replay --events research-runs/test.jsonl \
  --parameters research-runs/parameters.json --config research-runs/selected-config.json \
  --model persistence --out research-runs/test-persistence.json
```

Use separate chronological tapes. Validation must start after calibration ends.
Six predefined combinations of minimum improvement and downside penalty are
scored on validation net liquidation P&L. Selection writes both an audit and the
validation cutoff into the config. That config cannot open positions at or before
its selection cutoff. Freeze the model, config, universe, and cost assumptions
before the test; never select parameters on the final test results. Include enough
prior data to warm the causal lookback. Repeat this protocol across later blocks
for walk-forward evaluation; automatic fold scheduling is not supplied.

Merge multi-symbol/provider tapes **by recorded receipt time** before replay,
preserving each stream's order. Do not relabel event time as arrival time or
backfill revisions into old decisions. The replay rejects backward timestamps
and conflicting duplicates. Synthetic and real tapes/models cannot be mixed.

## Accounting and interpretation

Decisions precede events with the same timestamp. Pending orders become eligible
after the configured latency, expire within the minute, and require a new quote
whose event time is also after eligibility. Buys use ask plus slippage, sells bid
minus slippage; the decision's limit and displayed size must permit the entire
lot. There are no midpoint fills, partial-fill simulations, or assumed fills
from minute bars. Buys cannot spend proceeds from an unfilled sale. Research cash
does not model settlement, margin, regulatory account limits, or market impact
beyond the configured slippage and displayed-size check.

The report includes decisions, submitted/expired paper orders, quote-linked fills,
fees, realized P&L, estimated liquidation equity, residual positions, pending
orders, drawdown at minute/fill observations, and forecast errors against the
persistence control. Missing fresh or sufficiently sized final quotes produce
**null** net P&L, not invented liquidation. With open positions, net P&L includes
an unrealized bid-side liquidation estimate; realized P&L remains separate.
Final pending orders remain visible. No sale is fabricated at the end of a tape.

Compare `forecast_mse` with `zero_return_mse` **inside the same report**: these use
the same scored observations. Separate fluid and persistence runs may have
different forecast coverage because the fluid model can reject a simulated
boundary failure. Report the coverage counts alongside errors; lower error on a
selected subset is not by itself evidence of improvement over the full tape.

No real vendor data or API keys are required for tests. The SDK contract and
normalizers can be tested offline, but API entitlements, venue coverage, actual
latency, and execution realism require real-data validation. A positive synthetic
demo, directional accuracy, or validation winner cannot establish tradable edge.

## Primary references

- [Microscopic limit order books and stochastic PDE limits](https://arxiv.org/abs/1808.07107)
- [Latent and revealed liquidity dynamics](https://arxiv.org/abs/1808.09677)
- [Databento MBO book construction](https://databento.com/docs/examples/order-book/limit-order-book)
- [Databento MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo)
- [Tradier market quotes API](https://docs.tradier.com/reference/brokerage-api-markets-get-quotes)
