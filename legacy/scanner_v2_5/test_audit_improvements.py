import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import aiosqlite

import scanner as scanner_module
from bridge_client import DemoBridgeClient
from config import Config
from enhancements import shadow_assess
from models import Candle
from scanner import TradeScanner
from storage import Storage


def candles(side):
    out=[]
    price=100.0
    for i in range(12):
        o=price
        price += .08 if side=="LONG" else -.08
        out.append(Candle(i*60_000,o,max(o,price)+.05,min(o,price)-.05,price,100,10_000,True))
    return out


def analysis(side,stop_pct):
    bearish=side=="SHORT"
    return SimpleNamespace(
        inst_id="TESTUSDT",side=side,price=100.0,
        sl=100.0-stop_pct if side=="LONG" else 100.0+stop_pct,
        atr_5m=2.0,btc_context="BEARISH" if bearish else "NEUTRAL",
        eth_context="BEARISH" if bearish else "NEUTRAL",
        relative_strength=-.35 if bearish else .10,
        volume_ratio_5m=1.25,
    )


def test_shadow_cost_and_short_gate():
    cfg=Config()
    narrow=analysis("LONG",1.0)
    original=(narrow.sl,narrow.price)
    blocked=shadow_assess(narrow,candles("LONG"),candles("LONG"),cfg)
    assert blocked.status=="WOULD_BLOCK" and blocked.estimated_cost_r>.12
    assert (narrow.sl,narrow.price)==original

    wide=analysis("LONG",1.5)
    allowed=shadow_assess(wide,candles("LONG"),candles("LONG"),cfg)
    assert allowed.status=="PASS" and abs(allowed.estimated_cost_r-.10)<1e-9

    short=shadow_assess(analysis("SHORT",1.5),candles("SHORT"),candles("SHORT"),cfg)
    assert short.status=="WOULD_BLOCK"
    assert any("manual Demo approval" in reason for reason in short.reasons)


async def test_outbox_and_lifecycle_stats():
    with tempfile.TemporaryDirectory() as d:
        store=Storage(Path(d)/"audit.db")
        await store.init()
        payload=DemoBridgeClient.management_payload(
            event_id="e1",signal_id="s1",symbol="TESTUSDT",action="PROTECT",source_ts=123.0
        )
        await store.enqueue_bridge("e1","MANAGEMENT",payload)
        await store.enqueue_bridge("e1","MANAGEMENT",payload)
        assert (await store.bridge_outbox_counts()).get("PENDING")==1
        rows=await store.pending_bridge()
        assert len(rows)==1 and rows[0]["event_id"]=="e1"
        await store.mark_bridge_retry("e1","temporary")
        assert (await store.bridge_outbox_counts()).get("RETRY")==1
        await store.mark_bridge_delivered("e1")
        assert (await store.bridge_outbox_counts()).get("DELIVERED")==1

        now=time.time()
        async with aiosqlite.connect(store.path) as db:
            base=("TESTUSDT","TEST","LONG","A",85,now,1,100,100,100,99,101,102,103,now+900,"CLOSED","[]","[]","{}","TEST",1.5,.15)
            await db.execute("""INSERT INTO signals(
              inst_id,base,side,quality,score,confirmed_at,trigger_candle_ts,
              entry,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,status,
              reasons,blocks,context,setup_type,stop_pct,estimated_cost_r,
              tp1_hit,tp2_hit,tp3_hit,close_reason,close_price)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,1,'TP3',103)""",base)
            loss=("LOSSUSDT","LOSS","LONG","B",82,now,2,100,100,100,99,101,102,103,now+900,"CLOSED","[]","[]","{}","TEST",1.0,.15)
            await db.execute("""INSERT INTO signals(
              inst_id,base,side,quality,score,confirmed_at,trigger_candle_ts,
              entry,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,status,
              reasons,blocks,context,setup_type,stop_pct,estimated_cost_r,
              tp1_hit,tp2_hit,tp3_hit,close_reason,close_price)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,'SL',99)""",loss)
            await db.commit()
        stats=await store.report_stats(now-1)
        assert abs(stats["avg_planned_r"]-.45)<1e-9
        assert abs(stats["avg_estimated_net_r"]-.30)<1e-9
        assert abs(stats["planned_profit_factor"]-1.9)<1e-9


async def test_close_is_single_flight():
    class FakeStorage:
        def __init__(self):
            self.calls=0
            self.started=asyncio.Event()
            self.release=asyncio.Event()
        async def close_signal(self,*_):
            self.calls+=1
            self.started.set()
            await self.release.wait()

    s=SimpleNamespace(inst_id="TESTUSDT",id=7,status="ACTIVE")
    scanner=TradeScanner.__new__(TradeScanner)
    scanner.active={s.inst_id:s};scanner.closing=set();scanner.management={}
    scanner.demo_bridge=None;scanner.storage=FakeStorage();scanner.session=None;scanner.cfg=SimpleNamespace()
    alerts=[]
    original_alert=scanner_module.update_alert
    async def fake_alert(*args,**kwargs):
        alerts.append((args,kwargs))
    scanner_module.update_alert=fake_alert
    try:
        first=asyncio.create_task(scanner._close_active(s,"SL",99))
        await scanner.storage.started.wait()
        await scanner._close_active(s,"SL",99)
        scanner.storage.release.set()
        await first
    finally:
        scanner_module.update_alert=original_alert
    assert scanner.storage.calls==1 and len(alerts)==1 and not scanner.active


async def main():
    test_shadow_cost_and_short_gate()
    await test_outbox_and_lifecycle_stats()
    await test_close_is_single_flight()
    print("OK: cost/manual-SHORT SHADOW, durable outbox, lifecycle R and single-flight close")


asyncio.run(main())
