from __future__ import annotations

import tempfile
import time
import unittest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from bybit_demo import BybitDemo
from executor import DemoExecutor
from models import ExecuteSignal
from storage import Storage
from tests.helpers import NotifierStub, cfg_stub


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


def signal_payload(signal_id="sig-execute", shadow_status="WOULD_BLOCK"):
    now = time.time()
    return {
        "event": "EXECUTE",
        "signal_id": signal_id,
        "symbol": "BTCUSDT",
        "side": "LONG",
        "entry": 100,
        "entry_low": 99,
        "entry_high": 101,
        "sl": 95,
        "tp1": 105,
        "tp2": 110,
        "tp3": 115,
        "source_ts": now,
        "expires_at": now + 600,
        "shadow_status": shadow_status,
        "shadow_note": "audit verdict",
    }


class BybitStub:
    def __init__(self):
        self.stop = 95.0
        self.fail_stop_once = False
        self.stop_calls = 0
        self.execution_rows = []
        self.ticker_price = 106.0
        self.position_row = {
            "symbol": "BTCUSDT", "size": "0.6", "avgPrice": "100",
            "stopLoss": str(self.stop),
        }

    async def executions(self, *_args, **_kwargs):
        return list(self.execution_rows)

    async def ticker(self, _symbol):
        return self.ticker_price

    async def positions(self):
        return []

    async def instrument(self, _symbol):
        return {
            "priceFilter": {"tickSize": "0.1"},
            "lotSizeFilter": {"qtyStep": "0.1", "minOrderQty": "0.1"},
        }

    def quantize_price(self, price, instrument):
        return round(price, 1)

    async def set_full_stop(self, _symbol, stop, _trigger):
        self.stop_calls += 1
        if self.fail_stop_once:
            self.fail_stop_once = False
            raise RuntimeError("transient")
        self.stop = float(stop)

    async def position(self, _symbol):
        if self.position_row is None:
            return None
        return {**self.position_row, "stopLoss": str(self.stop)}


