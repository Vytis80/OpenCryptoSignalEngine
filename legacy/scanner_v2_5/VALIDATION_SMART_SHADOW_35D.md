# V2.5.1 SMART SHADOW — 35-day replay validation

This report is evidence for forward observation, not a promise of profitability and not authority to gate orders.

## Comparable baseline

- Public Bybit 5m OHLC replay, 29 symbols, 35 days.
- Same production `EXECUTE_SCORE=82` baseline.
- Same 30-minute per-symbol signal cooldown and one active simulated trade per symbol.
- Same conservative same-bar rule: stop is evaluated before a target.
- Modelled cost: 0.055% fee plus 0.020% slippage on each fill.

## Result

| Group | Trades | Win rate | Net expectancy | Net profit factor |
|---|---:|---:|---:|---:|
| All EXECUTE | 553 | 41.6% | -0.348R | 0.50 |
| SMART PASS | 137 | 52.6% | +0.080R | 1.16 |
| SMART CAUTION | 74 | 47.3% | -0.095R | 0.84 |
| SMART BLOCK | 385 | 38.4% | -0.490R | 0.36 |

SMART PASS was -0.102R over the earlier 60% sample (23 trades) and +0.116R over the later 40% sample (114 trades). Its bootstrap 95% interval still crossed zero. The four qualifying historical SHORT trades were negative; the sample is too small for a reliable conclusion.

## Decision

The ranking is promising enough for forward collection but not strong enough to change execution. V2.5.1 therefore keeps every final `EXECUTE`, preserves Entry/SL/TP, and records SMART labels only. A future execution gate requires a materially larger, exchange-confirmed forward sample segmented by side, setup, regime and realized fees/slippage.

Historical replay could not reconstruct past 1m micro-momentum, funding or open-interest deltas. Those fields are collected in live forward observations.
