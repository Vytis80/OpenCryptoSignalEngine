"""Shared scanner-to-executor bridge transport and event contract.

The protocol is intentionally exchange-independent. It defines deterministic JSON
serialization, HMAC authentication, timestamp freshness checks and common event
validation while leaving strategy and exchange execution to the active components.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Mapping
from typing import Any

BRIDGE_PROTOCOL_VERSION = "1"
TIMESTAMP_HEADER = "X-Bridge-Timestamp"
SIGNATURE_HEADER = "X-Bridge-Signature"
VERSION_HEADER = "X-Bridge-Version"
DEFAULT_MAX_SKEW_SEC = 30

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,24}$")
_MANAGEMENT_EVENT_ALIASES = {
    "MANAGEMENT",
    "PROTECT",
    "MOVE_SL",
    "CLOSE",
    "INVALIDATED",
    "CLOSE_EARLY",
}


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize a bridge payload deterministically as compact UTF-8 JSON.

    Sorting keys makes newly produced signatures reproducible regardless of Python
    dictionary construction order. Verification always authenticates the raw body,
    so existing unsorted v1 clients remain wire-compatible.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("bridge payload must be a mapping")
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _secret_bytes(secret: str) -> bytes:
    value = str(secret or "")
    if not value:
        raise ValueError("bridge secret must not be empty")
    return value.encode("utf-8")


def _timestamp_text(timestamp: int | str) -> str:
    text = str(timestamp).strip()
    if not text:
        raise ValueError("bridge timestamp is required")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError("bridge timestamp must be an integer Unix second") from exc
    if parsed < 0:
        raise ValueError("bridge timestamp must be non-negative")
    return str(parsed)


def sign_bridge_body(secret: str, timestamp: int | str, body: bytes) -> str:
    """Return the v1 hex HMAC-SHA256 signature for an already-serialized body."""

    if not isinstance(body, bytes):
        raise TypeError("bridge body must be bytes")
    ts = _timestamp_text(timestamp)
    return hmac.new(
        _secret_bytes(secret),
        ts.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()


def bridge_headers(secret: str, timestamp: int | str, body: bytes) -> dict[str, str]:
    """Build the HTTP headers used by the v1 signed bridge transport."""

    ts = _timestamp_text(timestamp)
    return {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: ts,
        SIGNATURE_HEADER: sign_bridge_body(secret, ts, body),
        VERSION_HEADER: BRIDGE_PROTOCOL_VERSION,
    }


def verify_bridge_signature(
    secret: str,
    timestamp: int | str,
    signature: str,
    body: bytes,
    *,
    now: float | None = None,
    max_skew_sec: int = DEFAULT_MAX_SKEW_SEC,
) -> bool:
    """Verify freshness and HMAC without reserializing the request body."""

    if max_skew_sec < 0:
        raise ValueError("max_skew_sec must be non-negative")
    if not isinstance(body, bytes):
        return False
    try:
        ts = _timestamp_text(timestamp)
        parsed = int(ts)
        current = int(time.time() if now is None else now)
        if abs(current - parsed) > max_skew_sec:
            return False
        expected = sign_bridge_body(secret, ts, body)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(str(signature or ""), expected)


def normalize_symbol(value: Any) -> str:
    """Normalize the USDT-linear symbol spelling accepted by current components."""

    text = str(value).upper().replace("-", "").replace("_", "").replace("/", "")
    if text.endswith("USDTUSDT"):
        text = text[:-4]
    if not _SYMBOL_RE.fullmatch(text):
        raise ValueError("invalid symbol")
    return text


def normalize_side(value: Any) -> str:
    side = str(value or "").upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    return side


def _identifier(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required for idempotency")
    if len(text) > 128:
        raise ValueError(f"{name} is too long")
    return text


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _validate_source_times(source_ts: float, expires_at: float, *, now: float | None) -> None:
    current = time.time() if now is None else float(now)
    if source_ts and source_ts > current + 300:
        raise ValueError("source_ts is too far in the future")
    if expires_at and source_ts and expires_at < source_ts:
        raise ValueError("expires_at cannot be before source_ts")


def build_execute_payload(
    *,
    signal_id: Any,
    symbol: Any,
    side: Any,
    entry: Any,
    entry_low: Any,
    entry_high: Any,
    sl: Any,
    tp1: Any,
    tp2: Any,
    tp3: Any,
    quality: Any = "",
    score: Any = 0.0,
    setup_type: Any = "",
    source_ts: Any = 0.0,
    expires_at: Any = 0.0,
    shadow_status: Any = "",
    shadow_note: Any = "",
    extra: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Build and validate a common EXECUTE event without strategy-side effects."""

    normalized_side = normalize_side(side)
    entry_value = _positive(entry, "entry")
    low_value = _positive(entry_low, "entry_low")
    high_value = _positive(entry_high, "entry_high")
    stop_value = _positive(sl, "sl")
    tp1_value = _positive(tp1, "tp1")
    tp2_value = _positive(tp2, "tp2")
    tp3_value = _positive(tp3, "tp3")
    score_value = _finite(score, "score")
    source_value = _finite(source_ts or 0.0, "source_ts")
    expires_value = _finite(expires_at or 0.0, "expires_at")

    if low_value > high_value:
        raise ValueError("entry_low cannot be greater than entry_high")
    if normalized_side == "LONG":
        valid = stop_value < entry_value < tp1_value <= tp2_value <= tp3_value
    else:
        valid = stop_value > entry_value > tp1_value >= tp2_value >= tp3_value
    if not valid:
        raise ValueError(f"invalid {normalized_side} level ordering")
    _validate_source_times(source_value, expires_value, now=now)

    payload: dict[str, Any] = {
        "event": "EXECUTE",
        "signal_id": _identifier(signal_id, "signal_id"),
        "symbol": normalize_symbol(symbol),
        "side": normalized_side,
        "entry": entry_value,
        "entry_low": low_value,
        "entry_high": high_value,
        "sl": stop_value,
        "tp1": tp1_value,
        "tp2": tp2_value,
        "tp3": tp3_value,
        "quality": str(quality or ""),
        "score": score_value,
        "setup_type": str(setup_type or ""),
        "source_ts": source_value,
        "expires_at": expires_value,
        "shadow_status": str(shadow_status or ""),
        "shadow_note": str(shadow_note or ""),
    }
    if extra:
        overlap = set(payload).intersection(extra)
        if overlap:
            raise ValueError(
                "extra EXECUTE fields cannot override reserved keys: "
                f"{sorted(overlap)}"
            )
        payload.update(dict(extra))
    return payload


