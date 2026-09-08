"""Run a deterministic replay against the repository's synthetic candle fixture."""

from __future__ import annotations

import csv
from pathlib import Path

from open_crypto_signal_engine.backtesting import (
    CostModel,
    TradeSetup,
    candle_from_row,
    replay_setup,
    summarize_results,
)

FIXTURE = Path(__file__).with_name("synthetic_candles.csv")


def main() -> None:
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        candles = tuple(
            candle_from_row(row, timestamp_unit="s") for row in csv.DictReader(handle)
        )

    setup = TradeSetup(
        signal_id="SYNTHETIC-LONG-001",
        setup_type="SYNTHETIC_BREAKOUT",
        side="LONG",
        eligible_from_ms=1_700_000_000_000,
        entry=100.0,
        stop=95.0,
        tp1=105.0,
        tp2=110.0,
        tp3=115.0,
    )
    result = replay_setup(
        candles,
        setup,
        costs=CostModel(fee_bps_per_side=5.5, slippage_bps=2.0),
    )
    summary = summarize_results((result,))

    print(f"signal={result.signal_id} close={result.close_reason} net={result.net_r:.4f}R")
    print("fills=" + ", ".join(fill.kind for fill in result.fills))
    print(
        f"entered={summary.entered} win_rate={summary.win_rate_pct:.1f}% "
        f"max_drawdown={summary.max_drawdown_r:.4f}R"
    )


if __name__ == "__main__":
    main()
