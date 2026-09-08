from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lifecycle_executor import LifecycleDemoExecutor
from storage import Storage
from tests.helpers import NotifierStub, cfg_stub
from tests.test_executor import BybitStub, signal


class LifecycleExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "state.db")
        await self.storage.init()
        self.bybit = BybitStub()
        self.notifier = NotifierStub()
        self.executor = LifecycleDemoExecutor(
            cfg_stub(), self.bybit, self.storage, self.notifier
        )

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def make_trade(self):
        trade_id = await self.storage.create_trade(signal(), 1, 10, 10, 1, {})
        links = ("BDT1-TP1", "BDT1-TP2", "BDT1-TP3")
        await self.storage.set_order_plan(
            trade_id, "BDT1-ENTRY", links, (0.4, 0.3, 0.3)
        )
        await self.storage.mark_opened(
            trade_id, 100, 1, 5, "order-1", "BDT1-ENTRY", links
        )
        return await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade_id,)
        )

    def test_strictest_current_stop_is_side_aware(self):
        self.assertEqual(
            self.executor._strictest_current_stop("LONG", 100.0, 102.0), 102.0
        )
        self.assertEqual(
            self.executor._strictest_current_stop("SHORT", 100.0, 98.0), 98.0
        )
        self.assertEqual(
            self.executor._strictest_current_stop("BUY", 100.0, 102.0), 102.0
        )
        self.assertEqual(
            self.executor._strictest_current_stop("SELL", 100.0, 98.0), 98.0
        )

    async def test_tp1_then_tp2_uses_shared_lifecycle_targets(self):
        trade = await self.make_trade()
        await self.storage.set_tp_hit(trade["id"], 1)
        trade = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )

        note = await self.executor._attempt_tp1_breakeven(
            trade, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("BREAKEVEN", note)
        after_tp1 = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )
        self.assertEqual(after_tp1["sl"], 100.0)
        self.assertEqual(after_tp1["be_status"], "APPLIED")

        await self.storage.set_tp_hit(trade["id"], 2)
        self.bybit.ticker_price = 111.0
        after_tp1 = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )
        note = await self.executor._attempt_tp2_lock_to_tp1(
            after_tp1, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("SL → **TP1**", note)
        after_tp2 = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )
        self.assertEqual(after_tp2["sl"], 105.0)
        self.assertEqual(after_tp2["tp2_lock_status"], "APPLIED")

    async def test_tp2_contract_never_loosen_stricter_stop(self):
        trade = await self.make_trade()
        await self.storage.set_tp_hit(trade["id"], 2)
        await self.storage.update_sl(trade["id"], 107.0, "stricter test stop")
        self.bybit.stop = 107.0
        self.bybit.ticker_price = 111.0
        trade = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )

        note = await self.executor._attempt_tp2_lock_to_tp1(
            trade, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("better than", note)
        after = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )
        self.assertEqual(after["sl"], 107.0)
        self.assertEqual(after["tp2_lock_status"], "NOT_NEEDED")
        self.assertEqual(self.bybit.stop_calls, 0)

    async def test_restart_reconciliation_adopts_stricter_exchange_stop(self):
        trade = await self.make_trade()
        self.bybit.stop = 102.0
        pos = await self.bybit.position("BTCUSDT")

        await self.executor._restore_monotonic_stop(trade, pos)

        after = await self.storage._one(
            "SELECT * FROM trades WHERE id=?", (trade["id"],)
        )
        self.assertEqual(after["sl"], 102.0)
        self.assertEqual(self.bybit.stop_calls, 0)


if __name__ == "__main__":
    unittest.main()
