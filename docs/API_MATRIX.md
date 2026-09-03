# API matrix

Plan entitlements vary. Absence of data is a fail-closed event, not a reason to guess.

## Finnhub

| Capability | Role here | Notes |
| --- | --- | --- |
| REST quote | Underlying last/quote probe | Documented REST family: `https://finnhub.io/api/v1` quote endpoint |
| REST news | Context for assembled facts | Entitlement varies by plan |
| REST earnings | Context | Entitlement varies |
| REST fundamentals | Context | Entitlement varies |
| REST sentiment | Context where entitled | Entitlement varies |
| WebSocket `wss://ws.finnhub.io` | **Stock trades / last prints** | Token as query param; never log unredacted URLs |
| Option NBBO | **Not provided** | Do not treat Finnhub ticks as option bid/ask |

Helsinki observation (not claimed as this repo): Finnhub WS SPY/QQQ ticks and REST SPY quote HTTP 200 were validated on the operator host. See `OBSERVED_DEPLOYMENT.md`.

Official docs: https://finnhub.io/docs/api

## Unusual Whales

Live options flow / option-trades and ask-side, premium, volume, and open-interest fields as published by UW.

| Item | Value |
| --- | --- |
| Default base URL (configurable) | `https://api.unusualwhales.com` |
| Docs home | https://api.unusualwhales.com/ |
| Agent/endpoint skill | https://unusualwhales.com/skill.md |

This package uses a **generic GET** of a caller-supplied path. Do **not** add unofficial aliases. Documented examples from UW (for operators to pass in) include `/api/option-trades` — confirm against current official docs before use.

## Tradier

Official endpoint overview: https://docs.tradier.com/docs/endpoints  
Market data: https://docs.tradier.com/docs/market-data  
FAQ (delayed stream): https://docs.tradier.com/docs/faq  
Account event WS: https://docs.tradier.com/reference/websocket-account-data-streaming  
Trading / preview: https://docs.tradier.com/docs/trading

| Environment | REST | Market stream | Account events WS |
| --- | --- | --- | --- |
| Production | `https://api.tradier.com/v1/` | `https://stream.tradier.com/v1/` | `wss://ws.tradier.com` |
| Sandbox | `https://sandbox.tradier.com/v1/` | **No delayed market-data stream** | `wss://sandbox-ws.tradier.com` |

Used product surfaces (official):

- Quotes (`/markets/quotes`)
- Option chains (`/markets/options/chains` — confirm params in current docs)
- Balances, positions, orders
- Order **preview** (`preview=true` on create-order)
- Market clock (`/markets/clock`)
- Account events (session + WS)

Sandbox limitations (official docs / FAQ):

- About **15-minute delayed** market data
- **No** market-data stream
- **No** Greeks
- **No** indices
- **No** tick timesales
- Account-event streaming **is** available

**Production NBBO is pricing truth.**

## Grok / xAI

Thesis and approve/skip only. No broker API. No invented market data.
