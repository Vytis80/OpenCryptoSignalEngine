# V1.5.2 TP2-to-TP1 protection

- After the exact planned TP2 order-link quantity is cumulatively filled, the remaining full-position stop is moved to TP1.
- A partial TP2 execution does not mark TP2 complete and does not move the stop.
- The stop update is checked against the live market, submitted to Bybit Demo and verified from the live position before it is recorded as applied.
- The monotonic guard keeps any exchange-side or DB stop that is already stricter than TP1.
- State, attempts, target, timestamps and the last failure are persisted in SQLite. Transient failures use bounded retry backoff and resume after restart.
- Discord status, active-position and trade views expose the protection state.
- `ALL_EXECUTE`, the 20-position limit, 1% risk target, sizing, leverage, margin logic, scanner/SMART classification and all credentials remain unchanged.
- The feature defaults to enabled. It can be disabled explicitly with `TP2_LOCK_SL_TO_TP1_ENABLED=false`; no `.env` edit is required for the default behavior.
