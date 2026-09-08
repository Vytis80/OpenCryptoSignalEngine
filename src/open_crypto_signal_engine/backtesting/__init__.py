"""Deterministic historical replay and R-based performance analysis."""

from .metrics import (
    PerformanceSummary,
    equity_curve_r,
    max_drawdown_r,
    summarize_by_setup,
    summarize_results,
)
from .models import (
    Candle,
    CloseReason,
    CostModel,
    IntrabarPolicy,
    ReplayFill,
    ReplayResult,
    ReplayStatus,
    Side,
    TradeSetup,
    candle_from_row,
    normalize_candles,
    normalize_timestamp_ms,
)
from .replay import replay_setup, replay_setups

__all__ = [
    "Candle",
    "CloseReason",
    "CostModel",
    "IntrabarPolicy",
    "PerformanceSummary",
    "ReplayFill",
    "ReplayResult",
    "ReplayStatus",
    "Side",
    "TradeSetup",
    "candle_from_row",
    "equity_curve_r",
    "max_drawdown_r",
    "normalize_candles",
    "normalize_timestamp_ms",
    "replay_setup",
    "replay_setups",
    "summarize_by_setup",
    "summarize_results",
]
