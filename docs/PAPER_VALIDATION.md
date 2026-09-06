# Paper validation

Paper is for **path validation**, not performance claims.

## Method

1. Run `GROKTRADING_MODE=paper` only.
2. Require Tradier **preview** before any sandbox order.
3. Tag every artifact with `signal_id`.
4. Snapshot **production** option NBBO at decision time (pricing truth).
5. Record sandbox fill (if any) as a **delayed artifact**.
6. Persist **same-day terminal** paper artifacts unless a live overnight long is explicitly in force. **12:30 PT is a new-entry cutoff only** on the live card (not a forced flatten). Do not treat sandbox files as live risk.
7. Reconcile with `PaperLedger.reconcile`: `sandbox_fill − production_ask`. That number is a delay/artifact delta, **not P&L**.

## Invalid conclusions

- Do not treat sandbox marks as live marks.
- Do not scale size from paper fills.
- Do not claim a milestone is reached from paper.

## Operator sandbox account

Sandbox and live account identifiers stay in host config, not in this public tree. Public docs use `YOUR_SANDBOX_ACCOUNT_ID` / `ACCOUNT_ID_REDACTED` only. See `OBSERVED_DEPLOYMENT.md`.
