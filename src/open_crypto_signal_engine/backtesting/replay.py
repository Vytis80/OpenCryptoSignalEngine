"""Deterministic candle replay for already-generated trade setups."""

from __future__ import annotations

from collections.abc import Iterable

from open_crypto_signal_engine.risk import LifecycleProgress, RiskPlan, evaluate_lifecycle

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
    normalize_candles,
)


def _touches(candle: Candle, price: float) -> bool:
    return candle.low <= price <= candle.high


def _entry_fill_price(side: Side, price: float, slippage_bps: float) -> float:
    factor = slippage_bps / 10_000
    return price * (1 + factor if side is Side.LONG else 1 - factor)


def _exit_fill_price(side: Side, price: float, slippage_bps: float) -> float:
    factor = slippage_bps / 10_000
    return price * (1 - factor if side is Side.LONG else 1 + factor)


def _pnl_per_unit(side: Side, entry: float, exit_price: float) -> float:
    if side is Side.LONG:
        return exit_price - entry
    return entry - exit_price


def _stop_touched(candle: Candle, side: Side, stop: float) -> bool:
    if side is Side.LONG:
        return candle.low <= stop
    return candle.high >= stop


def _target_touched(candle: Candle, side: Side, target: float) -> bool:
    if side is Side.LONG:
        return candle.high >= target
    return candle.low <= target


def _excursions(candle: Candle, setup: TradeSetup, risk: float) -> tuple[float, float]:
    if setup.side is Side.LONG:
        favorable = max(0.0, (candle.high - setup.entry) / risk)
        adverse = max(0.0, (setup.entry - candle.low) / risk)
    else:
        favorable = max(0.0, (setup.entry - candle.low) / risk)
        adverse = max(0.0, (candle.high - setup.entry) / risk)
    return favorable, adverse


