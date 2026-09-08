from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from models import ExecuteSignal
from storage import Storage


def signal(signal_id="sig-1"):
    return ExecuteSignal(
        signal_id=signal_id,
        symbol="BTCUSDT",
        side="LONG",
        entry=100,
        entry_low=99,
        entry_high=101,
        sl=95,
        tp1=105,
        tp2=110,
        tp3=115,
        source_ts=time.time(),
    )


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "state.db")
        await self.storage.init()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_schema_has_recovery_and_be_columns(self):
        rows = await self.storage._all("PRAGMA table_info(trades)")
        names = {row["name"] for row in rows}
        self.assertTrue(
            {
                "status_updated_at", "close_detected_at", "tp1_expected_qty",
                "be_status", "be_attempts", "be_last_attempt_at", "last_fill_sync_at",
                "tp2_lock_status", "tp2_lock_attempts", "tp2_lock_price",
                "tp2_lock_applied_at", "tp2_lock_last_attempt_at", "tp2_lock_last_error",
            }.issubset(names)
        )
        check = await self.storage._one("PRAGMA quick_check")
        self.assertEqual(next(iter(check.values())), "ok")

    async def test_old_trade_schema_is_migrated_in_place(self):
        old_path = Path(self.temp.name) / "old.db"
        db = sqlite3.connect(old_path)
        try:
            db.execute(
                """CREATE TABLE trades(
                   id INTEGER PRIMARY KEY, signal_id TEXT, symbol TEXT,
                   status TEXT, received_at REAL
                   )"""
            )
            db.execute(
                "INSERT INTO trades VALUES(1,'old-signal','BTCUSDT','CLOSED',123)"
            )
            db.commit()
        finally:
            db.close()
        old = Storage(old_path)
        await old.init()
        columns = {x["name"] for x in await old._all("PRAGMA table_info(trades)")}
        self.assertIn("be_status", columns)
        self.assertIn("tp2_lock_status", columns)
        self.assertIn("close_detected_at", columns)
        row = await old._one("SELECT status_updated_at FROM trades WHERE id=1")
        self.assertEqual(row["status_updated_at"], 123)

    async def test_pending_decision_claim_is_atomic(self):
        s = signal()
        await self.storage.save_pending(s, {"signal_id": s.signal_id})
        results = await asyncio.gather(
            self.storage.claim_pending(s.signal_id),
            self.storage.claim_pending(s.signal_id),
        )
        self.assertEqual(sorted(results), [False, True])
        self.assertTrue(
            await self.storage.resolve_pending(
                s.signal_id, "APPROVED", from_statuses=("PROCESSING",)
            )
        )

    async def test_processing_pending_is_recovered_on_restart(self):
        s = signal("restart-pending")
        await self.storage.save_pending(s, {"signal_id": s.signal_id})
        self.assertTrue(await self.storage.claim_pending(s.signal_id))
        restarted = Storage(self.storage.path)
        await restarted.init()
        row = await restarted.pending_by_signal(s.signal_id)
        self.assertEqual(row["status"], "PENDING")

    async def test_management_event_is_idempotent(self):
        args = ("event-1", "sig-1", "BTCUSDT", "CLOSE", {"x": 1})
        self.assertTrue(await self.storage.claim_management_event(*args))
        self.assertFalse(await self.storage.claim_management_event(*args))
        await self.storage.finish_management_event("event-1", error="transient")
        self.assertTrue(await self.storage.claim_management_event(*args))
        await self.storage.finish_management_event("event-1")
        self.assertFalse(await self.storage.claim_management_event(*args))

    async def test_fill_quantities_separate_entry_and_exit(self):
        trade_id = await self.storage.create_trade(signal(), 1, 5, 10, 2, {})
        await self.storage.add_fill(
            trade_id,
            {
                "execId": "entry", "side": "Buy", "execPrice": "100",
                "execQty": "2", "execValue": "200", "execFee": "0.1",
                "execTime": 1,
            },
        )
        await self.storage.add_fill(
            trade_id,
            {
                "execId": "exit", "side": "Sell", "execPrice": "105",
                "execQty": "2", "execValue": "210", "execFee": "0.1",
                "execTime": 2, "closedSize": "2",
            },
        )
        self.assertEqual(
            await self.storage.fill_quantities(trade_id),
            {"entry": 2.0, "exit": 2.0},
        )