class EntryBybitStub(BybitStub):
    def __init__(self, max_leverage="6.5"):
        super().__init__()
        self.position_row = None
        self.ticker_price = 100.0
        self.max_leverage = str(max_leverage)
        self.selected_leverage = None
        self.tp_orders = []

    async def wallet(self):
        return {"equity": 1000.0, "available": 1000.0}

    async def instrument(self, _symbol):
        return {
            "priceFilter": {"tickSize": "0.1"},
            "lotSizeFilter": {
                "qtyStep": "0.1", "minOrderQty": "0.1", "minNotionalValue": "5",
            },
            "leverageFilter": {
                "minLeverage": "1", "maxLeverage": self.max_leverage,
                "leverageStep": "0.1",
            },
        }

    def quantize_qty(self, raw_qty, instrument):
        return BybitDemo.quantize_qty(raw_qty, instrument)

    def quantize_qty_up(self, raw_qty, instrument):
        return BybitDemo.quantize_qty_up(raw_qty, instrument)

    def split_qty(self, total_qty, fractions, instrument):
        return BybitDemo.split_qty(total_qty, fractions, instrument)

    async def ensure_isolated_margin(self):
        return {"marginMode": "ISOLATED_MARGIN"}

    async def set_leverage(self, _symbol, leverage):
        self.selected_leverage = float(leverage)
        return {"retCode": 0}

    async def place_market_entry(
        self, symbol, _side, qty, _link_id, stop_loss, _sl_trigger_by
    ):
        size = float(qty)
        self.stop = float(stop_loss)
        self.position_row = {
            "symbol": symbol,
            "size": str(size),
            "avgPrice": "100",
            "stopLoss": str(stop_loss),
            "markPrice": "100",
            "liqPrice": "0",
            "positionValue": str(size * 100),
            "positionIM": str(size * 100 / self.selected_leverage),
            "leverage": str(self.selected_leverage),
        }
        return {"retCode": 0, "result": {"orderId": "entry-order"}}

    async def set_auto_add_margin(self, _symbol, _enabled=False):
        return {"retCode": 0}

    async def place_reduce_trigger(
        self, symbol, side, qty, trigger_price, trigger_by, link_id
    ):
        self.tp_orders.append((symbol, side, qty, trigger_price, trigger_by, link_id))
        return {"retCode": 0}


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "state.db")
        await self.storage.init()
        self.bybit = BybitStub()
        self.notifier = NotifierStub()
        self.executor = DemoExecutor(
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
        return await self.storage._one("SELECT * FROM trades WHERE id=?", (trade_id,))

    def test_leverage_selection_prefers_ten_then_instrument_maximum(self):
        instrument = {
            "leverageFilter": {
                "minLeverage": "1", "maxLeverage": "25", "leverageStep": "0.1",
            }
        }
        self.assertEqual(self.executor._select_leverage(instrument, 10), 10.0)
        instrument["leverageFilter"]["maxLeverage"] = "6.5"
        self.assertEqual(self.executor._select_leverage(instrument, 10), 6.5)
        instrument["leverageFilter"]["maxLeverage"] = "5"
        self.assertEqual(self.executor._select_leverage(instrument, 10), 5.0)

    def test_invalid_leverage_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "leverage"):
            self.executor._select_leverage({"leverageFilter": {}}, 10)
        with self.assertRaisesRegex(ValueError, "leverage"):
            self.executor._select_leverage(
                {"leverageFilter": {"minLeverage": "1", "maxLeverage": "NaN"}}, 10
            )

    async def test_execute_uses_decimal_instrument_maximum_instead_of_skipping(self):
        bybit = EntryBybitStub("6.5")
        executor = DemoExecutor(
            cfg_stub(
                execution_mode="ALL_EXECUTE", risk_pct=1.0,
                min_margin_usdt=100.0, max_notional_usdt=0.0,
            ),
            bybit, self.storage, self.notifier,
        )

        result = await executor.execute(
            signal_payload("fallback-open", shadow_status="PASS")
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["leverage"], 6.5)
        self.assertEqual(bybit.selected_leverage, 6.5)
        trade = await self.storage.by_signal("fallback-open")
        self.assertEqual(float(trade["leverage"]), 6.5)
        self.assertAlmostEqual(float(trade["planned_qty"]), 6.5)
        events = await self.storage._all(
            "SELECT event_type FROM events WHERE trade_id=? ORDER BY id", (trade["id"],)
        )
        self.assertIn("LEVERAGE_FALLBACK_SELECTED", {x["event_type"] for x in events})
        self.assertEqual(len(bybit.tp_orders), 3)

    async def test_shadow_would_block_stays_manual_in_legacy_mode(self):
        result = await self.executor.execute(signal_payload("manual-shadow"))
        self.assertEqual(result["skipped"], "shadow_manual_pending")
        pending = await self.storage.pending_by_signal("manual-shadow")
        self.assertEqual(pending["status"], "PENDING")

    async def test_all_execute_bypasses_shadow_and_waits_for_exact_entry(self):
        self.executor.cfg = cfg_stub(execution_mode="ALL_EXECUTE")
        self.bybit.position_row = None
        self.bybit.ticker_price = 110.0

        result = await self.executor.execute(signal_payload("all-execute-wait"))

        self.assertEqual(result["skipped"], "entry_waiting")
        self.assertTrue(result["pending"])
        pending = await self.storage.pending_by_signal("all-execute-wait")
        self.assertEqual(pending["status"], "WAITING_ENTRY")
        events = await self.storage._all(
            "SELECT event_type FROM events WHERE symbol=? ORDER BY id",
            ("BTCUSDT",),
        )
        self.assertIn("SHADOW_BYPASSED_ALL_EXECUTE", {x["event_type"] for x in events})
        self.assertIn("ALL_EXECUTE_WAITING_ENTRY", {x["event_type"] for x in events})
        self.assertFalse(await self.storage.by_signal("all-execute-wait"))

    async def test_flat_trade_waits_for_complete_exit_fills(self):
        trade = await self.make_trade()
        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "entry", "orderLinkId": "BDT1-ENTRY", "side": "Buy",
                "execPrice": "100", "execQty": "1", "execValue": "100",
                "execFee": "0.1", "execTime": 1,
            },
        )
        await self.storage.mark_flat_syncing(trade["id"], "TEST")
        self.assertFalse(await self.executor._finalize_flat_trade(trade))
        row = await self.storage._one("SELECT status FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["status"], "CLOSED_SYNCING")

        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "exit", "side": "Sell", "execPrice": "105",
                "execQty": "1", "execValue": "105", "execFee": "0.1",
                "execTime": 2, "closedSize": "1",
            },
        )
        refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertTrue(await self.executor._finalize_flat_trade(refreshed))
        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["status"], "CLOSED")
        self.assertAlmostEqual(row["gross_pnl_usdt"], 5.0)

    async def test_tp1_breakeven_retries_after_transient_failure(self):
        trade = await self.make_trade()
        await self.storage.set_tp_hit(trade["id"], 1)
        trade = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.bybit.fail_stop_once = True
        note = await self.executor._attempt_tp1_breakeven(
            trade, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("retry scheduled", note)
        failed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(failed["be_status"], "FAILED")

        async with self.storage._db() as db:
            await db.execute(
                "UPDATE trades SET be_last_attempt_at=0 WHERE id=?", (trade["id"],)
            )
            await db.commit()
        failed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        note = await self.executor._attempt_tp1_breakeven(
            failed, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("BREAKEVEN", note)
        applied = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(applied["be_status"], "APPLIED")
        self.assertEqual(applied["sl"], 100.0)

    async def test_close_does_not_mark_closed_when_flat_unconfirmed(self):
        trade = await self.make_trade()
        self.bybit.close_market = AsyncMock(return_value={"retCode": 0})
        self.executor._wait_flat = AsyncMock(return_value=False)
        result = await self.executor.close_trade("BTCUSDT", "TEST")
        self.assertFalse(result)
        row = await self.storage._one("SELECT status FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["status"], "RECOVERY_REQUIRED")

    async def test_management_rejects_stale_signal_before_sl_change(self):
        await self.make_trade()
        result = await self.executor.management(
            {
                "event_id": "event-1", "signal_id": "older-signal",
                "symbol": "BTCUSDT", "action": "MOVE_SL", "new_sl": 98,
            }
        )
        self.assertEqual(result["skipped"], "stale_signal_id")
        self.assertEqual(self.bybit.stop_calls, 0)

    async def test_global_entry_guard_serializes_different_symbols(self):
        first_inside = asyncio.Event()
        release_first = asyncio.Event()
        second_inside = asyncio.Event()

        async def first():
            async with self.executor.entry_guard("BTCUSDT"):
                first_inside.set()
                await release_first.wait()

        async def second():
            await first_inside.wait()
            async with self.executor.entry_guard("ETHUSDT"):
                second_inside.set()

        one = asyncio.create_task(first())
        two = asyncio.create_task(second())
        await first_inside.wait()
        await asyncio.sleep(0)
        self.assertFalse(second_inside.is_set())
        release_first.set()
        await asyncio.gather(one, two)
        self.assertTrue(second_inside.is_set())

    async def test_tp1_requires_full_planned_fill(self):
        trade = await self.make_trade()
        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "partial", "orderLinkId": "BDT1-TP1", "side": "Sell",
                "execPrice": "105", "execQty": "0.1", "execValue": "10.5",
                "execFee": "0.01", "execTime": 2, "closedSize": "0.1",
            },
        )
        await self.executor._reconcile_trade(trade)
        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["tp1_hit"], 0)

        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "remainder", "orderLinkId": "BDT1-TP1", "side": "Sell",
                "execPrice": "105", "execQty": "0.3", "execValue": "31.5",
                "execFee": "0.01", "execTime": 3, "closedSize": "0.3",
            },
        )
        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        await self.executor._reconcile_trade(row)
        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["tp1_hit"], 1)
        self.assertEqual(row["be_status"], "APPLIED")

    async def test_partial_tp2_does_not_move_stop(self):
        trade = await self.make_trade()
        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "tp2-partial", "orderLinkId": "BDT1-TP2", "side": "Sell",
                "execPrice": "110", "execQty": "0.1", "execValue": "11",
                "execFee": "0.01", "execTime": 2, "closedSize": "0.1",
            },
        )

        await self.executor._reconcile_trade(trade)

        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["tp2_hit"], 0)
        self.assertEqual(row["tp2_lock_status"], "NOT_DUE")
        self.assertEqual(row["sl"], 95.0)
        self.assertEqual(self.bybit.stop_calls, 0)

    async def test_full_tp2_moves_remaining_position_stop_to_tp1(self):
        trade = await self.make_trade()
        self.bybit.position_row["size"] = "0.3"
        self.bybit.ticker_price = 111.0
        for exec_id, link, price, qty in (
            ("tp1-full", "BDT1-TP1", "105", "0.4"),
            ("tp2-full", "BDT1-TP2", "110", "0.3"),
        ):
            await self.storage.add_fill(
                trade["id"],
                {
                    "execId": exec_id, "orderLinkId": link, "side": "Sell",
                    "execPrice": price, "execQty": qty,
                    "execValue": str(float(price) * float(qty)),
                    "execFee": "0.01", "execTime": 2, "closedSize": qty,
                },
            )

        await self.executor._reconcile_trade(trade)

        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(row["tp1_hit"], 1)
        self.assertEqual(row["tp2_hit"], 1)
        self.assertEqual(row["be_status"], "APPLIED")
        self.assertEqual(row["tp2_lock_status"], "APPLIED")
        self.assertEqual(row["tp2_lock_price"], 105.0)
        self.assertEqual(row["sl"], 105.0)
        self.assertEqual(self.bybit.stop, 105.0)
        events = await self.storage._all(
            "SELECT event_type FROM events WHERE trade_id=? ORDER BY id", (trade["id"],)
        )
        self.assertIn("TP2_SL_TO_TP1", {x["event_type"] for x in events})

    async def test_tp2_lock_never_loosens_a_stricter_stop(self):
        trade = await self.make_trade()
        await self.storage.set_tp_hit(trade["id"], 2)
        await self.storage.update_sl(trade["id"], 107.0, "test stricter stop")
        self.bybit.stop = 107.0
        self.bybit.ticker_price = 111.0
        trade = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        note = await self.executor._attempt_tp2_lock_to_tp1(
            trade, await self.bybit.position("BTCUSDT")
        )

        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertIn("already better", note)
        self.assertEqual(row["tp2_lock_status"], "NOT_NEEDED")
        self.assertEqual(row["sl"], 107.0)
        self.assertEqual(self.bybit.stop, 107.0)
        self.assertEqual(self.bybit.stop_calls, 0)

    async def test_tp2_lock_moves_short_stop_down_to_tp1(self):
        trade = await self.make_trade()
        async with self.storage._db() as db:
            await db.execute(
                """UPDATE trades
                   SET side='SHORT',sl=105,tp1=95,tp2=90,tp3=85,tp2_hit=1
                   WHERE id=?""",
                (trade["id"],),
            )
            await db.commit()
        self.bybit.stop = 105.0
        self.bybit.ticker_price = 89.0
        trade = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        note = await self.executor._attempt_tp2_lock_to_tp1(
            trade, await self.bybit.position("BTCUSDT")
        )

        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertIn("SL → **TP1**", note)
        self.assertEqual(row["tp2_lock_status"], "APPLIED")
        self.assertEqual(row["sl"], 95.0)
        self.assertEqual(self.bybit.stop, 95.0)

    async def test_tp2_lock_failed_attempt_is_retried_after_restart(self):
        trade = await self.make_trade()
        await self.storage.set_tp_hit(trade["id"], 2)
        self.bybit.ticker_price = 111.0
        self.bybit.fail_stop_once = True
        trade = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        note = await self.executor._attempt_tp2_lock_to_tp1(
            trade, await self.bybit.position("BTCUSDT")
        )
        self.assertIn("retry scheduled", note)
        failed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(failed["tp2_lock_status"], "FAILED")
        self.assertIn("transient", failed["tp2_lock_last_error"])

        async with self.storage._db() as db:
            await db.execute(
                "UPDATE trades SET tp2_lock_last_attempt_at=0 WHERE id=?", (trade["id"],)
            )
            await db.commit()
        restarted = DemoExecutor(cfg_stub(), self.bybit, self.storage, self.notifier)
        failed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        await restarted._reconcile_trade(failed)

        applied = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertEqual(applied["tp2_lock_status"], "APPLIED")
        self.assertIsNone(applied["tp2_lock_last_error"])
        self.assertEqual(applied["sl"], 105.0)
        self.assertEqual(self.bybit.stop, 105.0)

    async def test_management_event_is_applied_only_once(self):
        await self.make_trade()
        payload = {
            "event_id": "event-once", "signal_id": "sig-1",
            "symbol": "BTCUSDT", "action": "SIGNAL_CLOSED",
        }
        first = await self.executor.management(payload)
        second = await self.executor.management(payload)
        self.assertTrue(first["ignored_for_active_trade"])
        self.assertTrue(second["duplicate"])

    async def test_closed_trade_fill_history_is_backfilled(self):
        trade = await self.make_trade()
        now_ms = int(time.time() * 1000)
        await self.storage.add_fill(
            trade["id"],
            {
                "execId": "entry-history", "orderLinkId": "BDT1-ENTRY",
                "side": "Buy", "execPrice": "100", "execQty": "1",
                "execValue": "100", "execFee": "0.1", "execTime": now_ms,
            },
        )
        await self.storage.close_trade(trade["id"], "OLD_INCOMPLETE")
        self.bybit.execution_rows = [
            {
                "execId": "exit-history", "orderLinkId": "", "side": "Sell",
                "execPrice": "105", "execQty": "1", "execValue": "105",
                "execFee": "0.1", "execTime": now_ms + 1, "closedSize": "1",
            }
        ]
        self.assertEqual(await self.executor._backfill_incomplete_closed(), 1)
        row = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        self.assertAlmostEqual(row["gross_pnl_usdt"], 5.0)
