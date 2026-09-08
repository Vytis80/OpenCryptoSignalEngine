from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from models import ExecuteSignal
from smart_position import assess_position
from storage import Storage


def smart_signal():
    return ExecuteSignal.from_payload({
        "event":"EXECUTE","signal_id":"smart-block-exec","symbol":"BTCUSDT","side":"LONG",
        "entry":100,"entry_low":99,"entry_high":101,"sl":95,"tp1":105,"tp2":110,"tp3":115,
        "source_ts":time.time(),"smart_status":"SMART_BLOCK","smart_score":35,
        "smart_note":"counterfactual only","smart_setup":"BREAKOUT_RETEST","smart_regime":"RANGE",
    })


class SmartPositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.storage=Storage(Path(self.temp.name)/"smart.db")
        await self.storage.init()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_smart_block_is_metadata_not_execution_gate(self):
        signal=smart_signal()
        self.assertEqual(signal.smart_status,"SMART_BLOCK")
        trade_id=await self.storage.create_trade(signal,1,5,10,1,{"event":"EXECUTE"})
        row=await self.storage._one("SELECT * FROM trades WHERE id=?",(trade_id,))
        self.assertEqual(row["status"],"OPENING")
        self.assertEqual(row["smart_status"],"SMART_BLOCK")

    async def test_actual_position_observation_is_durable_and_non_executable(self):
        signal=smart_signal();trade_id=await self.storage.create_trade(signal,1,5,10,1,{})
        await self.storage.mark_opened(trade_id,100,1,5,"order","entry",("tp1","tp2","tp3"))
        async with self.storage._db() as db:
            await db.execute("UPDATE trades SET opened_at=? WHERE id=?",(time.time()-600,trade_id))
            await db.commit()
        trade=await self.storage._one("SELECT * FROM trades WHERE id=?",(trade_id,))
        position={"avgPrice":"100","markPrice":"97","size":"1"}
        assessment=assess_position(trade,position)
        self.assertEqual(assessment.action,"EXIT_CANDIDATE")
        self.assertFalse(hasattr(assessment,"new_sl"))
        self.assertFalse(hasattr(assessment,"close_order"))
        await self.storage.save_smart_position(assessment,60)
        restarted=Storage(self.storage.path);await restarted.init()
        saved=await restarted.smart_position_for_trade(trade_id)
        self.assertEqual(saved["action"],"EXIT_CANDIDATE")
        self.assertAlmostEqual(saved["current_r"],-.6)


if __name__=="__main__":
    unittest.main()
