Executor Bot (Render-ready)
--------------------------
- service.py: entry point with /health and /metrics
- lib/bingx.py: API client
- strategies/balanced.py: balanced strategy
- risk/protection.py: protections

Set env vars: BINGX_API_KEY, BINGX_API_SECRET (required). Optional: SYMBOL, INTERVAL, LEVERAGE, TRADE_PORTION, MIN_ATR, COOLDOWN.
