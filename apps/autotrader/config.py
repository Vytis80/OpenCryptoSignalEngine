from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Config:
    bybit_api_key: str
    bybit_api_secret: str
    bridge_secret: str
    bridge_host: str
    bridge_port: int
    discord_bot_token: str
    discord_channel_id: int
    discord_admin_user_ids: set[int]
    db_path: Path

    auto_trading_enabled: bool
    execution_mode: str
    risk_pct: float
    leverage: int
    min_margin_usdt: float
    max_open_positions: int
    max_margin_fraction: float
    max_notional_usdt: float
    entry_tolerance_pct: float
    tp1_fraction: float
    tp2_fraction: float
    tp3_fraction: float
    sl_trigger_by: str
    tp_trigger_by: str
    reconcile_sec: float

    smart_margin_enabled: bool
    smart_margin_buffer_stop_fraction: float
    smart_margin_max_extra_ratio: float
    smart_margin_step_usdt: float
    smart_position_shadow_enabled: bool
    smart_position_history_sec: float
    tp2_lock_sl_to_tp1_enabled: bool

    @classmethod
    def from_env(cls) -> "Config":
        admins = {
            int(x.strip())
            for x in os.getenv("DISCORD_ADMIN_USER_IDS", "").split(",")
            if x.strip().isdigit()
        }
        cfg = cls(
            bybit_api_key=os.getenv("BYBIT_DEMO_API_KEY", "").strip(),
            bybit_api_secret=os.getenv("BYBIT_DEMO_API_SECRET", "").strip(),
            bridge_secret=os.getenv("BRIDGE_SECRET", "").strip(),
            bridge_host=os.getenv("BRIDGE_HOST", "0.0.0.0").strip(),
            bridge_port=_int("BRIDGE_PORT", 8787),
            discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
            discord_channel_id=_int("DISCORD_CHANNEL_ID", 0),
            discord_admin_user_ids=admins,
            db_path=Path(os.getenv("DB_PATH", "data/demo_trader.db")),
            auto_trading_enabled=_bool("AUTO_TRADING_ENABLED", True),
            execution_mode=os.getenv("EXECUTION_MODE", "SHADOW_MANUAL").strip().upper().replace("-", "_"),
            risk_pct=_float("RISK_PCT", 1.0),
            leverage=_int("LEVERAGE", 10),
            min_margin_usdt=_float("MIN_MARGIN_USDT", 100.0),
            max_open_positions=_int("MAX_OPEN_POSITIONS", 20),
            max_margin_fraction=_float("MAX_MARGIN_FRACTION", 0.35),
            max_notional_usdt=_float("MAX_NOTIONAL_USDT", 0.0),
            entry_tolerance_pct=_float("ENTRY_TOLERANCE_PCT", 0.10),
            tp1_fraction=_float("TP1_FRACTION", 0.40),
            tp2_fraction=_float("TP2_FRACTION", 0.30),
            tp3_fraction=_float("TP3_FRACTION", 0.30),
            sl_trigger_by=os.getenv("SL_TRIGGER_BY", "MarkPrice").strip(),
            tp_trigger_by=os.getenv("TP_TRIGGER_BY", "LastPrice").strip(),
            reconcile_sec=_float("RECONCILE_SEC", 3.0),
            smart_margin_enabled=_bool("SMART_MARGIN_ENABLED", True),
            smart_margin_buffer_stop_fraction=_float("SMART_MARGIN_BUFFER_STOP_FRACTION", 0.20),
            smart_margin_max_extra_ratio=_float("SMART_MARGIN_MAX_EXTRA_RATIO", 1.0),
            smart_margin_step_usdt=_float("SMART_MARGIN_STEP_USDT", 25.0),
            smart_position_shadow_enabled=_bool("SMART_POSITION_SHADOW_ENABLED", True),
            smart_position_history_sec=_float("SMART_POSITION_HISTORY_SEC", 60.0),
            tp2_lock_sl_to_tp1_enabled=_bool("TP2_LOCK_SL_TO_TP1_ENABLED", True),
        )
        cfg.validate()
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        return cfg

    def validate(self) -> None:
        if not self.bybit_api_key or not self.bybit_api_secret:
            raise ValueError("BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required")
        if len(self.bridge_secret) < 24:
            raise ValueError("BRIDGE_SECRET must be at least 24 characters")
        if self.discord_bot_token and not self.discord_channel_id:
            raise ValueError("DISCORD_CHANNEL_ID is required when DISCORD_BOT_TOKEN is set")
        if self.execution_mode not in {"SHADOW_MANUAL", "ALL_EXECUTE"}:
            raise ValueError("EXECUTION_MODE must be SHADOW_MANUAL or ALL_EXECUTE")
        if not (0 < self.risk_pct <= 10):
            raise ValueError("RISK_PCT must be >0 and <=10")
        if self.leverage != 10:
            raise ValueError("LEVERAGE target is fixed at 10 for this bot")
        if self.min_margin_usdt < 100:
            raise ValueError("MIN_MARGIN_USDT must be >=100")
        if self.max_notional_usdt > 0 and self.max_notional_usdt < self.min_margin_usdt * self.leverage:
            raise ValueError("MAX_NOTIONAL_USDT cannot be below MIN_MARGIN_USDT * LEVERAGE")
        if self.max_open_positions < 1:
            raise ValueError("MAX_OPEN_POSITIONS must be >=1")
        if not (0 < self.max_margin_fraction <= 1):
            raise ValueError("MAX_MARGIN_FRACTION must be >0 and <=1")
        fracs = self.tp1_fraction + self.tp2_fraction + self.tp3_fraction
        if abs(fracs - 1.0) > 1e-9:
            raise ValueError("TP1_FRACTION + TP2_FRACTION + TP3_FRACTION must equal 1.0")
        if self.sl_trigger_by not in {"LastPrice", "MarkPrice", "IndexPrice"}:
            raise ValueError("Invalid SL_TRIGGER_BY")
        if self.tp_trigger_by not in {"LastPrice", "MarkPrice", "IndexPrice"}:
            raise ValueError("Invalid TP_TRIGGER_BY")
        if not (0 <= self.smart_margin_buffer_stop_fraction <= 2):
            raise ValueError("SMART_MARGIN_BUFFER_STOP_FRACTION must be between 0 and 2")
        if not (0 <= self.smart_margin_max_extra_ratio <= 5):
            raise ValueError("SMART_MARGIN_MAX_EXTRA_RATIO must be between 0 and 5")
        if self.smart_margin_step_usdt <= 0:
            raise ValueError("SMART_MARGIN_STEP_USDT must be >0")
        if self.smart_position_history_sec < 10:
            raise ValueError("SMART_POSITION_HISTORY_SEC must be >=10")
