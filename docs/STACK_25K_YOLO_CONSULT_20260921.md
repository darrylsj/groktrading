# $25k YOLO stack consult — 2026-09-21

Sanitized read-only consult (Codex, planning frame). No files were changed
and no broker calls were made in that pass. Dollar amounts below are
**planning-only** budgets for a funded $25,000 book. They are not quotes,
not live-rule changes, and not a profitability claim.

Prompt constraints that still bind this repo: no raw live POST, Trade Machine
to Tradier sandbox first, buy-to-open puts on IWM/SPY/QQQ refused, Options AI
in-app paper is not Tradier paper, and Options AI broker-connect to the live
account stays off.

## Verdict

The stack can improve expected results through structure, timing, and
execution. The desk has not demonstrated that edge. Dashboard scraping
alone is mostly process theater.

## Tool roles

| Product | Use | Ignore |
| --- | --- | --- |
| TradingView | Screen liquid names; define breakout, reclaim, failure, and invalidation; send alerts into an evaluation queue | Indicator voting, repainting backtests, treating stock returns as option returns |
| Options AI | Turn a view and horizon into competing structures. Fast Trade → Compare → Chart Trade. Scanner for discovery | “High PoP” as an edge, default strikes as optimal, mid prices as achievable fills |
| Unusual Whales | Fresh aggressive flow versus the underlying, repeats, and tide | Ask-side calls as proof of bullish opening buys; dark-pool prints as direction |
| Tradier | Resolve contracts, executable quotes, buying power, gated execution, fills | Sandbox fills as evidence of live execution quality. Sandbox data is delayed |
| Finnhub | Earnings, news, fundamentals, event context | News sentiment as an automatic direction; a missing event as “no catalyst” |
| Trade Machine | Today candidates, verify **Active**, Show Options, keep the stated entry and exit | Headline backtest returns, tiny samples, assuming Today means currently actionable |

Options AI Expected Move is **92.5% of the ATM straddle** for that expiry,
not a 92.5% probability.
[Expected Move](https://support.optionsai.com/options-ai-support/how-options-ai-works/expected-move).
Trade Machine rows can remain after conditions change. Recheck Active.
[Today Tab 2.0](https://learn.trademachine.com/docs/today-tab-2-0).

Do not require every product to agree. Agreement is not independent evidence.

## Two lanes, one execution discipline

`UW / TM / OAI ideas → timestamped candidate → catalyst and structure → size → existing gate → manage → attribute`

- **Fast lane:** Continual15 / Unusual Whales, with TradingView as a predefined trigger and Finnhub as cached context. Tradier supplies the executable price. Live eligibility is unchanged: thesis, freshness, cash/equity at least 20%, ask-drift, standing refusals, and `live_order_gate`. A vendor alert cannot submit.
- **Slower lane:** Trade Machine Active or Options AI Scanner. Resolve the exact structure. Trade Machine enters **Tradier sandbox first**. Options AI in-app paper is a separate learning ledger.

A shared candidate needs source time, receipt time, thesis, hold, catalyst, exact legs, quote times, executable limit, max loss, invalidation, exit rules, and account realm (shadow, paper, or live).

Recommended cadence, not a vendor latency promise: Trade Machine about every 30 minutes with an Active recheck before any paper entry; Options AI on shortlist change plus a morning and midday Compare; Tradier quotes refreshed immediately before any submit. Target under 30 seconds from receipt to a completed fast-lane evaluation, and measure source delay separately. Opportunity wakes stay paused until their own proof passes.

## Ranking hypothesis (not a proven order)

1. Fresh Unusual Whales aggression before the underlying move, if existing flow and thesis gates pass and a TradingView trigger confirms without chasing.
2. Trade Machine **Active + Show Options**, complete and reproducible. Sandbox first.
3. Options AI debit spread or long call for a strong directional thesis, after Compare.
4. Options AI defined-risk credit only with an explicit reason the implied move exceeds the desk’s expected move.
5. Near Active, category lists, and isolated dark-pool prints: watch only.

High PoP can still lose money. Recompute at the intended limit. Options AI cards use mids and exclude fees.
[Compare](https://support.optionsai.com/options-ai-support/how-options-ai-works/set-a-target).

Refuse every buy-to-open put on IWM, SPY, and QQQ, including a long put inside a put spread.

## Planning-only $25k budgets

These are aggressive evaluation budgets, not an optimized allocation and not a live unlock.

| Exposure | Proposed maximum contractual loss |
| --- | ---: |
| New setup pilot | $125–$250 (0.5–1%) |
| Ordinary established idea | $500 (2%) |
| Highest-quality, independently supported thesis | $1,000 (4%), including adds |
| 0DTE or binary-event experiment | $125–$250, inside the portfolio budget |
| One correlated theme | $2,000 (8%) |
| All open positions | $5,000 (20%) initially |

Keep cash/equity at least 20%. Size from actual max loss, not from a stop. Overnight is allowed only with an explicit multiday thesis; the consult’s proposed overnight full-loss budget is $2,500 aggregate, with binary events at pilot size. Current live exit rules stay in place while alternatives are compared in shadow.

## Week-1 cadence (2026-09-21 through 2026-09-25, times ET)

| Time | Checklist |
| --- | --- |
| 09:30–09:45 | Existing new-entry stand-down. Reconcile. Event context. Tide/flow. Prepare Options AI alternatives. |
| 09:45–11:00 | Continual15 plus permitted alerts. Rank fresh flow. Pull Trade Machine as the board populates and verify Active one by one. |
| 11:00–12:00 | Main Trade Machine Active → Show Options → OCC → sandbox pass. Options AI Fast Trade / Scanner → Compare on the shortlist. |
| 12:00–14:30 | Refresh catalysts and Trade Machine status. Another Options AI shape batch. Live and paper stay separate. |
| 14:30–15:30 | Re-rank on current quotes and remaining horizon. |
| 15:30–16:00 | Existing new-entry cutoff. Reconcile. Record latency, fills, and rejects. |

Friday 2026-09-25 reviews workflow and subscription utility. Five paper fills can prove plumbing, not edge. The desk kill date if still unproven is Monday 2026-09-28.

## Falsifiers

Compare sources under the same capital, arrival times, executable-price assumptions, and predeclared exits.

- No incremental economics versus Continual15 after fees, spread, subscriptions, and displaced baseline trades.
- Removing a product leaves choices and net results materially unchanged.
- Paper-only profits disappear when mids are replaced with conservative executable assumptions.
- Most of the move is gone before evaluation.
- Trade Machine results fail forward or cannot be reproduced on the stated timing.
- By 2026-09-25 the workflow still cannot resolve complete candidates.
- One outlier, or a modest fill deterioration, is the whole result.

The near-term bet in the consult is better execution of fresh flow plus better structure selection. More subscriptions earn their place only when realizable net results improve. That improvement is not claimed here.
