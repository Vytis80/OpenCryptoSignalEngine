from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


MODEL_VERSION = "V2.5.1-SMART-SHADOW-2"


def _clip(value, low, high):
    return max(low, min(high, value))


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if b else 0.0


def setup_family(name):
    text = str(name or "").upper()
    if "BREAKOUT" in text or "BREAKDOWN" in text:
        return "BREAKOUT_RETEST"
    if "PULLBACK" in text:
        return "TREND_PULLBACK"
    if "RECLAIM" in text or "REJECT" in text or "EMA" in text:
        return "EMA_REACTION"
    return "OTHER"


@dataclass
class SmartSignalAssessment:
    inst_id: str
    verdict: str
    score: float
    setup_family: str
    regime: str
    confidence_margin: float
    checked_at: float
    reasons: list[str] = field(default_factory=list)
    suggested_entry_low: float = 0.0
    suggested_entry_high: float = 0.0
    suggested_sl: float = 0.0
    features: dict = field(default_factory=dict)
    model_version: str = MODEL_VERSION

    def feature_payload(self):
        return dict(self.features)


@dataclass
class SmartManagementAssessment:
    signal_id: int
    inst_id: str
    action: str
    health_score: float
    current_r: float
    max_r: float
    giveback_r: float
    checked_at: float
    candle_ts: int
    regime: str
    reasons: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    model_version: str = MODEL_VERSION

    def payload(self):
        return asdict(self)


def _micro_view(c1m, side):
    rows = [x for x in c1m if getattr(x, "confirm", True)]
    if len(rows) < 4:
        return 0.0, 0, 0
    last = rows[-3:]
    momentum = _pct(rows[-1].c, rows[-4].c)
    aligned = sum((x.c > x.o) if side == "LONG" else (x.c < x.o) for x in last)
    return momentum, aligned, int(rows[-1].ts)


def _suggested_plan(a, c5):
    atr = max(float(getattr(a, "atr_5m", 0) or 0), 1e-12)
    anchor = float(getattr(a, "trigger_level", 0) or 0)
    if anchor <= 0 or abs(float(a.price) - anchor) > 1.5 * atr:
        anchor = float(a.price)
    if a.side == "LONG":
        low, high = anchor - 0.08 * atr, anchor + 0.12 * atr
    else:
        low, high = anchor - 0.12 * atr, anchor + 0.08 * atr
    confirmed = [x for x in c5 if getattr(x, "confirm", True)]
    recent = confirmed[-7:]
    if not recent:
        return low, high, float(a.sl)
    if a.side == "LONG":
        suggested_sl = min(x.l for x in recent) - 0.20 * atr
    else:
        suggested_sl = max(x.h for x in recent) + 0.20 * atr
    return low, high, suggested_sl


