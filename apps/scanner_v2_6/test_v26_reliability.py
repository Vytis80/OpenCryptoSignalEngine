import asyncio
import time
from dataclasses import replace

from config import Config
from models import ActiveSignal,MarketTicker,TradeAnalysis
from scanner import TradeScanner


def ticker(symbol,n):
    return MarketTicker(symbol,symbol[:-4],100+n,100,110,90,10_000_000+n,99,101,time.time())


def test_fair_rotation():
    cfg=replace(Config(),deep_candidates_per_scan=4,rotating_candidates=2,
                core_symbols="BTC",min_24h_quote_volume=0,max_deep_scan_age_sec=360)
    scanner=TradeScanner(cfg)
    symbols=[f"C{n}USDT" for n in range(9)]+["BTCUSDT"]
    tickers={symbol:ticker(symbol,n) for n,symbol in enumerate(symbols)}
    scanner.live={symbol:symbol[:-4] for symbol in symbols}
    visited=set()
    for cycle in range(5):
        picked,eligible=scanner.choose_candidates(tickers)
        assert len(picked)==4
        assert eligible==10
        visited.update(picked)
        stamp=time.time()+cycle
        for symbol in picked:scanner.last_deep_scan_by_iid[symbol]=stamp
    assert visited==set(symbols),f"fair rotation missed: {set(symbols)-visited}"
    assert scanner.coverage_health(time.time()+5)["ok"]


async def test_post_tp_invalidation_and_stale_freeze():
    cfg=Config();scanner=TradeScanner(cfg);now=time.time()
    signal=ActiveSignal(1,"BTRUSDT","BTR","LONG","A",86,now-300,100,99.5,100.5,
                        98,102,104,106,now+600,tp1_hit=True,last_price=102,
                        last_checked_at=now,last_price_at=now,last_context_at=now)
    scanner.active[signal.inst_id]=signal
    analysis=TradeAnalysis("BTRUSDT","BTR","SHORT","EXECUTE",80,"A",101,100.5,101.5,
                           103,99,97,95,2,"BEARISH","BEARISH / LL_LH","BREAKDOWN",
                           "BEARISH","NEUTRAL",0,0.01,1.3,1,123,True,False,[],[])
    calls=[]
    async def close(*args,**kwargs):calls.append((args,kwargs))
    scanner._close_active=close
    await scanner.maybe_invalidate(analysis)
    assert len(calls)==1 and calls[0][0][1]=="INVALIDATED"
    assert "remaining position" in calls[0][0][4]

    calls.clear();signal.last_price_at=now-999;signal.last_context_at=now-999
    await scanner.maybe_invalidate(analysis)
    assert not calls,"stale data must freeze invalidation"


def test_cost_is_analytics_only():
    cfg=Config();scanner=TradeScanner(cfg);now=time.time()
    signal=ActiveSignal(2,"XUSDT","X","LONG","A",84,now,100,99,101,98,102,104,106,now+600)
    net,cost_r,cost_pct=scanner.cost_estimate_r(signal,1.0)
    assert abs(cost_pct-0.13)<1e-9
    assert abs(cost_r-0.065)<1e-9
    assert abs(net-0.935)<1e-9
    assert (signal.entry,signal.sl,signal.tp1,signal.tp2,signal.tp3)==(100,98,102,104,106)


test_fair_rotation()
asyncio.run(test_post_tp_invalidation_and_stale_freeze())
test_cost_is_analytics_only()
print("OK: V2.6 fair rotation, post-TP invalidation, stale freeze and cost sidecar")
