from types import SimpleNamespace

from models import Candle,MarketTicker,TimeframeView
from strategy import analyze,analyze_v25


def candles(count,step=.02,span=.32,end=100.0,minute_ms=300_000):
    start=end-step*(count-1)
    rows=[]
    for i in range(count):
        close=start+step*i
        open_=close-step*.55
        rows.append(Candle(
            i*minute_ms,open_,close+span*.45,open_-span*.55,close,
            100+i,10_000+i*100,True
        ))
    return rows


def long_fixture():
    c4=candles(90,step=.06,span=.75,minute_ms=14_400_000)
    c1h=candles(90,step=.04,span=.55,minute_ms=3_600_000)
    c15=candles(100,step=.025,span=.40,minute_ms=900_000)
    c5=candles(120,step=.02,span=.32,minute_ms=300_000)
    level=max(x.h for x in c5[-26:-2])
    prev=c5[-2]
    prev.o=level*1.00045;prev.c=level*1.0010
    prev.h=prev.c+.08;prev.l=prev.o-.05;prev.quote_vol=35_000
    cur=c5[-1]
    cur.o=level*1.00025;cur.l=level*.9995
    cur.c=level*1.0012;cur.h=cur.c+.025;cur.quote_vol=40_000
    c1m=candles(60,step=.015,span=.12,end=cur.c,minute_ms=60_000)
    c1m[-1].quote_vol=30_000
    ticker=MarketTicker("TESTUSDT","TEST",cur.c,cur.c*.98,cur.c*1.02,cur.c*.97,
                        50_000_000,cur.c*.9999,cur.c*1.0001,1_000_000)
    ctx=TimeframeView(trend="BULLISH",return_pct=0.0)
    cfg=SimpleNamespace(
        execute_score=82,potential_score=70,min_rr_tp2=1.8,
        volume_ratio_trigger=1.15,max_spread_pct=.20,max_chase_atr=1.30,
        min_micro_confirmations=2,min_atr5_pct=.06,max_atr5_pct=2.50,
        max_5m_range_atr=2.30,min_stop_atr=.65,max_stop_atr=2.00,
        min_stop_pct=.15,max_stop_pct=4.0,context_hard_block=True,
    )
    return ticker,c4,c1h,c15,c5,c1m,(ctx,ctx),(ctx,ctx),cfg


def run_v26(parts):
    ticker,c4,c1h,c15,c5,c1m,btc,eth,cfg=parts
    return analyze("TESTUSDT",ticker,c4,c1h,c15,c5,c1m,btc,eth,cfg)


clean=long_fixture()
a=run_v26(clean)
assert a is not None
assert a.core_version=="2.6"
assert a.status=="EXECUTE",(a.score,a.blocks,a.trigger_5m,a.micro_confirmations)
assert a.regime_4h=="BULLISH"
assert a.micro_confirmations>=2
assert a.stop_atr<=clean[-1].max_stop_atr
assert a.stop_pct<=clean[-1].max_stop_pct
assert abs((a.tp1-a.price)-abs(a.price-a.sl))<1e-9
assert abs((a.tp2-a.price)-2*abs(a.price-a.sl))<1e-9
assert abs((a.tp3-a.price)-3*abs(a.price-a.sl))<1e-9

# A BTR-like distant wick may not produce an impractically wide structural stop.
wide=long_fixture()
wide[4][-8].l=wide[4][-1].c*.90
b=run_v26(wide)
assert b.status!="EXECUTE"
assert any("structural SL rejected" in x for x in b.blocks),b.blocks

# Strong higher-timeframe score cannot compensate for missing 1M timing.
no_micro=long_fixture()
last=no_micro[5][-8:]
for i,x in enumerate(last):
    x.o=x.c+.08
    x.c=x.o-.05-.01*i
    x.h=x.o+.02
    x.l=x.c-.02
c=run_v26(no_micro)
assert c.status!="EXECUTE"
assert c.micro_confirmations<no_micro[-1].min_micro_confirmations
assert any("1m confirmation missing" in x for x in c.blocks),c.blocks

# The frozen baseline remains callable for objective V2.5/V2.6 comparison.
ticker,c4,c1h,c15,c5,c1m,btc,eth,cfg=long_fixture()
old=analyze_v25("TESTUSDT",ticker,c1h,c15,c5,btc,eth,cfg)
assert old is not None and old.core_version=="2.5"

print("OK: V2.6 hard gates, honest SL rejection, exact 1R/2R/3R, V2.5 baseline")