def assess_signal(a, c5, c1m, cfg):
    """Counterfactual SMART label for an existing confirmed EXECUTE.

    This function cannot alter TradeAnalysis and does not return an execution
    instruction. Its only output is an auditable observation.
    """
    family = setup_family(getattr(a, "trigger_5m", ""))
    regime = str(getattr(a, "market_regime", "TRANSITION") or "TRANSITION")
    margin = float(getattr(a, "direction_margin", 0) or 0)
    score = 50.0
    reasons = []

    margin_points = _clip((margin - 8.0) * 0.7, -10.0, 14.0)
    score += margin_points
    reasons.append(f"direction margin {margin:.0f} ({margin_points:+.1f})")

    aligned_1h = (a.side == "LONG" and a.bias_1h == "BULLISH") or (
        a.side == "SHORT" and a.bias_1h == "BEARISH"
    )
    aligned_15m = (a.side == "LONG" and str(a.setup_15m).startswith("BULLISH")) or (
        a.side == "SHORT" and str(a.setup_15m).startswith("BEARISH")
    )
    score += 8.0 if aligned_1h else -14.0
    score += 7.0 if aligned_15m else -10.0
    reasons.append("1H aligned" if aligned_1h else "1H not aligned")
    reasons.append("15M aligned" if aligned_15m else "15M not aligned")

    compatibility = 0.0
    if family == "BREAKOUT_RETEST":
        compatibility = 10.0 if regime in {"TREND", "VOLATILITY_EXPANSION"} else -10.0 if regime == "RANGE" else 1.0
    elif family == "TREND_PULLBACK":
        compatibility = 10.0 if regime == "TREND" else -7.0 if regime in {"RANGE", "VOLATILITY_EXPANSION"} else 2.0
    elif family == "EMA_REACTION":
        compatibility = 7.0 if regime in {"TREND", "TRANSITION"} else -5.0
    else:
        compatibility = -5.0
    score += compatibility
    reasons.append(f"{family} in {regime} ({compatibility:+.0f})")

    volume = float(getattr(a, "volume_ratio_5m", 0) or 0)
    volume_points = 8.0 if volume >= 1.50 else 4.0 if volume >= 1.15 else -6.0 if volume < 0.85 else 0.0
    score += volume_points
    reasons.append(f"5M volume {volume:.2f}x ({volume_points:+.0f})")

    stop_pct = float(getattr(a, "stop_pct", 0) or 0)
    cost_r = float(getattr(a, "estimated_cost_r", 0) or 0)
    if not cost_r and stop_pct > 0:
        cost_r = 2.0 * float(cfg.shadow_estimated_one_way_cost_pct) / stop_pct
    cost_points = -15.0 if cost_r > 0.18 else -9.0 if cost_r > 0.12 else -4.0 if cost_r > 0.08 else 2.0
    score += cost_points
    reasons.append(f"estimated cost {cost_r:.2f}R ({cost_points:+.0f})")

    signed_rs = float(getattr(a, "relative_strength", 0) or 0) * (1.0 if a.side == "LONG" else -1.0)
    rs_points = 5.0 if signed_rs >= 0.25 else -6.0 if signed_rs <= -0.25 else 0.0
    score += rs_points
    if rs_points:
        reasons.append(f"side-adjusted relative strength {signed_rs:+.2f}% ({rs_points:+.0f})")

    spread = float(getattr(a, "spread_pct", 0) or 0)
    spread_limit = max(float(cfg.max_spread_pct), 1e-9)
    spread_points = -8.0 if spread > 0.75 * spread_limit else 2.0 if spread < 0.25 * spread_limit else 0.0
    score += spread_points
    if spread_points:
        reasons.append(f"spread {spread:.3f}% ({spread_points:+.0f})")

    oi_delta = float(getattr(a, "oi_delta_pct", 0) or 0)
    oi_min = float(cfg.smart_oi_participation_pct)
    oi_points = 4.0 if oi_delta >= oi_min else -3.0 if oi_delta <= -oi_min else 0.0
    score += oi_points
    if oi_points:
        reasons.append(f"open-interest change {oi_delta:+.2f}% ({oi_points:+.0f})")

    funding = float(getattr(a, "funding_rate", 0) or 0)
    crowded = float(cfg.smart_funding_crowded_abs)
    funding_against = (a.side == "LONG" and funding >= crowded) or (a.side == "SHORT" and funding <= -crowded)
    if funding_against:
        score -= 4.0
        reasons.append(f"crowded funding against {a.side} ({funding:+.5f})")

    momentum, micro_aligned, candle_ts = _micro_view(c1m, a.side)
    direction_ok = momentum > 0 if a.side == "LONG" else momentum < 0
    micro_points = 5.0 if direction_ok and micro_aligned >= 2 else -7.0 if not direction_ok and abs(momentum) >= 0.08 else 0.0
    score += micro_points
    if micro_points:
        reasons.append(f"1M momentum {momentum:+.3f}% aligned {micro_aligned}/3 ({micro_points:+.0f})")

    score = round(_clip(score, 0.0, 100.0), 2)

    # Replay separated cost/stop geometry and asymmetric SHORT confirmation
    # more consistently than a descriptive score alone. The strict label is
    # still counterfactual: every source EXECUTE continues through the bridge.
    pass_cost_r = float(getattr(cfg, "smart_pass_max_cost_r", 0.12))
    block_cost_r = float(getattr(cfg, "smart_block_min_cost_r", 0.18))
    cost_ok = 0.0 < cost_r <= pass_cost_r
    short_confirmed = (
        a.side != "SHORT"
        or (
            a.btc_context == "BEARISH"
            and a.eth_context == "BEARISH"
            and float(getattr(a, "relative_strength", 0) or 0) <= -0.25
            and volume >= 1.15
        )
    )
    if cost_ok and short_confirmed and score >= float(cfg.smart_caution_score):
        verdict = "SMART_PASS"
        reasons.append(f"cost/structure guard passed ({cost_r:.2f}R)")
    elif cost_r >= block_cost_r or not short_confirmed or score < float(cfg.smart_caution_score):
        verdict = "SMART_BLOCK"
        if cost_r >= block_cost_r:
            reasons.append(f"cost/stop geometry blocked ({cost_r:.2f}R)")
        if not short_confirmed:
            reasons.append("SHORT lacks BTC+ETH+RS+volume confirmation")
    else:
        verdict = "SMART_CAUTION"
        reasons.append(f"borderline cost/structure ({cost_r:.2f}R)")

    entry_low, entry_high, suggested_sl = _suggested_plan(a, c5)
    features = {
        "side": a.side,
        "base_score": float(a.score),
        "long_score": float(getattr(a, "long_score", 0) or 0),
        "short_score": float(getattr(a, "short_score", 0) or 0),
        "direction_margin": margin,
        "regime_strength": float(getattr(a, "regime_strength", 0) or 0),
        "atr_expansion": float(getattr(a, "atr_expansion", 1) or 1),
        "volume_ratio_5m": volume,
        "estimated_cost_r": cost_r,
        "pass_max_cost_r": pass_cost_r,
        "block_min_cost_r": block_cost_r,
        "short_structure_confirmed": short_confirmed,
        "spread_pct": spread,
        "relative_strength": float(getattr(a, "relative_strength", 0) or 0),
        "oi_delta_pct": oi_delta,
        "open_interest_value": float(getattr(a, "open_interest_value", 0) or 0),
        "funding_rate": funding,
        "micro_momentum_pct": momentum,
        "micro_aligned": micro_aligned,
        "micro_candle_ts": candle_ts,
        "trigger_level": float(getattr(a, "trigger_level", 0) or 0),
    }
    return SmartSignalAssessment(
        a.inst_id, verdict, score, family, regime, margin, time.time(), reasons,
        entry_low, entry_high, suggested_sl, features,
    )


