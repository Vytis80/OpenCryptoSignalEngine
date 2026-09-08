# Deterministic backtesting and signal replay

The shared backtesting package replays already-generated trade setups against normalized OHLCV candles without exchange, network, account, or Discord dependencies.

## Goals

- deterministic historical replay with no hidden network calls
- normalized Unix timestamps in milliseconds
- explicit LONG/SHORT trade-level validation
- configurable fees and slippage
- explicit intrabar collision policy when one candle touches both protection and profit levels
- the same TP1 → breakeven and TP2 → TP1 protection lifecycle used by the shared risk module
- R-based trade outcomes, MFE/MAE, profit factor and maximum drawdown
- reproducible per-setup and aggregate statistics

## Important assumptions

Replay operates on candle ranges, not tick-by-tick data. When a candle contains both a stop and a target there is no way to infer the true order from OHLC alone. Callers therefore select an `IntrabarPolicy` explicitly. `ADVERSE_FIRST` is the conservative default; `TARGET_FIRST` is available for sensitivity analysis.

Entry is considered filled on the first eligible candle whose low/high range touches the requested entry price. Every entered setup is closed deterministically by stop, TP3, or the final candle close (`END_OF_DATA`).

Fees are charged on entry and every exit fraction. Slippage is applied against the trader on both entry and exit fills.

## Synthetic example

The repository includes `examples/replay/synthetic_candles.csv` and `examples/replay/run_replay.py`. The fixture is synthetic and contains no account data, exchange credentials, private trade history, or production market logs.

Run it from the repository root after installing the project:

```bash
python examples/replay/run_replay.py
```

The example intentionally uses fixed inputs so repeated runs produce the same fills and R-based summary.

## Scope

This package validates trade-management and replay behavior. It does not claim that candle replay can reproduce exchange matching, liquidation, funding, latency, queue position, partial-order-book execution, or real-world slippage exactly. Production strategy promotion should combine deterministic replay with the scanner's own regression gates and deployment-host preflight checks.
