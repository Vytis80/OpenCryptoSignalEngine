from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

from open_crypto_signal_engine.protocol import normalize_side, normalize_symbol


def _identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required for idempotency")
    if len(text) > 128:
        raise ValueError(f"{name} is too long")
    return text


@dataclass
class ExecuteSignal:
    signal_id: str
    symbol: str
    side: str
    entry: float
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    quality: str = ""
    score: float = 0.0
    setup_type: str = ""
    source_ts: float = 0.0
    shadow_status: str = ""
    shadow_note: str = ""
    expires_at: float = 0.0
    smart_status: str = ""
    smart_score: float = 0.0
    smart_note: str = ""
    smart_setup: str = ""
    smart_regime: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecuteSignal":
        obj = cls(
            signal_id=_identifier(payload.get("signal_id") or payload.get("id"), "signal_id"),
            symbol=normalize_symbol(payload["symbol"]),
            side=normalize_side(payload["side"]),
            entry=float(payload["entry"]),
            entry_low=float(payload.get("entry_low", payload["entry"])),
            entry_high=float(payload.get("entry_high", payload["entry"])),
            sl=float(payload["sl"]),
            tp1=float(payload["tp1"]),
            tp2=float(payload["tp2"]),
            tp3=float(payload["tp3"]),
            quality=str(payload.get("quality", "")),
            score=float(payload.get("score", 0.0)),
            setup_type=str(payload.get("setup_type", "")),
            source_ts=float(payload.get("source_ts", 0.0) or 0.0),
            shadow_status=str(payload.get("shadow_status", "") or ""),
            shadow_note=str(payload.get("shadow_note", "") or ""),
            expires_at=float(payload.get("expires_at", 0.0) or 0.0),
            smart_status=str(payload.get("smart_status", "") or "")[:64],
            smart_score=float(payload.get("smart_score", 0.0) or 0.0),
            smart_note=str(payload.get("smart_note", "") or "")[:2000],
            smart_setup=str(payload.get("smart_setup", "") or "")[:128],
            smart_regime=str(payload.get("smart_regime", "") or "")[:64],
        )
        now = time.time()
        if obj.source_ts and obj.source_ts > now + 300:
            raise ValueError("source_ts is too far in the future")
        if obj.expires_at and obj.source_ts and obj.expires_at < obj.source_ts:
            raise ValueError("expires_at cannot be before source_ts")
        if not math.isfinite(obj.smart_score) or not (0 <= obj.smart_score <= 100):
            raise ValueError("smart_score must be finite and between 0 and 100")
        obj.validate_levels()
        return obj

    def validate_levels(self) -> None:
        vals = [self.entry, self.entry_low, self.entry_high, self.sl, self.tp1, self.tp2, self.tp3]
        if any(not math.isfinite(v) or v <= 0 for v in vals):
            raise ValueError("all price levels must be finite and >0")
        if self.entry_low > self.entry_high:
            raise ValueError("entry_low cannot be greater than entry_high")
        if self.side == "LONG":
            if not (self.sl < self.entry and self.entry < self.tp1 <= self.tp2 <= self.tp3):
                raise ValueError("invalid LONG level ordering")
        else:
            if not (self.sl > self.entry and self.entry > self.tp1 >= self.tp2 >= self.tp3):
                raise ValueError("invalid SHORT level ordering")


@dataclass
class ManagementEvent:
    event_id: str
    signal_id: str
    symbol: str
    action: str
    reason: str = ""
    price: float | None = None
    new_sl: float | None = None
    source_ts: float = 0.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ManagementEvent":
        obj = cls(
            event_id=_identifier(payload.get("event_id") or payload.get("id"), "event_id"),
            signal_id=_identifier(payload.get("signal_id"), "signal_id"),
            symbol=normalize_symbol(payload["symbol"]),
            action=str(payload["action"]).upper(),
            reason=str(payload.get("reason", payload.get("note", ""))),
            price=float(payload["price"]) if payload.get("price") is not None else None,
            new_sl=float(payload["new_sl"]) if payload.get("new_sl") is not None else None,
            source_ts=float(payload.get("source_ts", 0.0) or 0.0),
        )
        for name, value in (("price", obj.price), ("new_sl", obj.new_sl), ("source_ts", obj.source_ts)):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if obj.new_sl is not None and obj.new_sl <= 0:
            raise ValueError("new_sl must be >0")
        if obj.source_ts and obj.source_ts > time.time() + 300:
            raise ValueError("source_ts is too far in the future")
        return obj
