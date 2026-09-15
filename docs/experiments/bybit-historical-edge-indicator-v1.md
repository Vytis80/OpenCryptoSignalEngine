# Bybit Historical Edge Indicator V1

Status: **standalone research prototype; not integrated into LIVE execution**.

This 2026-09-14 prototype was designed as a statistical indicator/research engine for Bybit USDT perpetual markets. It compares the current market state with historically similar states and estimates direction probability, expected move, favorable/adverse excursion and TP/SL probabilities.

## Inputs and modelling

V1 uses public market data only and does not require an API key or place orders.

Research inputs include:

- Bybit public kline history: 15m primary timeframe with 1H and 4H context;
- BTC context for non-BTC symbols;
- Open Interest;
- long/short account ratio;
- funding-rate history;
- price-action features including returns, candle body/wicks, ATR, RSI, EMA structure/slope, volume anomaly, volatility and breakout/sweep features.

The prototype uses K-nearest historical analogues with robust feature scaling, distance weighting, recency weighting and an embargo between the current sample and historical training data to reduce look-ahead leakage.

## Research outputs

The prototype can emit:

- `direction`: LONG / SHORT / WAIT;
- `edge_score`;
- `confidence_pct`;
- `p_up_pct`;
- number of historical matches;
- `expected_move_pct`;
- expected favorable/adverse excursion;
- TP and SL probability estimates;
- market regime.

The default outcome-label horizon is four 15-minute bars (one hour).

`edge_score` is a combined historical directional/expectancy research score, not a guaranteed win probability. `confidence_pct` is a sample/distance-quality heuristic, not a calibrated probability.

## Validation boundary

The prototype includes a walk-forward backtest concept and deliberately excludes an unfinished current candle from the feature dataset. Historical similarity must not be trusted from in-sample results alone.

Any future use as a scanner or AutoTrader gate requires strict out-of-sample validation first. Candidate future work included a top-liquid-universe scanner, regime-specific matchers, calibrated probabilities, separate LONG/SHORT outcome models and historically derived TP/SL distributions.

## Project status

This prototype is recorded for project history because it was built during the same research cycle, but it is **not** evidence that a historical-data gate was promoted into Scanner V2.5, Scanner V2.6 or the Demo AutoTrader.

The separate Historical Pattern V1 validation recorded in [`../research-status-2026-09-14.md`](../research-status-2026-09-14.md) failed promotion. New historical-context designs must therefore start as separately versioned SHADOW experiments rather than silently entering deterministic execution logic.
