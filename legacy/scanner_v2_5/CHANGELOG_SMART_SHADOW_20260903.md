# V2.5.1 SMART signal and management SHADOW

- Preserves the audited V2.5 confirmed-candle strategy and all final `EXECUTE` delivery.
- Classifies each final signal as `SMART_PASS`, `SMART_CAUTION` or `SMART_BLOCK` for forward research.
- Uses direction separation, regime/setup fit, volume, relative strength, spread, estimated cost/R, funding, open-interest participation and confirmed 1m momentum when available.
- Adds persisted, restart-safe SMART signal and management tables.
- Adds confirmed-1m management observations without modifying active-signal or order instructions.
- Sends SMART metadata through the durable bridge while keeping the event type `EXECUTE`.
- Adds `/bybit_smart_active` and `/bybit_smart_stats` read-only Discord views.
- Does not include or replace any secret file.
