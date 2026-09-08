"""Validated, exchange-independent models for deterministic historical replay."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class IntrabarPolicy(StrEnum):
    """How to resolve a candle that touches both protection and profit levels."""

    ADVERSE_FIRST = "ADVERSE_FIRST"
    TARGET_FIRST = "TARGET_FIRST"


class ReplayStatus(StrEnum):
    NOT_ENTERED = "NOT_ENTERED"
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    STOP = "STOP"
    TP3 = "TP3"
    END_OF_DATA = "END_OF_DATA"


def normalize_timestamp_ms(value: int | float | str, unit: str = "auto") -> int:
    """Normalize a numeric Unix timestamp to integer milliseconds.

    ``unit='auto'`` treats values below 10 billion as Unix seconds and larger
    values as Unix milliseconds. Crypto-market history is recent enough for
    that boundary to be unambiguous in normal use.
    """

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("timestamp must be finite and non-negative")

    normalized_unit = unit.lower()
    if normalized_unit == "auto":
        normalized_unit = "s" if numeric < 10_000_000_000 else "ms"
    if normalized_unit == "s":
        numeric *= 1000
    elif normalized_unit != "ms":
        raise ValueError("timestamp unit must be 'auto', 's', or 'ms'")
    return int(round(numeric))


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("candle timestamp must be non-negative")
        prices = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise ValueError("OHLC prices must be finite and greater than zero")
        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError("volume must be finite and non-negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is inconsistent with OHLC values")


@dataclass(frozen=True, slots=True)
class TradeSetup:
    signal_id: str
    setup_type: str
    side: Side | str
    eligible_from_ms: int
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    tp_fractions: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)

    def __post_init__(self) -> None:
        side = Side(str(self.side).upper())
        object.__setattr__(self, "side", side)
        if not self.signal_id.strip():
            raise ValueError("signal_id must not be empty")
        if not self.setup_type.strip():
            raise ValueError("setup_type must not be empty")
        if self.eligible_from_ms < 0:
            raise ValueError("eligible_from_ms must be non-negative")

        levels = (self.entry, self.stop, self.tp1, self.tp2, self.tp3)
        if not all(math.isfinite(value) and value > 0 for value in levels):
            raise ValueError("trade levels must be finite and greater than zero")
        if side is Side.LONG:
            valid = self.stop < self.entry < self.tp1 < self.tp2 < self.tp3
        else:
            valid = self.stop > self.entry > self.tp1 > self.tp2 > self.tp3
        if not valid:
            raise ValueError("trade level ordering is invalid for the selected side")

        fractions = self.tp_fractions
        if len(fractions) != 3:
            raise ValueError("exactly three TP fractions are required")
        if not all(math.isfinite(value) and value > 0 for value in fractions):
            raise ValueError("TP fractions must be finite and greater than zero")
        if not math.isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("TP fractions must sum to 1.0")


@dataclass(frozen=True, slots=True)
class CostModel:
    """Simple deterministic costs applied to every entry and exit fill."""

    fee_bps_per_side: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        values = (self.fee_bps_per_side, self.slippage_bps)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("fees and slippage must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ReplayFill:
    timestamp_ms: int
    kind: str
    level_price: float
    fill_price: float
    fraction: float


@dataclass(frozen=True, slots=True)
class ReplayResult:
    signal_id: str
    setup_type: str
    side: Side
    status: ReplayStatus
    close_reason: CloseReason | None
    entry_time_ms: int | None
    close_time_ms: int | None
    gross_r: float
    net_r: float
    fee_r: float
    slippage_r: float
    max_favorable_r: float
    max_adverse_r: float
    tp1_hit: bool
    tp2_hit: bool
    tp3_hit: bool
    fills: tuple[ReplayFill, ...]

    @property
    def entered(self) -> bool:
        return self.status is ReplayStatus.CLOSED


def _row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    raise ValueError(f"candle row is missing one of: {', '.join(names)}")


def candle_from_row(
    row: Mapping[str, Any] | Sequence[Any],
    *,
    timestamp_unit: str = "auto",
) -> Candle:
    """Build a validated candle from a mapping or common OHLCV sequence."""

    if isinstance(row, Mapping):
        timestamp = _row_value(row, "timestamp_ms", "timestamp", "time", "ts")
        return Candle(
            timestamp_ms=normalize_timestamp_ms(timestamp, timestamp_unit),
            open=float(_row_value(row, "open", "o")),
            high=float(_row_value(row, "high", "h")),
            low=float(_row_value(row, "low", "l")),
            close=float(_row_value(row, "close", "c")),
            volume=float(row.get("volume", row.get("v", 0.0))),
        )

    if isinstance(row, (str, bytes)) or len(row) < 5:
        raise ValueError("sequence candle rows require at least timestamp + OHLC")
    volume = row[5] if len(row) > 5 else 0.0
    return Candle(
        timestamp_ms=normalize_timestamp_ms(row[0], timestamp_unit),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(volume),
    )


def normalize_candles(
    rows: Iterable[Candle | Mapping[str, Any] | Sequence[Any]],
    *,
    timestamp_unit: str = "auto",
) -> tuple[Candle, ...]:
    """Normalize, sort, and reject duplicate candle timestamps."""

    candles = [
        row if isinstance(row, Candle) else candle_from_row(row, timestamp_unit=timestamp_unit)
        for row in rows
    ]
    candles.sort(key=lambda candle: candle.timestamp_ms)
    timestamps = [candle.timestamp_ms for candle in candles]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("duplicate candle timestamps are not allowed")
    return tuple(candles)
