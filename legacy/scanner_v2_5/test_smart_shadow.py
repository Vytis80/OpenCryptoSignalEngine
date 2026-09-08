import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from bridge_client import DemoBridgeClient
from config import Config
from models import ActiveSignal,Candle,TradeAnalysis
from smart_engine import assess_management,assess_signal
from storage import Storage


def candles(side="LONG", count=40):
    out=[];price=100.0
    for i in range(count):
        o=price;price += .10 if side=="LONG" else -.10
        out.append(Candle(i*60_000,o,max(o,price)+.04,min(o,price)-.04,price,100,10_000,True))
    return out


def analysis(**overrides):
    values=dict(
        inst_id="TESTUSDT",base="TEST",side="LONG",status="EXECUTE",score=88,quality="A",
        price=100,entry_low=99.8,entry_high=100.2,sl=98,tp1=102,tp2=104,tp3=106,
        rr_tp2=2,bias_1h="BULLISH",setup_15m="BULLISH / HH_HL",
        trigger_5m="BREAKOUT + RETEST",btc_context="BULLISH",eth_context="BULLISH",
        relative_strength=.40,spread_pct=.01,volume_ratio_5m=1.6,atr_5m=1,
        trigger_candle_ts=1_000_000,fresh=True,too_late=False,reasons=[],blocks=[],
        stop_pct=2,estimated_cost_r=.075,long_score=90,short_score=55,direction_margin=35,
        market_regime="TREND",regime_strength=80,trigger_level=99.9,atr_expansion=1.1,
        funding_rate=0,open_interest_value=1_000_000,oi_delta_pct=.5,
    )
    values.update(overrides)
    return TradeAnalysis(**values)


def test_smart_signal_is_nonblocking():
    cfg=Config();a=analysis();before=(a.status,a.entry_low,a.entry_high,a.sl,a.tp1,a.tp2,a.tp3)
    result=assess_signal(a,candles(),candles(),cfg)
    assert result.verdict=="SMART_PASS"
    assert (a.status,a.entry_low,a.entry_high,a.sl,a.tp1,a.tp2,a.tp3)==before

    weak=analysis(direction_margin=0,market_regime="RANGE",volume_ratio_5m=.6,
                  estimated_cost_r=.25,relative_strength=-.5,spread_pct=.19,
                  oi_delta_pct=-.5,funding_rate=.001)
    blocked=assess_signal(weak,candles("SHORT"),candles("SHORT"),cfg)
    assert blocked.verdict=="SMART_BLOCK"
    assert weak.status=="EXECUTE", "SMART_BLOCK must not suppress the scanner EXECUTE"

    payload=DemoBridgeClient.execute_payload(
        signal_id=1,symbol=a.inst_id,side=a.side,entry=a.price,entry_low=a.entry_low,
        entry_high=a.entry_high,sl=a.sl,tp1=a.tp1,tp2=a.tp2,tp3=a.tp3,
        smart_status=blocked.verdict,smart_score=blocked.score,
        smart_note="audit only",smart_setup=blocked.setup_family,smart_regime=blocked.regime,
    )
    assert payload["event"]=="EXECUTE" and payload["smart_status"]=="SMART_BLOCK"


def test_live_management_is_observation_only():
    now=time.time()
    s=ActiveSignal(1,"TESTUSDT","TEST","LONG","A",88,now-600,100,99.8,100.2,98,102,104,106,now+300)
    s.last_price=98.8;s.max_gain_pct=.4;s.smart_status="SMART_BLOCK";s.smart_score=35
    a=analysis(price=98.8,bias_1h="BEARISH",setup_15m="BEARISH / LH_LL",side="SHORT",score=90)
    result=assess_management(s,a,candles("SHORT",10))
    assert result.action=="EXIT_CANDIDATE"
    assert not hasattr(result,"new_sl") and not hasattr(result,"close_order")


async def test_smart_storage_is_restart_safe():
    with tempfile.TemporaryDirectory() as d:
        store=Storage(Path(d)/"smart.db");await store.init()
        a=analysis();sid=await store.create_signal(a,time.time()+900)
        smart=assess_signal(a,candles(),candles(),Config())
        await store.save_smart_signal(sid,smart)
        saved=await store.smart_for_signal(sid)
        assert saved["verdict"]=="SMART_PASS" and saved["model_version"]
        s=ActiveSignal(sid,"TESTUSDT","TEST","LONG","A",88,time.time()-600,100,99.8,100.2,98,102,104,106,time.time()+300)
        s.last_price=101;s.max_gain_pct=1
        managed=assess_management(s,a,candles())
        await store.save_smart_management(managed)
        restarted=Storage(store.path);await restarted.init()
        latest=await restarted.latest_smart_management(sid)
        assert latest and latest["action"]==managed.action


async def main():
    test_smart_signal_is_nonblocking()
    test_live_management_is_observation_only()
    await test_smart_storage_is_restart_safe()
    print("OK: SMART signal/management shadow is non-blocking, durable and restart-safe")


asyncio.run(main())
