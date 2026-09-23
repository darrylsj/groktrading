# Tradier paper one-lots

Sandbox only: `https://sandbox.tradier.com/v1`.

Set `TRADIER_PAPER_ACCOUNT_ID` and `TRADIER_PAPER_ACCESS_TOKEN` in the host
environment. Public docs use `YOUR_SANDBOX_ACCOUNT_ID`. Do not commit tokens
or account numbers. `api.tradier.com` is refused.

`paper_lift.py` plans ranked Trade Machine **Active** ideas. It does not POST
unless `--submit` is passed. Near Active rows are watch-only. Options AI is
skipped until `--allow-oai` and the DOM card already has max risk, max gain,
and PoP. Buy-to-open puts on IWM, SPY, and QQQ are refused.

This path is not `live_order_gate` and is not Continual15.
