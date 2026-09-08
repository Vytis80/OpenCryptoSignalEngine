"""Deterministic trade-protection lifecycle independent from exchange execution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class LifecycleStage(StrEnum):
    """Protection stage derived from confirmed trade milestones."""

    INITIAL = "INITIAL"
    BREAKEVEN = "BREAKEVEN"
    TP1_LOCKED = "TP1_LOCKED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class RiskPlan:
    """Immutable price levels required before an entry may be managed."""

    side: str
    entry: float
    initial_stop: float
    tp1: float
    tp2: float
    tp3: float

    def __post_init__(self) -> None:
        side = self.side.upper()
        object.__setattr__(self, "side", side)
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")

        levels = (self.entry, self.initial_stop, self.tp1, self.tp2, self.tp3)
        if not all(math.isfinite(value) and value > 0 for value in levels):
            raise ValueError("all risk-plan prices must be finite and greater than zero")

        if side == "LONG":
            valid = self.initial_stop < self.entry < self.tp1 < self.tp2 < self.tp3
        else:
            valid = self.initial_stop > self.entry > self.tp1 > self.tp2 > self.tp3
        if not valid:
            raise ValueError("risk-plan price ordering is invalid for the selected side")


@dataclass(frozen=True, slots=True)
class LifecycleProgress:
    """Confirmed milestones used by the pure lifecycle evaluator."""

    tp1_hit: bool = False
    tp2_hit: bool = False
    invalidated: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Pure lifecycle output; callers decide how or whether to execute it."""

    stage: LifecycleStage
    desired_stop: float | None
    effective_stop: float
    move_stop: bool
    close_required: bool
    reason: str


def is_stricter_stop(side: str, candidate: float, reference: float) -> bool:
    """Return whether ``candidate`` protects more profit/risk than ``reference``."""

    normalized = side.upper()
    if normalized == "LONG":
        return candidate > reference
    if normalized == "SHORT":
        return candidate < reference
    raise ValueError("side must be LONG or SHORT")


def _strictest_stop(side: str, first: float, second: float) -> float:
    return first if is_stricter_stop(side, first, second) else second


def evaluate_lifecycle(
    plan: RiskPlan,
    progress: LifecycleProgress,
    current_stop: float | None = None,
) -> RiskDecision:
    """Evaluate the stop/close action implied by confirmed milestones.

    Rules are deliberately exchange-agnostic:

    * before TP1, the initial stop is the required protection;
    * after TP1, the desired stop is breakeven (the actual entry);
    * after TP2, the desired stop advances to TP1;
    * an explicit invalidation requests a close and never loosens a stop;
    * a caller-provided stricter stop is always preserved.

    TP2 logically implies that the TP1 protection stage has already been surpassed,
    even if a caller only persisted ``tp2_hit=True`` after recovery.
    """

    if current_stop is not None and (not math.isfinite(current_stop) or current_stop <= 0):
        raise ValueError("current_stop must be finite and greater than zero")

    if progress.invalidated:
        effective = current_stop if current_stop is not None else plan.initial_stop
        return RiskDecision(
            stage=LifecycleStage.INVALIDATED,
            desired_stop=None,
            effective_stop=effective,
            move_stop=False,
            close_required=True,
            reason="explicit invalidation requires position close",
        )

    if progress.tp2_hit:
        stage = LifecycleStage.TP1_LOCKED
        desired = plan.tp1
        reason = "TP2 confirmed: protect remainder at TP1"
    elif progress.tp1_hit:
        stage = LifecycleStage.BREAKEVEN
        desired = plan.entry
        reason = "TP1 confirmed: protect remainder at breakeven"
    else:
        stage = LifecycleStage.INITIAL
        desired = plan.initial_stop
        reason = "initial protective stop required"

    if current_stop is None:
        return RiskDecision(
            stage=stage,
            desired_stop=desired,
            effective_stop=desired,
            move_stop=True,
            close_required=False,
            reason=reason,
        )

    effective = _strictest_stop(plan.side, current_stop, desired)
    move_stop = not math.isclose(effective, current_stop, rel_tol=0.0, abs_tol=1e-12)
    if not move_stop and not math.isclose(current_stop, desired, rel_tol=0.0, abs_tol=1e-12):
        reason = f"{reason}; existing stop is already stricter"

    return RiskDecision(
        stage=stage,
        desired_stop=desired,
        effective_stop=effective,
        move_stop=move_stop,
        close_required=False,
        reason=reason,
    )
