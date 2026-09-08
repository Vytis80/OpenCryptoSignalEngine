from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Config


class ConfigTests(unittest.TestCase):
    def environment(self, db_path: Path, **overrides):
        values = {
            "BYBIT_DEMO_API_KEY": "test-key",
            "BYBIT_DEMO_API_SECRET": "test-secret",
            "BRIDGE_SECRET": "x" * 32,
            "DB_PATH": str(db_path),
        }
        values.update(overrides)
        return values

    def test_safe_default_keeps_manual_shadow_and_uses_twenty_position_default(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.environment(Path(temp) / "state.db")
            with patch.dict(os.environ, env, clear=True):
                cfg = Config.from_env()
        self.assertEqual(cfg.execution_mode, "SHADOW_MANUAL")
        self.assertEqual(cfg.max_open_positions, 20)
        self.assertEqual(cfg.risk_pct, 1.0)
        self.assertTrue(cfg.tp2_lock_sl_to_tp1_enabled)

    def test_all_execute_mode_and_twenty_position_override_validate(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.environment(
                Path(temp) / "state.db",
                EXECUTION_MODE="ALL_EXECUTE",
                MAX_OPEN_POSITIONS="20",
            )
            with patch.dict(os.environ, env, clear=True):
                cfg = Config.from_env()
        self.assertEqual(cfg.execution_mode, "ALL_EXECUTE")
        self.assertEqual(cfg.max_open_positions, 20)

    def test_unknown_execution_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.environment(
                Path(temp) / "state.db",
                EXECUTION_MODE="UNKNOWN",
            )
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, "EXECUTION_MODE"):
                    Config.from_env()
