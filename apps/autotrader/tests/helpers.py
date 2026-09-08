from __future__ import annotations

from types import SimpleNamespace


class NotifierStub:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, text: str, **_kwargs):
        self.messages.append(text)
        return None

    def shadow_view(self, *_args, **_kwargs):
        return None


def cfg_stub(**overrides):
    values = {
        "sl_trigger_by": "MarkPrice",
        "tp_trigger_by": "LastPrice",
        "tp1_fraction": 0.4,
        "tp2_fraction": 0.3,
        "tp3_fraction": 0.3,
        "reconcile_sec": 0.01,
        "smart_margin_enabled": False,
        "smart_margin_buffer_stop_fraction": 0.2,
        "smart_margin_max_extra_ratio": 1.0,
        "smart_margin_step_usdt": 25.0,
        "max_margin_fraction": 0.35,
        "leverage": 10,
        "execution_mode": "SHADOW_MANUAL",
        "auto_trading_enabled": True,
        "max_open_positions": 20,
        "entry_tolerance_pct": 0.10,
        "tp2_lock_sl_to_tp1_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)
