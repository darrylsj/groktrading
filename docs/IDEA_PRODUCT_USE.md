# Options AI and Trade Machine — vendor-intended use

**Written:** 2026-09-21 PT. Desk locks below are operator rules, not vendor guarantees.
This is not a profitability claim.

Public sources:

- [Options AI Ways to Trade](https://support.optionsai.com/options-ai-support/how-options-ai-works/bullish-bearish-or-neutral)
- [Trade Scanner](https://support.optionsai.com/options-ai-support/how-options-ai-works/trade-scanner)
- [Comparing Trade Strategies](https://support.optionsai.com/options-ai-support/how-options-ai-works/set-a-target)
- [Expected Move](https://support.optionsai.com/options-ai-support/how-options-ai-works/expected-move)
- [Probability of Profit](https://support.optionsai.com/options-ai-support/how-options-ai-works/probability-of-profit)
- [Paper Trading](https://support.optionsai.com/options-ai-support/about-us/paper-trading)
- [support.optionsai.com llms.txt](https://support.optionsai.com/llms.txt)
- [Trade Machine how it works](https://live.trademachine.com/)
- [Today Tab 2.0](https://learn.trademachine.com/docs/today-tab-2-0)
- [Getting Started with Today](https://learn.trademachine.com/docs/getting-started-today-tab)
- [Navigating ProScan](https://learn.trademachine.com/docs/navigating-the-proscan-tab)
- [Building Your Alerts Portfolio](https://learn.trademachine.com/docs/building-your-alerts-portfolio)

Related: [underuse gap](UNDERUSE_GAP_20260921.md),
[Funnel B](IDEA_FUNNEL_B.md),
[$25k stack consult](STACK_25K_YOLO_CONSULT_20260921.md).

Paying for the product and only shadow-ranking scraped cards is underuse.
Scrape is necessary and not sufficient.

## Desk locks

- Options AI Fast Trade / Scanner → **Compare**. A usable card shows strategy,
  strikes, expiry, **max risk**, **max gain**, and **PoP**, at mid, with no
  commissions. Capture those fields when the DOM shows them. Do not invent
  them from chain JSON.
- **Expected Move is 92.5% of the ATM straddle** for that expiry. It is a
  market-implied move, **not** a 92.5% probability.
- DOM Compare / QuickStrike / Strategy Builder is the idea. Chain XHR
  (`expire-strikes`, `chain-details`, quotes) is quotes-only.
- Options AI in-app paper (virtual balance, mid fills, Followed Trades) is
  **not** Tradier paper.
- Never auto broker-connect Options AI to the live production account.
- Trade Machine: trade only **Active**. **Near Active** is watch. Show Options
  / OCC is the contract. Empty Near Active legs are expected. Do not invent legs.
- Alerts and ProScan are part of the product and are unused on this desk.
- Trade Machine ideas go to Tradier **paper** (`https://sandbox.tradier.com/v1`,
  host env `TRADIER_PAPER_ACCOUNT_ID` / public placeholder
  `YOUR_SANDBOX_ACCOUNT_ID`) until OCC resolves. Default is dry-run.
- Continual15 live stays on Helsinki behind `live_order_gate`.
- Trial prove/kill: Friday 2026-09-25 end of day PT. Hard cancel Monday
  2026-09-28 if unproven. The paid window recorded on the desk runs longer
  than that kill date; the kill date is the desk lock.

## Options AI

Options AI is a visual platform built around Expected Move and defined-risk
spreads. Intended paths from the support docs:

1. **Fast Trade / QuickStrike** — symbol, bullish/bearish/neutral view, and
   horizon. Initial strikes map to Expected Move.
2. **Chart Trade** — support, resistance, range, or target zones become
   credit/debit spreads or iron condors.
3. **Trade Scanner** — up to five symbols, a strategy, duration, and strike
   logic, then Compare.
4. **Custom Trade** — when the structure is already known.

Compare cards are the “good idea” surface: strategy, strikes, expiry, max
risk, max gain, and probability of profit. PoP is interpolated delta at
breakeven. It is the chance of **any** profit by expiry, not the chance of
max gain, and the docs call it informational. Metrics are at the mid and
exclude commissions.

In-app paper starts at a virtual $10,000 and fills limits at mid. Off-hours
or edited entries become Followed Trades and do not update that balance.
Live execution is a separate Tradier connect on the Options AI account page.
This desk does not automate that connect.

Using Options AI well means: form a view, generate a few defined-risk
alternatives, rank the Compare card, then paper in-app or send a resolved
structure to Tradier sandbox. Chain quotes are not that workflow.

## Trade Machine

Trade Machine sells daily option ideas plus a backtester, templates, alerts,
and community. The member loop on the marketing site is: the product finds
the trade; you place it at your broker.

1. **Watch and wait.** Status moves Inactive → Near Active → Active. No trade
   until the criteria are met.
2. **Active** is the only state to trade. The UI can show Show Options:
   ticker, strategy, strike, expiration, and entry, plus a chain to copy.
3. **Near Active** means the trigger is close (Today 2.0 docs: within $4 of
   the stock). It does not show the exact-options button. Empty legs are
   expected. Do not paper them.
4. Today populates with ideas; the public FAQ points at morning population
   and scans at least every 30 minutes in market hours. Recheck Active before
   acting, because a row can remain after conditions change.
5. **Alerts** (email/SMS when a name flips Active) and **ProScan** (strategy
   filters, win rate, alert column) are how members avoid staring at Today.
   Both are unused here.

Show Options / OCC availability can depend on subscription tier. Do not
invent a contract when the payload is absent.

Using Trade Machine well means: after the morning board, take Active only,
open Show Options, copy the structure, verify it on the broker chain, and
place a sized order in **your** account. On this desk that account is the
Tradier sandbox until OCC resolution and paper fills exist.

## What to rank

1. Trade Machine **Active** with full legs and an entry the board actually
   showed.
2. The same, when the card’s own sample size is not tiny.
3. Options AI Compare cards that already show max risk, max gain, and PoP.
4. Options AI debit spreads only with an explicit view. Expected Move is a
   strike gut-check, not a probability.
5. Near Active, Scanner category lists, and chain JSON: watch only.
6. No legs, no OCC, or no Compare metrics: shadow note only. Never paper.

Standing refuse: buy-to-open puts on IWM, SPY, and QQQ, including inside
spreads that the live gate already rejects.

## Scrape versus use

| Feature | Vendor intent | Desk use |
| --- | --- | --- |
| TM Today | Idea board after the morning populate | Explicit redacted HAR, latest HTTP 200 |
| TM Active only | Trade when Active | Paper gate requires Active |
| TM Show Options | Copy the exact trade | Legs from `attach_live_option_quotes` only |
| TM alerts / ProScan | Notice Active flips; build a scan | Unused |
| OAI Fast Trade / Scanner | View → Compare | DOM board only |
| OAI max risk / max gain / PoP | What the card is | Copy when DOM shows them; else null |
| OAI Expected Move | 92.5% ATM straddle | Not a probability; not an idea card |
| OAI chain XHR | Quotes | Never mapped into ideas |
| OAI in-app paper | Mid-fill simulation | Not Tradier paper |
| OAI broker connect | Optional live exec | Never automated onto the live account |
