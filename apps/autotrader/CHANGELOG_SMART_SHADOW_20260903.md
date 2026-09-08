# V1.5.1 SMART position SHADOW

- Accepts and persists the scanner's SMART signal metadata.
- Keeps `ALL_EXECUTE` behavior and the 20-position deployment override unchanged.
- Adds a real-time observer based on the actual Bybit Demo average entry and mark price.
- Persists current/max/min/giveback R and an observation-only management action.
- Adds `/demo_smart` and `/demo_smart_stats` read-only Discord views.
- Does not submit, amend, cancel or close an order.
- Does not change sizing, the 1% risk target, leverage, margin, Entry, SL, TP, TP1-to-breakeven or the monotonic SL guard.
- Does not include or replace `.env`, bridge-secret, API-key or Discord-token files.
