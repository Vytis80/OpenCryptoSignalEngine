import math
import time
import unittest

from models import ExecuteSignal, ManagementEvent


def execute_payload(**overrides):
    payload = {
        "signal_id": "sig-1",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "entry": 100.0,
        "entry_low": 99.0,
        "entry_high": 101.0,
        "sl": 95.0,
        "tp1": 105.0,
        "tp2": 110.0,
        "tp3": 115.0,
        "source_ts": time.time(),
    }
    payload.update(overrides)
    return payload


class ModelValidationTests(unittest.TestCase):
    def test_execute_rejects_non_finite_levels(self):
        with self.assertRaises(ValueError):
            ExecuteSignal.from_payload(execute_payload(tp1=math.inf))

    def test_execute_rejects_expiry_before_source(self):
        now = time.time()
        with self.assertRaises(ValueError):
            ExecuteSignal.from_payload(
                execute_payload(source_ts=now, expires_at=now - 1)
            )

    def test_management_requires_event_and_signal_identity(self):
        with self.assertRaises(ValueError):
            ManagementEvent.from_payload(
                {"symbol": "BTCUSDT", "action": "CLOSE"}
            )
        event = ManagementEvent.from_payload(
            {
                "event_id": "event-1",
                "signal_id": "signal-1",
                "symbol": "BTC/USDT",
                "action": "close",
            }
        )
        self.assertEqual(event.symbol, "BTCUSDT")
        self.assertEqual(event.action, "CLOSE")
