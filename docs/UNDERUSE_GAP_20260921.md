# Underuse gaps — Options AI and Trade Machine

**Updated:** 2026-09-21 PT.
Full use note: [IDEA_PRODUCT_USE.md](IDEA_PRODUCT_USE.md).

We are not taking advantage of these paid idea products. Five gaps:

1. **Trade Machine Active → paper fills.** The vendor says wait for Active,
   then place the exact legs and entry at your broker. The desk shadow-ranks
   and has about **zero** Trade Machine paper fills on the Tradier sandbox
   (`YOUR_SANDBOX_ACCOUNT_ID` at `https://sandbox.tradier.com/v1`). The trial
   prove-it dies without fills.
2. **Scheduled get-ideas pulls.** The dual-path lock exists in
   `tools/idea_board_scrape/get_ideas.py`. The RTH `get-ideas-board-pull`
   routine has not been run, so the morning Today batch and a twice-a-day
   cadence are missing.
3. **Trade Machine OCC is incomplete.** Active detail often still lacks
   resolvable OCC (empty legs or entry, expiry left as a broker label).
   Near Active empty legs are expected. Without same-day OCC resolution,
   the ideas are not tradable.
4. **Options AI Compare metrics are missing** on the captured DOM cards
   (max risk, max gain, PoP). Chain XHR cannot supply them. Ranking without
   those fields is not Fast Trade or Scanner as documented.
5. **Workflows past the scrape are unused:** Trade Machine Active alerts and
   ProScan; Options AI Scanner, Expected Move as a gut-check, and in-app
   Paper versus Followed Trades.

**Not gaps.** These refusals are correct:

- Linking the live production account to Options AI broker-connect from automation.
- Treating Options AI in-app paper as Tradier paper.
- Paper-lifting Trade Machine Near Active before legs exist.
- Inventing legs, prices, Available, AUTHENTICATED, or paper mode from arbitrary JSON.

Prove/kill remains Friday 2026-09-25 end of day PT, with a hard cancel Monday
2026-09-28 if those bars are still unmet. No profitability claim.