def assess_management(s, a, c1m):
    """Observe a scanner ACTIVE signal; never emit an executable action."""
    risk = abs(float(s.entry) - float(s.sl))
    now = time.time()
    if risk <= 0 or not s.entry:
        return SmartManagementAssessment(
            int(s.id), s.inst_id, "HOLD", 0.0, 0.0, 0.0, 0.0, now, 0,
            str(getattr(a, "market_regime", "TRANSITION")), ["invalid risk geometry"],
        )
    price = float(s.last_price or a.price)
    current_r = (price - s.entry) / risk if s.side == "LONG" else (s.entry - price) / risk
    risk_pct = risk / s.entry * 100.0
    max_r = float(s.max_gain_pct) / risk_pct if risk_pct > 0 else current_r
    max_r = max(max_r, current_r)
    giveback = max(0.0, max_r - current_r)
    momentum, micro_aligned, candle_ts = _micro_view(c1m, s.side)
    direction_ok = momentum > 0 if s.side == "LONG" else momentum < 0
    regime = str(getattr(a, "market_regime", "TRANSITION") or "TRANSITION")
    adverse = []
    if s.side == "LONG":
        if a.bias_1h == "BEARISH": adverse.append("1H bearish")
        if str(a.setup_15m).startswith("BEARISH"): adverse.append("15M bearish")
        if a.side == "SHORT" and a.score >= 76: adverse.append("opposite SHORT setup")
        if a.btc_context == "BEARISH": adverse.append("BTC bearish")
    else:
        if a.bias_1h == "BULLISH": adverse.append("1H bullish")
        if str(a.setup_15m).startswith("BULLISH"): adverse.append("15M bullish")
        if a.side == "LONG" and a.score >= 76: adverse.append("opposite LONG setup")
        if a.btc_context == "BULLISH": adverse.append("BTC bullish")
    if not direction_ok and abs(momentum) >= 0.08:
        adverse.append(f"1M momentum opposite {momentum:+.3f}%")
    if setup_family(s.setup_type) == "BREAKOUT_RETEST" and regime == "RANGE":
        adverse.append("breakout returned to range regime")

    age_min = max(0.0, (now - float(s.confirmed_at)) / 60.0)
    health = 68.0 + _clip(current_r * 10.0, -18.0, 18.0) - 9.0 * len(adverse)
    health -= _clip(giveback - 0.30, 0.0, 1.5) * 10.0
    health = round(_clip(health, 0.0, 100.0), 2)

    severe_before_tp1 = not s.tp1_hit and current_r <= -0.45 and len(adverse) >= 2 and age_min >= 5
    severe_after_tp1 = s.tp1_hit and giveback >= 0.55 and len(adverse) >= 2
    if severe_before_tp1 or severe_after_tp1:
        action = "EXIT_CANDIDATE"
    elif s.tp2_hit or (max_r >= 1.8 and giveback >= 0.25):
        action = "TRAIL_CANDIDATE"
    elif s.tp1_hit or (max_r >= 0.95 and giveback >= 0.30):
        action = "PROTECT_CANDIDATE"
    elif len(adverse) >= 2:
        action = "WEAKENING"
    else:
        action = "HOLD"
    reasons = adverse[:4] or [f"setup intact; progress {current_r:+.2f}R"]
    features = {
        "price": price,
        "age_min": age_min,
        "tp1_hit": bool(s.tp1_hit),
        "tp2_hit": bool(s.tp2_hit),
        "micro_momentum_pct": momentum,
        "micro_aligned": micro_aligned,
        "adverse_count": len(adverse),
        "signal_smart_status": str(getattr(s, "smart_status", "PENDING")),
        "signal_smart_score": float(getattr(s, "smart_score", 0) or 0),
    }
    return SmartManagementAssessment(
        int(s.id), s.inst_id, action, health, current_r, max_r, giveback, now,
        candle_ts or int(getattr(a, "trigger_candle_ts", 0) or 0), regime, reasons, features,
    )
