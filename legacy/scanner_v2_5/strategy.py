from statistics import mean
from models import TimeframeView,TradeAnalysis
from indicators import ema,rsi,atr,volume_ratio,structure,support_resistance,close_position,body_ratio

def pct(a,b):return (a/b-1)*100 if b else 0

def tf_view(candles,fast,slow):
    if len(candles)<max(slow+5,30):return TimeframeView()
    closes=[x.c for x in candles]
    ef=ema(closes,fast);es=ema(closes,slow);rv=rsi(closes);av=atr(candles)
    st=structure(candles);sup,res=support_resistance(candles,20)
    last=closes[-1];ret=pct(last,closes[-5]) if len(closes)>=5 else 0
    if ef>es and last>ef:trend="BULLISH"
    elif ef<es and last<ef:trend="BEARISH"
    else:trend="NEUTRAL"
    return TimeframeView(trend,ef,es,rv,av,volume_ratio(candles),ret,st,sup,res)

def context_direction(h1,m15):
    if h1.trend=="BULLISH" and m15.trend!="BEARISH":return "BULLISH"
    if h1.trend=="BEARISH" and m15.trend!="BULLISH":return "BEARISH"
    return "NEUTRAL"

def _ema_slope_atr(candles,period,lookback,av):
    if av<=0 or len(candles)<period+lookback+2:return 0.0
    closes=[x.c for x in candles]
    return (ema(closes,period)-ema(closes[:-lookback],period))/av

def _atr_expansion(candles):
    if len(candles)<30:return 1.0
    fast=atr(candles,6);slow=atr(candles,24)
    return fast/slow if slow>0 else 1.0

def _market_regime(v1,v15,v5,c1h,c15,c5):
    sep1=abs(v1.ema_fast-v1.ema_slow)/v1.atr if v1.atr>0 else 0.0
    sep15=abs(v15.ema_fast-v15.ema_slow)/v15.atr if v15.atr>0 else 0.0
    slope1=abs(_ema_slope_atr(c1h,20,3,v1.atr))
    slope15=abs(_ema_slope_atr(c15,9,3,v15.atr))
    expansion=_atr_expansion(c5)
    aligned=v1.trend==v15.trend and v1.trend in {"BULLISH","BEARISH"}
    strength=min(100.0,18*sep1+16*sep15+22*slope1+18*slope15)
    if expansion>=1.35 and v5.volume_ratio>=1.15:return "VOLATILITY_EXPANSION",max(strength,65.0),expansion
    if aligned and sep1>=.18 and sep15>=.16 and (slope1>=.10 or slope15>=.14):return "TREND",max(strength,60.0),expansion
    if sep1<.16 and sep15<.14 and slope1<.10 and slope15<.12:return "RANGE",min(strength,45.0),expansion
    return "TRANSITION",strength,expansion

def _trigger_long(c5,v5):
    if len(c5)<25:return False,"NONE",0
    cur,prev=c5[-1],c5[-2]
    prior=c5[-22:-2];level=max(x.h for x in prior)
    prev_break=prev.c>level*1.0005
    retest=prev_break and cur.l<=level*1.003 and cur.c>level and close_position(cur)>=.55
    reaction=(cur.l<=max(v5.ema_fast,v5.ema_slow)*1.003 and cur.c>cur.o and close_position(cur)>=.65 and body_ratio(cur)>=.35)
    reclaim=(prev.c<max(v5.ema_fast,v5.ema_slow) and cur.c>max(v5.ema_fast,v5.ema_slow) and cur.c>cur.o and close_position(cur)>=.65)
    if retest:return True,"BREAKOUT + RETEST",level
    if reclaim:return True,"EMA RECLAIM + REACTION",max(v5.ema_fast,v5.ema_slow)
    if reaction:return True,"PULLBACK REACTION",max(v5.ema_fast,v5.ema_slow)
    return False,"WAITING FOR RETEST/REACTION",level

def _trigger_short(c5,v5):
    if len(c5)<25:return False,"NONE",0
    cur,prev=c5[-1],c5[-2]
    prior=c5[-22:-2];level=min(x.l for x in prior)
    prev_break=prev.c<level*.9995
    retest=prev_break and cur.h>=level*.997 and cur.c<level and close_position(cur)<=.45
    reaction=(cur.h>=min(v5.ema_fast,v5.ema_slow)*.997 and cur.c<cur.o and close_position(cur)<=.35 and body_ratio(cur)>=.35)
    reclaim=(prev.c>min(v5.ema_fast,v5.ema_slow) and cur.c<min(v5.ema_fast,v5.ema_slow) and cur.c<cur.o and close_position(cur)<=.35)
    if retest:return True,"BREAKDOWN + RETEST",level
    if reclaim:return True,"EMA REJECT + REACTION",min(v5.ema_fast,v5.ema_slow)
    if reaction:return True,"PULLBACK REACTION",min(v5.ema_fast,v5.ema_slow)
    return False,"WAITING FOR RETEST/REACTION",level

