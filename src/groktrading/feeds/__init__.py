"""External feed adapters. All clients are injectable and fail closed on timeout/stale.

P1/P2 sensor-farm helpers (package only; not auto-deployed to live Helsinki):
flow-alerts poller, tide/net-prem state, Tradier quote interest, screener
snapshot, shadow marks, UW_WS probe stub. Finnhub watch widen lives in
``feeds.finnhub``. Live ``ws_tape.py`` stays host-owned.
"""