def build_management_payload(
    *,
    event_id: Any,
    signal_id: Any,
    symbol: Any,
    action: Any,
    reason: Any = "",
    price: Any = None,
    new_sl: Any = None,
    source_ts: Any = 0.0,
    extra: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Build and validate a common MANAGEMENT event."""

    action_text = str(action or "").strip().upper()
    if not action_text:
        raise ValueError("action is required")
    if len(action_text) > 64:
        raise ValueError("action is too long")
    source_value = _finite(source_ts or 0.0, "source_ts")
    _validate_source_times(source_value, 0.0, now=now)

    payload: dict[str, Any] = {
        "event": "MANAGEMENT",
        "event_id": _identifier(event_id, "event_id"),
        "signal_id": _identifier(signal_id, "signal_id"),
        "symbol": normalize_symbol(symbol),
        "action": action_text,
        "reason": str(reason or ""),
        "source_ts": source_value,
    }
    if price is not None:
        payload["price"] = _finite(price, "price")
    if new_sl is not None:
        payload["new_sl"] = _positive(new_sl, "new_sl")
    if extra:
        overlap = set(payload).intersection(extra)
        if overlap:
            raise ValueError(
                f"extra MANAGEMENT fields cannot override reserved keys: {sorted(overlap)}"
            )
        payload.update(dict(extra))
    return payload


def validate_event_payload(
    payload: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Validate/normalize an incoming v1 event while preserving extension fields."""

    if not isinstance(payload, Mapping):
        raise ValueError("request body must be a JSON object")
    raw = dict(payload)
    event = str(raw.get("event", "EXECUTE") or "EXECUTE").upper()

    if event == "EXECUTE":
        known = {
            "event",
            "signal_id",
            "id",
            "symbol",
            "side",
            "entry",
            "entry_low",
            "entry_high",
            "sl",
            "tp1",
            "tp2",
            "tp3",
            "quality",
            "score",
            "setup_type",
            "source_ts",
            "expires_at",
            "shadow_status",
            "shadow_note",
        }
        extra = {key: value for key, value in raw.items() if key not in known}
        return build_execute_payload(
            signal_id=raw.get("signal_id") or raw.get("id"),
            symbol=raw["symbol"],
            side=raw["side"],
            entry=raw["entry"],
            entry_low=raw.get("entry_low", raw["entry"]),
            entry_high=raw.get("entry_high", raw["entry"]),
            sl=raw["sl"],
            tp1=raw["tp1"],
            tp2=raw["tp2"],
            tp3=raw["tp3"],
            quality=raw.get("quality", ""),
            score=raw.get("score", 0.0),
            setup_type=raw.get("setup_type", ""),
            source_ts=raw.get("source_ts", 0.0),
            expires_at=raw.get("expires_at", 0.0),
            shadow_status=raw.get("shadow_status", ""),
            shadow_note=raw.get("shadow_note", ""),
            extra=extra,
            now=now,
        )

    if event in _MANAGEMENT_EVENT_ALIASES:
        known = {
            "event",
            "event_id",
            "id",
            "signal_id",
            "symbol",
            "action",
            "reason",
            "note",
            "price",
            "new_sl",
            "source_ts",
        }
        extra = {key: value for key, value in raw.items() if key not in known}
        action = raw.get("action") or (event if event != "MANAGEMENT" else "")
        return build_management_payload(
            event_id=raw.get("event_id") or raw.get("id"),
            signal_id=raw.get("signal_id"),
            symbol=raw["symbol"],
            action=action,
            reason=raw.get("reason", raw.get("note", "")),
            price=raw.get("price"),
            new_sl=raw.get("new_sl"),
            source_ts=raw.get("source_ts", 0.0),
            extra=extra,
            now=now,
        )

    raise ValueError(f"unknown event {event}")
