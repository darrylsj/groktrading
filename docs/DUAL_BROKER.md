# Dual-broker plan

Operator will trade on **both Tradier and Schwab**. Phase A (this tree) only
introduces a venue-aware `Broker` protocol and extracts the existing Tradier
client behind `TradierBroker`. **Live Tradier order behavior is unchanged.**

## Phases

| Phase | Status | What |
| --- | --- | --- |
| A (this) | Protocol + Tradier extract | `venue_id` is `Literal["tradier"]`. Paper/live paths call `Broker`, not ad-hoc Tradier methods. |
| B/C | After Schwab OAuth Ready For Use | Implement `SchwabBroker`. No Schwab credentials in this repo. No live Schwab calls until then. |

`src/groktrading/brokers/schwab.py` is a placeholder: construction raises
`NotImplementedError` (`Schwab OAuth not ready`). It accepts no tokens and
opens no sockets.

## Hard rules

1. **No dual-fire of the same print.** A signal may be previewed/submitted on at
   most one venue (`refuse_dual_fire`). Never send the same UW print to Tradier
   and Schwab.
2. **Exits follow the holding venue.** Close or cancel where the lot was opened
   (`exit_venue`). A Tradier fill is not exited on Schwab, and the reverse.
3. **Tuesday Opening15 is untouched.** The 2026-09-08 clean baseline remains
   `research.cli run` (packet-only capture → recommend → paper monitor). That
   path must not import `groktrading.brokers`, must not preview/submit, and is
   not a dual-broker experiment. Expanded Context portfolio stays Tradier
   read-only GET until Schwab OAuth — research context, not this execution
   protocol.

## Surfaces (Phase A)

`Broker` covers balances, positions, option quote (gate inputs), preview and
submit of an option order, find-by-tag, and cancel of working **entry** orders
only (no flatten). `OrderMachine` still uses the preview/submit/find subset
(`OrderBroker`). `Executor` can attach `BrokerSink` so paper/live stubs go
through the same venue object. `RecordingBroker` / `RecordingOrderBroker`
remain in-memory test doubles.

Schwab is not wired. Selecting venue `schwab` raises the OAuth-not-ready error.
