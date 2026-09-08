import pytest

from open_crypto_signal_engine.risk import (
    LifecycleProgress,
    LifecycleStage,
    RiskPlan,
    evaluate_lifecycle,
    is_stricter_stop,
)


def long_plan() -> RiskPlan:
    return RiskPlan(
        side="LONG",
        entry=100.0,
        initial_stop=95.0,
        tp1=105.0,
        tp2=110.0,
        tp3=115.0,
    )


def short_plan() -> RiskPlan:
    return RiskPlan(
        side="SHORT",
        entry=100.0,
        initial_stop=105.0,
        tp1=95.0,
        tp2=90.0,
        tp3=85.0,
    )


@pytest.mark.parametrize(
    ("plan", "progress", "stage", "expected_stop"),
    [
        (long_plan(), LifecycleProgress(), LifecycleStage.INITIAL, 95.0),
        (long_plan(), LifecycleProgress(tp1_hit=True), LifecycleStage.BREAKEVEN, 100.0),
        (long_plan(), LifecycleProgress(tp2_hit=True), LifecycleStage.TP1_LOCKED, 105.0),
        (short_plan(), LifecycleProgress(), LifecycleStage.INITIAL, 105.0),
        (short_plan(), LifecycleProgress(tp1_hit=True), LifecycleStage.BREAKEVEN, 100.0),
        (short_plan(), LifecycleProgress(tp2_hit=True), LifecycleStage.TP1_LOCKED, 95.0),
    ],
)
def test_lifecycle_targets_are_deterministic(
    plan: RiskPlan,
    progress: LifecycleProgress,
    stage: LifecycleStage,
    expected_stop: float,
) -> None:
    decision = evaluate_lifecycle(plan, progress)

    assert decision.stage is stage
    assert decision.desired_stop == expected_stop
    assert decision.effective_stop == expected_stop
    assert decision.move_stop is True
    assert decision.close_required is False


@pytest.mark.parametrize(
    ("plan", "progress", "current_stop", "expected_stop"),
    [
        (long_plan(), LifecycleProgress(tp1_hit=True), 102.0, 102.0),
        (long_plan(), LifecycleProgress(tp2_hit=True), 107.0, 107.0),
        (short_plan(), LifecycleProgress(tp1_hit=True), 98.0, 98.0),
        (short_plan(), LifecycleProgress(tp2_hit=True), 93.0, 93.0),
    ],
)
def test_existing_stricter_stop_is_never_loosened(
    plan: RiskPlan,
    progress: LifecycleProgress,
    current_stop: float,
    expected_stop: float,
) -> None:
    decision = evaluate_lifecycle(plan, progress, current_stop=current_stop)

    assert decision.effective_stop == expected_stop
    assert decision.move_stop is False
    assert "already stricter" in decision.reason


@pytest.mark.parametrize(
    ("plan", "current_stop", "expected_stop"),
    [
        (long_plan(), 96.0, 100.0),
        (short_plan(), 104.0, 100.0),
    ],
)
def test_tp1_moves_stop_to_breakeven_when_needed(
    plan: RiskPlan,
    current_stop: float,
    expected_stop: float,
) -> None:
    decision = evaluate_lifecycle(
        plan,
        LifecycleProgress(tp1_hit=True),
        current_stop=current_stop,
    )

    assert decision.stage is LifecycleStage.BREAKEVEN
    assert decision.effective_stop == expected_stop
    assert decision.move_stop is True


@pytest.mark.parametrize(
    ("plan", "current_stop", "expected_stop"),
    [
        (long_plan(), 100.0, 105.0),
        (short_plan(), 100.0, 95.0),
    ],
)
def test_tp2_moves_stop_to_tp1_when_needed(
    plan: RiskPlan,
    current_stop: float,
    expected_stop: float,
) -> None:
    decision = evaluate_lifecycle(
        plan,
        LifecycleProgress(tp1_hit=True, tp2_hit=True),
        current_stop=current_stop,
    )

    assert decision.stage is LifecycleStage.TP1_LOCKED
    assert decision.effective_stop == expected_stop
    assert decision.move_stop is True


def test_invalidation_supersedes_profit_milestones() -> None:
    decision = evaluate_lifecycle(
        long_plan(),
        LifecycleProgress(tp1_hit=True, tp2_hit=True, invalidated=True),
        current_stop=106.0,
    )

    assert decision.stage is LifecycleStage.INVALIDATED
    assert decision.close_required is True
    assert decision.move_stop is False
    assert decision.desired_stop is None
    assert decision.effective_stop == 106.0


@pytest.mark.parametrize(
    "plan",
    [
        lambda: RiskPlan("LONG", 100.0, 101.0, 105.0, 110.0, 115.0),
        lambda: RiskPlan("SHORT", 100.0, 99.0, 95.0, 90.0, 85.0),
        lambda: RiskPlan("SIDEWAYS", 100.0, 95.0, 105.0, 110.0, 115.0),
    ],
)
def test_invalid_risk_plans_fail_closed(plan) -> None:
    with pytest.raises(ValueError):
        plan()


def test_stop_strictness_is_side_aware() -> None:
    assert is_stricter_stop("LONG", 101.0, 100.0)
    assert not is_stricter_stop("LONG", 99.0, 100.0)
    assert is_stricter_stop("SHORT", 99.0, 100.0)
    assert not is_stricter_stop("SHORT", 101.0, 100.0)
