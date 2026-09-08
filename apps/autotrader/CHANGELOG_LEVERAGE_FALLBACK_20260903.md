# V1.5.3 adaptive leverage fallback

- Keeps 10x as the configured leverage target.
- Reads `minLeverage`, `maxLeverage` and `leverageStep` from Bybit instrument metadata before every entry.
- Uses the highest valid leverage at or below 10x when 10x is unavailable instead of rejecting the signal.
- Uses the selected leverage consistently for the minimum-margin notional floor, available-margin cap, recorded trade leverage, displayed margin and Smart Margin fallback calculations.
- Sends the selected value to Bybit before opening and records a `LEVERAGE_FALLBACK_SELECTED` audit event when fallback was needed.
- Missing or invalid Bybit leverage metadata still fails closed without opening a position.
- Existing positions are not modified by this change.
- `ALL_EXECUTE`, the 20-position limit, risk logic, entry/SL/TP levels, TP1 breakeven, TP2-to-TP1 protection, SMART SHADOW and all credentials remain unchanged.
