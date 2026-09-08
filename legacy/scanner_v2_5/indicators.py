from statistics import mean
from models import Candle

def ema(vals,period):
    if not vals:return 0.0
    k=2/(period+1);x=vals[0]
    for v in vals[1:]:x=v*k+x*(1-k)
    return x

def rsi(vals,period=14):
    if len(vals)<period+1:return 50.0
    gains=[];loss=[]
    for a,b in zip(vals[-period-1:-1],vals[-period:]):
        d=b-a;gains.append(max(0,d));loss.append(max(0,-d))
    ag=sum(gains)/period;al=sum(loss)/period
    if al==0:return 100.0 if ag>0 else 50.0
    rs=ag/al
    return 100-(100/(1+rs))

def atr(candles,period=14):
    if len(candles)<2:return 0.0
    rows=candles[-period-1:]
    tr=[]
    for i in range(1,len(rows)):
        c=rows[i];pc=rows[i-1].c
        tr.append(max(c.h-c.l,abs(c.h-pc),abs(c.l-pc)))
    return mean(tr) if tr else 0.0

def volume_ratio(candles,lookback=20):
    if len(candles)<3:return 1.0
    cur=candles[-1].quote_vol or candles[-1].vol
    prev=[(x.quote_vol or x.vol) for x in candles[-lookback-1:-1] if (x.quote_vol or x.vol)>0]
    return cur/(mean(prev) if prev else cur or 1)

def structure(candles,n=6):
    if len(candles)<n+1:return "MIXED"
    x=candles[-n:]
    highs=[c.h for c in x];lows=[c.l for c in x]
    up=sum(highs[i]>highs[i-1] and lows[i]>lows[i-1] for i in range(1,len(x)))
    dn=sum(highs[i]<highs[i-1] and lows[i]<lows[i-1] for i in range(1,len(x)))
    if up>=3:return "HH_HL"
    if dn>=3:return "LH_LL"
    return "MIXED"

def support_resistance(candles,lookback=20):
    x=candles[-lookback-1:-1] if len(candles)>lookback else candles[:-1]
    if not x:return 0.0,0.0
    return min(c.l for c in x),max(c.h for c in x)

def close_position(c:Candle):
    rng=max(c.h-c.l,1e-12)
    return (c.c-c.l)/rng

def body_ratio(c:Candle):
    rng=max(c.h-c.l,1e-12)
    return abs(c.c-c.o)/rng
