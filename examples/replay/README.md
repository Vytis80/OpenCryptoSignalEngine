# Synthetic replay example

This directory contains a small deterministic example for the shared backtesting package.

- `synthetic_candles.csv` contains invented OHLCV data only.
- `run_replay.py` loads the fixture, replays one fixed LONG setup and prints fills plus an R-based summary.

No production candles, private trade history, account identifiers, credentials, Discord data, or deployment details are included.

From the repository root:

```bash
pip install -e ".[dev]"
python examples/replay/run_replay.py
```

See `docs/backtesting.md` for assumptions and limitations.
