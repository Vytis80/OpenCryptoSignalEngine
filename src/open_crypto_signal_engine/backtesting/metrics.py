"""Aggregate deterministic replay results into auditable R-based statistics."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .models import ReplayResult, ReplayStatus


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    total_setups: int
    entered: int
    not_entered: int
    wins: int
    losses: int
    breakeven: int
    win_rate_pct: float
    total_gross_r: float
    total_net_r: float
    average_net_r: float
    profit_factor: float
    max_drawdown_r: float
    max_favorable_excursion_r: float
    max_adverse_excursion_r: float


def equity_curve_r(results: Iterable[ReplayResult]) -> tuple[float, ...]:
    """Return cumulative net R ordered by close time and signal id."""

    entered = [result for result in results if result.status is ReplayStatus.CLOSED]
    entered.sort(key=lambda result: (result.close_time_ms or 0, result.signal_id))
    equity = 0.0
    curve = [0.0]
    for result in entered:
        equity += result.net_r
        curve.append(equity)
    return tuple(curve)


def max_drawdown_r(curve: Iterable[float]) -> float:
    """Return the largest peak-to-trough decline in R units."""

    values = tuple(curve)
    if not values:
        return 0.0
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
    return drawdown


def summarize_results(results: Iterable[ReplayResult]) -> PerformanceSummary:
    rows = tuple(results)
    entered = tuple(row for row in rows if row.status is ReplayStatus.CLOSED)
    not_entered = len(rows) - len(entered)
    wins = sum(row.net_r > 1e-12 for row in entered)
    losses = sum(row.net_r < -1e-12 for row in entered)
    breakeven = len(entered) - wins - losses
    total_gross_r = sum(row.gross_r for row in entered)
    total_net_r = sum(row.net_r for row in entered)
    positive = sum(row.net_r for row in entered if row.net_r > 0)
    negative = -sum(row.net_r for row in entered if row.net_r < 0)

    if negative > 0:
        profit_factor = positive / negative
    elif positive > 0:
        profit_factor = math.inf
    else:
        profit_factor = 0.0

    return PerformanceSummary(
        total_setups=len(rows),
        entered=len(entered),
        not_entered=not_entered,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate_pct=(wins / len(entered) * 100) if entered else 0.0,
        total_gross_r=total_gross_r,
        total_net_r=total_net_r,
        average_net_r=(total_net_r / len(entered)) if entered else 0.0,
        profit_factor=profit_factor,
        max_drawdown_r=max_drawdown_r(equity_curve_r(entered)),
        max_favorable_excursion_r=max(
            (row.max_favorable_r for row in entered),
            default=0.0,
        ),
        max_adverse_excursion_r=max(
            (row.max_adverse_r for row in entered),
            default=0.0,
        ),
    )


def summarize_by_setup(results: Iterable[ReplayResult]) -> dict[str, PerformanceSummary]:
    """Aggregate results independently for every setup label."""

    groups: dict[str, list[ReplayResult]] = defaultdict(list)
    for result in results:
        groups[result.setup_type].append(result)
    return {
        setup_type: summarize_results(groups[setup_type])
        for setup_type in sorted(groups)
    }