def replay_setup(
    candles: Iterable[Candle],
    setup: TradeSetup,
    *,
    costs: CostModel | None = None,
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.ADVERSE_FIRST,
) -> ReplayResult:
    """Replay one validated setup without network or exchange dependencies.

    The setup is eligible only from ``eligible_from_ms`` onward. Entry occurs on
    the first eligible candle whose range touches the requested entry price.
    Every entered setup is closed deterministically: by stop, TP3, or the last
    available candle close.
    """

    series = normalize_candles(candles)
    model = costs or CostModel()
    policy = IntrabarPolicy(intrabar_policy)
    side = Side(setup.side)
    risk = abs(setup.entry - setup.stop)

    entry_index = None
    for index, candle in enumerate(series):
        if candle.timestamp_ms < setup.eligible_from_ms:
            continue
        if _touches(candle, setup.entry):
            entry_index = index
            break

    if entry_index is None:
        return ReplayResult(
            signal_id=setup.signal_id,
            setup_type=setup.setup_type,
            side=side,
            status=ReplayStatus.NOT_ENTERED,
            close_reason=None,
            entry_time_ms=None,
            close_time_ms=None,
            gross_r=0.0,
            net_r=0.0,
            fee_r=0.0,
            slippage_r=0.0,
            max_favorable_r=0.0,
            max_adverse_r=0.0,
            tp1_hit=False,
            tp2_hit=False,
            tp3_hit=False,
            fills=(),
        )

    entry_candle = series[entry_index]
    entry_fill = _entry_fill_price(side, setup.entry, model.slippage_bps)
    fee_rate = model.fee_bps_per_side / 10_000
    fee_value = entry_fill * fee_rate
    fills: list[ReplayFill] = [
        ReplayFill(entry_candle.timestamp_ms, "ENTRY", setup.entry, entry_fill, 1.0)
    ]

    ideal_pnl = 0.0
    actual_pnl = 0.0
    remaining = 1.0
    tp_hits = [False, False, False]
    max_favorable_r = 0.0
    max_adverse_r = 0.0
    current_stop = setup.stop
    close_reason: CloseReason | None = None
    close_time_ms: int | None = None

    risk_plan = RiskPlan(
        side=side.value,
        entry=setup.entry,
        initial_stop=setup.stop,
        tp1=setup.tp1,
        tp2=setup.tp2,
        tp3=setup.tp3,
    )
    targets = (setup.tp1, setup.tp2, setup.tp3)

    def exit_fraction(timestamp_ms: int, kind: str, level: float, fraction: float) -> None:
        nonlocal actual_pnl, fee_value, ideal_pnl
        fill_price = _exit_fill_price(side, level, model.slippage_bps)
        ideal_pnl += _pnl_per_unit(side, setup.entry, level) * fraction
        actual_pnl += _pnl_per_unit(side, entry_fill, fill_price) * fraction
        fee_value += fill_price * fee_rate * fraction
        fills.append(ReplayFill(timestamp_ms, kind, level, fill_price, fraction))

    for candle in series[entry_index:]:
        favorable, adverse = _excursions(candle, setup, risk)
        max_favorable_r = max(max_favorable_r, favorable)
        max_adverse_r = max(max_adverse_r, adverse)

        if (
            remaining > 1e-12
            and policy is IntrabarPolicy.ADVERSE_FIRST
            and _stop_touched(candle, side, current_stop)
        ):
            exit_fraction(candle.timestamp_ms, "STOP", current_stop, remaining)
            remaining = 0.0
            close_reason = CloseReason.STOP
            close_time_ms = candle.timestamp_ms
            break

        for index, target in enumerate(targets):
            if tp_hits[index] or remaining <= 1e-12:
                continue
            if not _target_touched(candle, side, target):
                continue

            fraction = min(setup.tp_fractions[index], remaining)
            exit_fraction(candle.timestamp_ms, f"TP{index + 1}", target, fraction)
            remaining -= fraction
            tp_hits[index] = True

            if index < 2 and remaining > 1e-12:
                decision = evaluate_lifecycle(
                    risk_plan,
                    LifecycleProgress(tp1_hit=tp_hits[0], tp2_hit=tp_hits[1]),
                    current_stop=current_stop,
                )
                current_stop = decision.effective_stop

        if remaining <= 1e-12:
            close_reason = CloseReason.TP3
            close_time_ms = candle.timestamp_ms
            break

        if _stop_touched(candle, side, current_stop):
            exit_fraction(candle.timestamp_ms, "STOP", current_stop, remaining)
            remaining = 0.0
            close_reason = CloseReason.STOP
            close_time_ms = candle.timestamp_ms
            break

    if remaining > 1e-12:
        last = series[-1]
        exit_fraction(last.timestamp_ms, "END_OF_DATA", last.close, remaining)
        remaining = 0.0
        close_reason = CloseReason.END_OF_DATA
        close_time_ms = last.timestamp_ms

    gross_r = ideal_pnl / risk
    actual_before_fees_r = actual_pnl / risk
    fee_r = fee_value / risk
    net_r = actual_before_fees_r - fee_r
    slippage_r = gross_r - actual_before_fees_r

    return ReplayResult(
        signal_id=setup.signal_id,
        setup_type=setup.setup_type,
        side=side,
        status=ReplayStatus.CLOSED,
        close_reason=close_reason,
        entry_time_ms=entry_candle.timestamp_ms,
        close_time_ms=close_time_ms,
        gross_r=gross_r,
        net_r=net_r,
        fee_r=fee_r,
        slippage_r=slippage_r,
        max_favorable_r=max_favorable_r,
        max_adverse_r=max_adverse_r,
        tp1_hit=tp_hits[0],
        tp2_hit=tp_hits[1],
        tp3_hit=tp_hits[2],
        fills=tuple(fills),
    )


def replay_setups(
    candles: Iterable[Candle],
    setups: Iterable[TradeSetup],
    *,
    costs: CostModel | None = None,
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.ADVERSE_FIRST,
) -> tuple[ReplayResult, ...]:
    """Replay many independent setups in a stable deterministic order."""

    series = normalize_candles(candles)
    ordered = sorted(setups, key=lambda item: (item.eligible_from_ms, item.signal_id))
    return tuple(
        replay_setup(series, setup, costs=costs, intrabar_policy=intrabar_policy)
        for setup in ordered
    )
