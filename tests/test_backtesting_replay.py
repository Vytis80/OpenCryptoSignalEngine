import math

import pytest

from open_crypto_signal_engine.backtesting import (
    Candle,
    CloseReason,
    CostModel,
    IntrabarPolicy,
    ReplayStatus,
    TradeSetup,
    equity_curve_r,
    max_drawdown_r,
    normalize_candles,
    normalize_timestamp_ms,
    replay_setup,
    replay_setups,
    summarize_by_setup,
    summarize_results,
)


def long_setup(**overrides) -> TradeSetup:
    values = {
        "signal_id": "L1",
        "setup_type": "BREAKOUT",
        "side": "LONG",
        "eligible_from_ms": 1_000,
        "entry": 100.0,
        "stop": 95.0,
        "tp1": 105.0,
        "tp2": 110.0,
        "tp3": 115.0,
    }
    values.update(overrides)
    return TradeSetup(**values)


def short_setup(**overrides) -> TradeSetup:
    values = {
        "signal_id": "S1",
        "setup_type": "REJECTION",
        "side": "SHORT",
        "eligible_from_ms": 1_000,
        "entry": 100.0,
        "stop": 105.0,
        "tp1": 95.0,
        "tp2": 90.0,
        "tp3": 85.0,
    }
    values.update(overrides)
    return TradeSetup(**values)


def test_timestamp_and_candle_normalization_is_stable() -> None:
    assert normalize_timestamp_ms(1_700_000_000, "auto") == 1_700_000_000_000
    assert normalize_timestamp_ms(1_700_000_000_000, "auto") == 1_700_000_000_000

    rows = [
        [1_700_000_060, 101, 103, 100, 102, 12],
        {
            "timestamp": 1_700_000_000,
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "volume": 10,
        },
    ]
    candles = normalize_candles(rows, timestamp_unit="s")

    assert [candle.timestamp_ms for candle in candles] == [
        1_700_000_000_000,
        1_700_000_060_000,
    ]
    assert candles[0].close == 101


def test_duplicate_timestamps_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        normalize_candles(
            [
                Candle(1_000, 100, 101, 99, 100),
                Candle(1_000, 100, 102, 98, 101),
            ]
        )


def test_long_tp1_then_tp2_advances_stop_monotonically() -> None:
    candles = (
        Candle(1_000, 100, 104, 99, 103),
        Candle(2_000, 103, 106, 102, 105),
        Candle(3_000, 105, 111, 104, 110),
    )

    result = replay_setup(candles, long_setup())

    assert result.close_reason is CloseReason.STOP
    assert result.tp1_hit is True
    assert result.tp2_hit is True
    assert result.tp3_hit is False
    assert result.gross_r == pytest.approx(4 / 3)
    assert [fill.kind for fill in result.fills] == ["ENTRY", "TP1", "TP2", "STOP"]
    assert result.fills[-1].level_price == 105.0


def test_short_lifecycle_is_symmetric() -> None:
    candles = (
        Candle(1_000, 100, 101, 96, 97),
        Candle(2_000, 97, 98, 94, 95),
        Candle(3_000, 95, 96, 89, 90),
    )

    result = replay_setup(candles, short_setup())

    assert result.close_reason is CloseReason.STOP
    assert result.tp1_hit is True
    assert result.tp2_hit is True
    assert result.gross_r == pytest.approx(4 / 3)
    assert result.fills[-1].level_price == 95.0


def test_same_candle_collision_policy_is_explicit() -> None:
    candles = (
        Candle(1_000, 100, 101, 99, 100),
        Candle(2_000, 100, 111, 94, 105),
    )

    adverse = replay_setup(
        candles,
        long_setup(),
        intrabar_policy=IntrabarPolicy.ADVERSE_FIRST,
    )
    favorable = replay_setup(
        candles,
        long_setup(),
        intrabar_policy=IntrabarPolicy.TARGET_FIRST,
    )

    assert adverse.close_reason is CloseReason.STOP
    assert adverse.gross_r == pytest.approx(-1.0)
    assert adverse.tp1_hit is False
    assert favorable.tp1_hit is True
    assert favorable.tp2_hit is True
    assert favorable.gross_r == pytest.approx(4 / 3)


def test_fees_and_slippage_reduce_net_result() -> None:
    setup = long_setup(stop=90.0, tp1=110.0, tp2=120.0, tp3=130.0)
    candles = (
        Candle(1_000, 100, 101, 99, 100),
        Candle(2_000, 100, 131, 101, 130),
    )

    result = replay_setup(
        candles,
        setup,
        costs=CostModel(fee_bps_per_side=10.0, slippage_bps=10.0),
    )

    assert result.close_reason is CloseReason.TP3
    assert result.gross_r == pytest.approx(2.0)
    assert result.slippage_r > 0
    assert result.fee_r > 0
    assert result.net_r < result.gross_r
    assert result.net_r == pytest.approx(1.956002, abs=1e-6)


def test_end_of_data_closes_remaining_position_deterministically() -> None:
    candles = (
        Candle(1_000, 100, 103, 99, 102),
        Candle(2_000, 102, 104, 101, 103),
    )

    result = replay_setup(candles, long_setup())

    assert result.status is ReplayStatus.CLOSED
    assert result.close_reason is CloseReason.END_OF_DATA
    assert result.close_time_ms == 2_000
    assert result.gross_r == pytest.approx(0.6)


def test_replay_order_and_metrics_are_reproducible() -> None:
    win = replay_setup(
        (
            Candle(1_000, 100, 101, 99, 100),
            Candle(2_000, 101, 116, 101, 115),
        ),
        long_setup(signal_id="WIN", setup_type="A"),
    )
    loss = replay_setup(
        (Candle(3_000, 100, 101, 94, 95),),
        long_setup(signal_id="LOSS", setup_type="B", eligible_from_ms=3_000),
    )
    missed = replay_setup(
        (Candle(4_000, 100, 101, 99, 100),),
        long_setup(
            signal_id="MISS",
            setup_type="A",
            eligible_from_ms=4_000,
            entry=200.0,
            stop=190.0,
            tp1=210.0,
            tp2=220.0,
            tp3=230.0,
        ),
    )

    summary = summarize_results((win, loss, missed))
    curve = equity_curve_r((loss, missed, win))

    assert summary.total_setups == 3
    assert summary.entered == 2
    assert summary.not_entered == 1
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.win_rate_pct == pytest.approx(50.0)
    assert summary.total_net_r == pytest.approx(1.0)
    assert summary.average_net_r == pytest.approx(0.5)
    assert summary.profit_factor == pytest.approx(2.0)
    assert curve == pytest.approx((0.0, 2.0, 1.0))
    assert max_drawdown_r(curve) == pytest.approx(1.0)

    by_setup = summarize_by_setup((win, loss, missed))
    assert tuple(by_setup) == ("A", "B")
    assert by_setup["A"].wins == 1
    assert by_setup["B"].losses == 1


def test_multi_setup_replay_has_stable_signal_order() -> None:
    candles = (Candle(1_000, 100, 101, 94, 100),)
    setups = (
        long_setup(signal_id="B"),
        long_setup(signal_id="A"),
    )

    first = replay_setups(candles, setups)
    second = replay_setups(candles, reversed(setups))

    assert [result.signal_id for result in first] == ["A", "B"]
    assert first == second


def test_profit_factor_is_infinite_without_losses() -> None:
    result = replay_setup(
        (
            Candle(1_000, 100, 101, 99, 100),
            Candle(2_000, 101, 116, 101, 115),
        ),
        long_setup(),
    )

    assert math.isinf(summarize_results((result,)).profit_factor)
