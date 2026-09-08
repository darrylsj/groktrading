# Dual-broker plan

Operator will trade on **both Tradier and Schwab**. Phase A introduced a
venue-aware `Broker` protocol and extracted the existing Tradier client behind
`TradierBroker`. **Live Tradier order behavior is unchanged.**

This tree adds **Phase B-prep**: a Schwab OAuth helper so the desk can persist a
refresh token the moment App Key/Secret + **Ready For Use** land. There is still
**no live Schwab order or quote HTTP**.

## Phases

| Phase | Status | What |
| --- | --- | --- |
| A | Protocol + Tradier extract | `venue_id` is `Literal["tradier"]`. Paper/live paths call `Broker`, not ad-hoc Tradier methods. |
| B-prep (this) | OAuth helper stub | `schwab_oauth` documents the login flow, fail-closes without env vars, wraps `schwab-py` only when keys are present. `SchwabBroker` still cannot place orders. |
| B/C | After token + Ready For Use | Implement `SchwabBroker` quote/preview/submit. No Schwab credentials in this repo. |

`src/groktrading/brokers/schwab.py` fails closed without tokens. Construction
raises `SchwabAuthNotReady` and points at the helper, env vars, and the Ready
For Use gate. It does not accept tokens as constructor arguments.

## Schwab OAuth (operator)

1. Create a Schwab developer app: **Trader API**, **Individual** product.
2. Set the callback URL exactly `https://127.0.0.1:8182` (no trailing slash).
3. Wait until status is **Ready For Use**. **Submitted is not enough.**
4. Copy App Key / App Secret into a secret store (never GitHub). Env names are
   in [`.env.example`](../.env.example): `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`,
   optional `SCHWAB_TOKEN_PATH`.
5. Run the helper (dry-run if vars are missing — no browser hang):

   ```bash
   python -m groktrading.brokers.schwab_oauth
   # or: groktrading-schwab-oauth
   # or: python scripts/schwab_oauth_stub.py
   ```

   Login persists a refresh token to `~/.config/groktrading/schwab_token.json`
   (or `SCHWAB_TOKEN_PATH`). That path must stay **outside** the git repo.
6. **Weekly re-auth reminder:** access tokens last ~30 minutes; refresh tokens
   last ~7 days. Re-run the helper when the refresh token expires.

Optional install for the real login/refresh wrap: `pip install 'groktrading[schwab]'`
(or `pip install schwab-py`). The helper is a thin `client_from_login_flow` /
`client_from_token_file` wrapper. It does not scrape the Schwab web UI.

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
4. **WebSocket never places orders.** Auth tokens are not an order path.

## Surfaces

`Broker` covers balances, positions, option quote (gate inputs), preview and
submit of an option order, find-by-tag, and cancel of working **entry** orders
only (no flatten). `OrderMachine` still uses the preview/submit/find subset
(`OrderBroker`). `Executor` can attach `BrokerSink` so paper/live stubs go
through the same venue object. `RecordingBroker` / `RecordingOrderBroker`
remain in-memory test doubles.

Selecting venue `schwab` still cannot preview or submit. Phase D (dual-fire
router) is out of scope here.
