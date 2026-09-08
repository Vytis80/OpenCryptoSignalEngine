from __future__ import annotations

import time
from dataclasses import dataclass, field


MODEL_VERSION = "V1.5.1-SMART-POSITION-SHADOW-1"


def _num(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def _clip(value, low, high):
    return max(low, min(high, value))


@dataclass
class SmartPositionAssessment:
    trade_id: int
    symbol: str
    action: str
    health_score: float
    current_r: float
    max_r: float
    min_r: float
    giveback_r: float
    mark_price: float
    ts: float
    reasons: list[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION


def assess_position(trade: dict, position: dict, previous: dict | None = None):
    """Assess an actual Bybit Demo position without changing it.

    The observer deliberately returns no price amendment or close instruction.
    Existing exchange SL/TP, TP1->BE and monotonic-stop guards remain sovereign.
    """
    entry = _num(position.get("avgPrice")) or _num(trade.get("avg_entry")) or _num(trade.get("entry_signal"))
    mark = _num(position.get("markPrice")) or _num(position.get("lastPrice"))
    sl = _num(trade.get("sl"))
    risk = abs(entry - sl)
    if entry <= 0 or mark <= 0 or risk <= 0:
        raise ValueError("SMART position observer requires valid entry, mark and SL")

    side = str(trade.get("side") or "").upper()
    current_r = (mark - entry) / risk if side == "LONG" else (entry - mark) / risk
    previous_max = _num((previous or {}).get("max_r"), current_r)
    previous_min = _num((previous or {}).get("min_r"), current_r)
    max_r = max(previous_max, current_r)
    min_r = min(previous_min, current_r)
    giveback = max(0.0, max_r - current_r)
    tp1 = bool(trade.get("tp1_hit"))
    tp2 = bool(trade.get("tp2_hit"))
    be_applied = str(trade.get("be_status") or "") in {"APPLIED", "NOT_NEEDED"}
    smart_status = str(trade.get("smart_status") or "NO_DATA").upper()
    age_min = max(0.0, (time.time() - _num(trade.get("opened_at"), time.time())) / 60.0)

    reasons = []
    if current_r <= -0.45:
        reasons.append(f"position adverse {current_r:+.2f}R")
    if max_r >= 0.75 and giveback >= 0.35:
        reasons.append(f"giveback {giveback:.2f}R from {max_r:+.2f}R")
    if tp1 and not be_applied:
        reasons.append("TP1 reached; breakeven protection still pending")
    if smart_status == "SMART_BLOCK":
        reasons.append("scanner SMART_BLOCK counterfactual")
    elif smart_status == "SMART_CAUTION":
        reasons.append("scanner SMART_CAUTION counterfactual")

    health = 68.0 + _clip(current_r * 12.0, -22.0, 20.0)
    health -= _clip(giveback - 0.25, 0.0, 1.5) * 12.0
    if smart_status == "SMART_BLOCK": health -= 8.0
    if smart_status == "SMART_CAUTION": health -= 3.0
    if tp1: health += 6.0
    if tp2: health += 6.0
    health = round(_clip(health, 0.0, 100.0), 2)

    if not tp1 and age_min >= 5 and (
        current_r <= -0.70 or (current_r <= -0.50 and smart_status == "SMART_BLOCK")
    ):
        action = "EXIT_CANDIDATE"
    elif tp2 or (max_r >= 1.8 and giveback >= 0.25):
        action = "TRAIL_CANDIDATE"
    elif tp1 or (max_r >= 0.95 and giveback >= 0.30):
        action = "PROTECT_CANDIDATE"
    elif current_r <= -0.35 or giveback >= 0.45 or smart_status == "SMART_BLOCK":
        action = "WEAKENING"
    else:
        action = "HOLD"

    if not reasons:
        reasons.append(f"actual Demo position intact at {current_r:+.2f}R")
    return SmartPositionAssessment(
        int(trade["id"]), str(trade["symbol"]), action, health, current_r,
        max_r, min_r, giveback, mark, time.time(), reasons,
    )