def analyze(inst_id,ticker,c1h,c15,c5,btc_views,eth_views,cfg):
    base=ticker.base;price=ticker.last
    v1=tf_view(c1h,20,50);v15=tf_view(c15,9,21);v5=tf_view(c5,9,21)
    if not c5 or v5.atr<=0:return None

    btc_h,btc_15=btc_views;eth_h,eth_15=eth_views
    btc_ctx=context_direction(btc_h,btc_15);eth_ctx=context_direction(eth_h,eth_15)
    btc_ret=btc_h.return_pct
    coin_ret=v1.return_pct
    rs=coin_ret-btc_ret
    regime,regime_strength,atr_expansion=_market_regime(v1,v15,v5,c1h,c15,c5)

    longs=0;shorts=0;lr=[];sr=[];lb=[];sb=[]

    # 1h bias: 36 points
    if v1.ema_fast>v1.ema_slow:longs+=14;lr.append("1h EMA20 > EMA50")
    if v1.ema_fast<v1.ema_slow:shorts+=14;sr.append("1h EMA20 < EMA50")
    if c1h[-1].c>v1.ema_fast:longs+=7
    if c1h[-1].c<v1.ema_fast:shorts+=7
    if v1.structure=="HH_HL":longs+=9;lr.append("1h HH/HL structure")
    if v1.structure=="LH_LL":shorts+=9;sr.append("1h LH/LL structure")
    if 52<=v1.rsi<=70:longs+=6
    if 30<=v1.rsi<=48:shorts+=6

    # 15m setup: 28 points
    if v15.ema_fast>v15.ema_slow:longs+=8;lr.append("15m trend aligned")
    if v15.ema_fast<v15.ema_slow:shorts+=8;sr.append("15m trend aligned")
    if v15.structure=="HH_HL":longs+=6
    if v15.structure=="LH_LL":shorts+=6
    if c15[-1].c>v15.ema_fast and v15.rsi>=50:longs+=6
    if c15[-1].c<v15.ema_fast and v15.rsi<=50:shorts+=6
    if v15.volume_ratio>=1.1:
        if c15[-1].c>=c15[-1].o:longs+=4
        else:shorts+=4
    # price location around 15m trend rather than chasing extremes
    if v15.atr>0:
        if abs(price-v15.ema_fast)/v15.atr<=1.2:longs+=4;shorts+=4

    # 5m trigger: 24 points, hard requirement for EXECUTE
    ltrig,lname,llevel=_trigger_long(c5,v5)
    strig,sname,slevel=_trigger_short(c5,v5)
    if ltrig:longs+=18;lr.append("full 5m close + "+lname.lower())
    else:lb.append(lname)
    if strig:shorts+=18;sr.append("full 5m close + "+sname.lower())
    else:sb.append(sname)
    if v5.volume_ratio>=cfg.volume_ratio_trigger:
        if c5[-1].c>c5[-1].o:longs+=6;lr.append(f"5m volume {v5.volume_ratio:.2f}×")
        elif c5[-1].c<c5[-1].o:shorts+=6;sr.append(f"5m volume {v5.volume_ratio:.2f}×")

    # Context / relative strength: up to 12
    if btc_ctx=="BULLISH":longs+=4
    elif btc_ctx=="BEARISH":shorts+=4
    if eth_ctx=="BULLISH":longs+=3
    elif eth_ctx=="BEARISH":shorts+=3
    if rs>=.25:longs+=5;lr.append(f"relative strength vs BTC {rs:+.2f}%")
    elif rs<=-.25:shorts+=5;sr.append(f"relative weakness vs BTC {rs:+.2f}%")

    # Decide directional candidate before risk filters
    if longs>=shorts:
        side="LONG";raw=longs;reasons=lr;blocks=lb;trigger=ltrig;trigger_name=lname;level=llevel
    else:
        side="SHORT";raw=shorts;reasons=sr;blocks=sb;trigger=strig;trigger_name=sname;level=slevel

    # Normalize approximately to 100.
    score=min(100.0,raw/100*100)

    # Hard bias alignment
    bias_ok=(side=="LONG" and v1.trend=="BULLISH") or (side=="SHORT" and v1.trend=="BEARISH")
    if not bias_ok:
        blocks.append("1h bias nėra pakankamai švarus");score-=10

    # Context hard opposition
    context_opposes=(side=="LONG" and btc_ctx=="BEARISH" and eth_ctx=="BEARISH") or (side=="SHORT" and btc_ctx=="BULLISH" and eth_ctx=="BULLISH")
    if context_opposes:
        blocks.append("BTC + ETH context opposes trade")
        score-=12

    # Spread
    if ticker.spread_pct>cfg.max_spread_pct:
        blocks.append(f"spread per platus ({ticker.spread_pct:.3f}%)");score-=10

    # Anti-chase
    atr5=v5.atr
    ema_anchor=v5.ema_fast
    chase_atr=abs(price-ema_anchor)/atr5 if atr5 else 99
    too_late=chase_atr>cfg.max_chase_atr
    if too_late:
        blocks.append(f"TOO LATE / chase risk ({chase_atr:.2f} ATR nuo 5m EMA)")
        score-=15

    # Entry/SL/targets from ATR + recent structure.
    # R:R is not assumed: it is constrained by the nearest known 15m obstacle.
    entry_low=price-.12*atr5;entry_high=price+.12*atr5
    recent=c5[-8:]
    if side=="LONG":
        swing=min(x.l for x in recent)
        sl=min(price-1.05*atr5,swing-.12*atr5)
        risk=price-sl
        ideal_tp1=price+risk;ideal_tp2=price+2*risk;ideal_tp3=price+3*risk
        obstacle=v15.resistance if v15.resistance>price else 0.0
        rr_space=(obstacle-price)/risk if risk>0 and obstacle>price else 3.0
        if obstacle>price:
            # Do not place targets directly into visible resistance.
            safe_obstacle=price+(obstacle-price)*0.92
            tp1=min(ideal_tp1,safe_obstacle) if rr_space<1.15 else ideal_tp1
            tp2=min(ideal_tp2,safe_obstacle) if rr_space<2.15 else ideal_tp2
            tp3=min(ideal_tp3,safe_obstacle) if rr_space<3.15 else ideal_tp3
        else:
            tp1,tp2,tp3=ideal_tp1,ideal_tp2,ideal_tp3
        if rr_space<cfg.min_rr_tp2:
            blocks.append(f"per mažai erdvės iki 15m resistance ({rr_space:.2f}R)")
            score-=12
    else:
        swing=max(x.h for x in recent)
        sl=max(price+1.05*atr5,swing+.12*atr5)
        risk=sl-price
        ideal_tp1=price-risk;ideal_tp2=price-2*risk;ideal_tp3=price-3*risk
        obstacle=v15.support if v15.support and v15.support<price else 0.0
        rr_space=(price-obstacle)/risk if risk>0 and obstacle>0 else 3.0
        if obstacle>0:
            safe_obstacle=price-(price-obstacle)*0.92
            tp1=max(ideal_tp1,safe_obstacle) if rr_space<1.15 else ideal_tp1
            tp2=max(ideal_tp2,safe_obstacle) if rr_space<2.15 else ideal_tp2
            tp3=max(ideal_tp3,safe_obstacle) if rr_space<3.15 else ideal_tp3
        else:
            tp1,tp2,tp3=ideal_tp1,ideal_tp2,ideal_tp3
        if rr_space<cfg.min_rr_tp2:
            blocks.append(f"per mažai erdvės iki 15m support ({rr_space:.2f}R)")
            score-=12

    if risk>0:
        rr=((tp2-price)/risk) if side=="LONG" else ((price-tp2)/risk)
    else:
        rr=0
    score=max(0,min(100,score))
    fresh=not too_late

    execute=(score>=cfg.execute_score and trigger and bias_ok and fresh and
             ticker.spread_pct<=cfg.max_spread_pct and rr>=cfg.min_rr_tp2 and
             not (cfg.context_hard_block and context_opposes))
    if execute:
        status="EXECUTE"
    elif score>=cfg.potential_score:
        status="POTENTIAL"
    else:
        status="WAIT"

    quality="A+" if score>=92 else "A" if score>=86 else "B+" if score>=cfg.potential_score else "C"
    return TradeAnalysis(
        inst_id,base,side,status,score,quality,price,entry_low,entry_high,sl,tp1,tp2,tp3,rr,
        v1.trend,v15.trend+" / "+v15.structure,trigger_name,btc_ctx,eth_ctx,rs,
        ticker.spread_pct,v5.volume_ratio,atr5,c5[-1].ts,fresh,too_late,reasons,blocks,
        trigger_close=c5[-1].c,
        stop_pct=(risk/price*100 if price>0 else 0.0),
        long_score=float(longs),short_score=float(shorts),direction_margin=float(abs(longs-shorts)),
        market_regime=regime,regime_strength=regime_strength,trigger_level=float(level or 0),
        ema_distance_atr=chase_atr,atr_expansion=atr_expansion,
        funding_rate=float(getattr(ticker,"funding_rate",0) or 0),
        open_interest_value=float(getattr(ticker,"open_interest_value",0) or 0),
    )
