# V2.5 Market History V0 — SHADOW prototype

Status: **research prototype only; not a LIVE trading gate**.

This 2026-09-14 V2.5 experiment tested whether similar same-symbol market patterns tend to repeat using actual Bybit historical 5-minute candles rather than only previous scanner-signal outcomes.

## Design

The prototype was designed to run only for already-confirmed `EXECUTE` signals and only after the signal had been persisted and queued to the Demo AutoTrader bridge. It cannot change scanner status, Entry, SL, TP or the bridge payload.

The planned flow:

- download up to 14 days of same-symbol closed 5m candles through Bybit V5 kline pagination;
- use the signal `trigger_candle_ts` as the current-pattern cutoff;
- compare the latest 24 closed 5m candles (~2 hours) with older same-symbol windows;
- require every historical match to have its complete 36-bar (~3 hour) forward window before the current trigger, preventing future leakage;
- enforce spacing between historical matches so one move is not counted repeatedly;
- replay current stop geometry in ATR units with the same research management assumption used elsewhere: TP1 → breakeven, TP2 → TP1, TP3 → +3R;
- persist prototype results in a local `market_history_checks` table;
- expose research inspection commands `/bybit_history_last` and `/bybit_history_stats`.

## Prototype defaults

- lookback: 14 days
- pattern window: 24 × 5m bars
- forward outcome window: 36 × 5m bars
- minimum independent matches: 30
- maximum matches: 80
- minimum similarity: 0.72
- candidate stride: 3 bars
- match separation: 12 bars
- history cache TTL: 6 hours

The design used `MARKET_HISTORY_*` configuration variables with built-in defaults.

## Safety boundary

Historical analysis must remain a background SHADOW task spawned only after the deterministic execution path. It must never become an implicit veto merely because a pattern match is weak or unavailable.

The prototype installer was designed for a fresh V2.5 TEST copy first, with source-hash verification, backup, compile/tests and rollback on failure, and without automatically restarting the service.

## Relationship to later validation

This prototype is documented for research provenance. It does **not** override the later walk-forward finding recorded in [`../research-status-2026-09-14.md`](../research-status-2026-09-14.md): raw historical-shape gating was not promoted to LIVE because the tested historical score did not demonstrate useful out-of-sample separation.

No runtime historical cache, SQLite rows or deployment-specific data belongs in the public repository.
