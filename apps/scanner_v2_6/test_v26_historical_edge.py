import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from storage import Storage


def analysis(price=100.0):
    return SimpleNamespace(
        inst_id="TESTUSDT",base="TEST",side="LONG",quality="A",score=90,
        trigger_candle_ts=123,price=price,entry_low=99.9,entry_high=100.1,
        sl=99.0,tp1=101.0,tp2=102.0,tp3=103.0,
        reasons=["clean"],blocks=[],btc_context="BULLISH",eth_context="BULLISH",
        relative_strength=.5,trigger_5m="BREAKOUT + RETEST",core_version="2.6",
        regime_4h="BULLISH",micro_confirmations=3,stop_atr=1.2,stop_pct=1.0,
        obstacle_rr=3.0,
    )


async def main():
    with tempfile.TemporaryDirectory() as td:
        s=Storage(Path(td)/"edge.db")
        await s.init()
        ids=[]
        for _ in range(3):
            ids.append(await s.create_signal(analysis(),time.time()+900))
        await s.close_signal(ids[0],"SL",99.0)
        for n in (1,2,3):await s.mark_tp(ids[1],n)
        await s.close_signal(ids[1],"TP3",103.0)
        for n in (1,2):await s.mark_tp(ids[2],n)
        await s.close_signal(ids[2],"INVALIDATED",101.5)

        r=await s.setup_edge(time.time()-60,"BREAKOUT + RETEST","LONG",.13)
        assert r["n"]==3,r
        assert r["avg_net_r"]>0,r
        assert abs(r["tp2_rate"]-2/3)<1e-9,r
        assert abs(r["full_sl_rate"]-1/3)<1e-9,r
    print("OK: V2.6 setup/side-specific historical net edge and create schema")


asyncio.run(main())
