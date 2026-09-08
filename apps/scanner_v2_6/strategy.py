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

def analyze_v25(inst_id,ticker,c1h,c15,c5,btc_views,eth_views,cfg):
    base=ticker.base;price=ticker.last
    v1=tf_view(c1h,20,50);v15=tf_view(c15,9,21);v5=tf_view(c5,9,21)
    if not c5 or v5.atr<=0:return None

    btc_h,btc_15=btc_views;eth_h,eth_15=eth_views
    btc_ctx=context_direction(btc_h,btc_15);eth_ctx=context_direction(eth_h,eth_15)
    btc_ret=btc_h.return_pct
    coin_ret=v1.return_pct
    rs=coin_ret-btc_ret

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
        ticker.spread_pct,v5.volume_ratio,atr5,c5[-1].ts,fresh,too_late,reasons,blocks
    )


def _v26_trigger_long(c5,v5):
    if len(c5)<30:return False,"NONE",0.0
    cur,prev=c5[-1],c5[-2]
    prior=c5[-26:-2]
    level=max(x.h for x in prior)
    breakout=prev.c>level*1.00035
    retest=breakout and cur.l<=level*1.0020 and cur.c>level and close_position(cur)>=.58
    anchor=max(v5.ema_fast,v5.ema_slow)
    reclaim=(prev.c<anchor and cur.c>anchor and cur.c>cur.o and close_position(cur)>=.65)
    reaction=(cur.l<=anchor*1.0018 and cur.c>cur.o and close_position(cur)>=.66 and body_ratio(cur)>=.38)
    sweep_level=min(x.l for x in c5[-8:-1])
    sweep=(cur.l<sweep_level*.9995 and cur.c>sweep_level and cur.c>cur.o and
           close_position(cur)>=.68 and body_ratio(cur)>=.30)
    if retest:return True,"BREAKOUT + RETEST",level
    if sweep:return True,"LIQUIDITY SWEEP + RECLAIM",sweep_level
    if reclaim:return True,"EMA RECLAIM + REACTION",anchor
    if reaction:return True,"PULLBACK REACTION",anchor
    return False,"WAITING FOR CONFIRMED 5M RETEST/REACTION",level


def _v26_trigger_short(c5,v5):
    if len(c5)<30:return False,"NONE",0.0
    cur,prev=c5[-1],c5[-2]
    prior=c5[-26:-2]
    level=min(x.l for x in prior)
    breakdown=prev.c<level*.99965
    retest=breakdown and cur.h>=level*.9980 and cur.c<level and close_position(cur)<=.42
    anchor=min(v5.ema_fast,v5.ema_slow)
    reject=(prev.c>anchor and cur.c<anchor and cur.c<cur.o and close_position(cur)<=.35)
    reaction=(cur.h>=anchor*.9982 and cur.c<cur.o and close_position(cur)<=.34 and body_ratio(cur)>=.38)
    sweep_level=max(x.h for x in c5[-8:-1])
    sweep=(cur.h>sweep_level*1.0005 and cur.c<sweep_level and cur.c<cur.o and
           close_position(cur)<=.32 and body_ratio(cur)>=.30)
    if retest:return True,"BREAKDOWN + RETEST",level
    if sweep:return True,"LIQUIDITY SWEEP + REJECT",sweep_level
    if reject:return True,"EMA REJECT + REACTION",anchor
    if reaction:return True,"PULLBACK REACTION",anchor
    return False,"WAITING FOR CONFIRMED 5M RETEST/REACTION",level


def _micro_confirmations(c1m,side):
    if len(c1m)<25:return 0,"NO 1M DATA",[]
    v1=tf_view(c1m,9,21)
    cur=c1m[-1]
    recent=c1m[-3:]
    hits=0;reasons=[]
    if side=="LONG":
        if cur.c>cur.o and close_position(cur)>=.58:
            hits+=1;reasons.append("1m bullish close")
        if v1.ema_fast>v1.ema_slow and cur.c>v1.ema_fast:
            hits+=1;reasons.append("1m EMA momentum")
        if sum(x.c>x.o for x in recent)>=2 and recent[-1].c>recent[0].o:
            hits+=1;reasons.append("1m sequence aligned")
        if v1.volume_ratio>=1.05 and cur.c>cur.o:
            hits+=1;reasons.append(f"1m volume {v1.volume_ratio:.2f}x")
    else:
        if cur.c<cur.o and close_position(cur)<=.42:
            hits+=1;reasons.append("1m bearish close")
        if v1.ema_fast<v1.ema_slow and cur.c<v1.ema_fast:
            hits+=1;reasons.append("1m EMA momentum")
        if sum(x.c<x.o for x in recent)>=2 and recent[-1].c<recent[0].o:
            hits+=1;reasons.append("1m sequence aligned")
        if v1.volume_ratio>=1.05 and cur.c<cur.o:
            hits+=1;reasons.append(f"1m volume {v1.volume_ratio:.2f}x")
    text=", ".join(reasons[:3]) if reasons else "MICRO NOT CONFIRMED"
    return hits,text,reasons


def _opposite_rejection(candle,side):
    body=max(abs(candle.c-candle.o),(candle.h-candle.l)*.08,1e-12)
    upper=max(0.0,candle.h-max(candle.o,candle.c))
    lower=max(0.0,min(candle.o,candle.c)-candle.l)
    if side=="LONG":return upper/body>1.8 and close_position(candle)<.72
    return lower/body>1.8 and close_position(candle)>.28


def analyze(inst_id,ticker,c4h,c1h,c15,c5,c1m,btc_views,eth_views,cfg):
    """V2.6 core: category score plus non-compensable execution gates."""
    base=ticker.base;price=ticker.last
    v4=tf_view(c4h,20,50);v1=tf_view(c1h,20,50)
    v15=tf_view(c15,9,21);v5=tf_view(c5,9,21)
    if min(len(c4h),len(c1h),len(c15),len(c5),len(c1m))<25 or v5.atr<=0:return None

    btc_h,btc_15=btc_views;eth_h,eth_15=eth_views
    btc_ctx=context_direction(btc_h,btc_15);eth_ctx=context_direction(eth_h,eth_15)
    rs=v1.return_pct-btc_h.return_pct
    long=0.0;short=0.0;lr=[];sr=[];lb=[];sb=[]

    # 4H market regime — 15 points.
    if v4.ema_fast>v4.ema_slow:long+=6;lr.append("4h EMA20 > EMA50")
    elif v4.ema_fast<v4.ema_slow:short+=6;sr.append("4h EMA20 < EMA50")
    if v4.structure=="HH_HL":long+=5;lr.append("4h HH/HL regime")
    elif v4.structure=="LH_LL":short+=5;sr.append("4h LH/LL regime")
    if c4h[-1].c>v4.ema_fast and v4.rsi>=50:long+=4
    elif c4h[-1].c<v4.ema_fast and v4.rsi<=50:short+=4

    # 1H directional bias — 25 points.
    if v1.ema_fast>v1.ema_slow:long+=10;lr.append("1h EMA20 > EMA50")
    elif v1.ema_fast<v1.ema_slow:short+=10;sr.append("1h EMA20 < EMA50")
    if v1.structure=="HH_HL":long+=8;lr.append("1h HH/HL structure")
    elif v1.structure=="LH_LL":short+=8;sr.append("1h LH/LL structure")
    if c1h[-1].c>v1.ema_fast:long+=4
    elif c1h[-1].c<v1.ema_fast:short+=4
    if 52<=v1.rsi<=70:long+=3
    elif 30<=v1.rsi<=48:short+=3

    # 15M setup — 20 points. Neutral location never boosts both directions.
    if v15.ema_fast>v15.ema_slow:long+=7;lr.append("15m trend aligned")
    elif v15.ema_fast<v15.ema_slow:short+=7;sr.append("15m trend aligned")
    if v15.structure=="HH_HL":long+=5
    elif v15.structure=="LH_LL":short+=5
    if c15[-1].c>v15.ema_fast and v15.rsi>=50:long+=4
    elif c15[-1].c<v15.ema_fast and v15.rsi<=50:short+=4
    if v15.volume_ratio>=1.05:
        if c15[-1].c>=c15[-1].o:long+=2
        else:short+=2
    if v15.atr>0 and abs(price-v15.ema_fast)/v15.atr<=1.2:
        if v15.trend=="BULLISH":long+=2
        elif v15.trend=="BEARISH":short+=2

    # Confirmed 5M trigger — 25 points.
    lt,lname,llevel=_v26_trigger_long(c5,v5)
    st,sname,slevel=_v26_trigger_short(c5,v5)
    if lt:long+=20;lr.append("full 5m close + "+lname.lower())
    else:lb.append(lname)
    if st:short+=20;sr.append("full 5m close + "+sname.lower())
    else:sb.append(sname)
    if v5.volume_ratio>=cfg.volume_ratio_trigger:
        if c5[-1].c>c5[-1].o:long+=5;lr.append(f"5m volume {v5.volume_ratio:.2f}x")
        elif c5[-1].c<c5[-1].o:short+=5;sr.append(f"5m volume {v5.volume_ratio:.2f}x")

    # Cross-market evidence — only 5 points; never replaces structure/trigger.
    if btc_ctx=="BULLISH":long+=2
    elif btc_ctx=="BEARISH":short+=2
    if eth_ctx=="BULLISH":long+=1
    elif eth_ctx=="BEARISH":short+=1
    if rs>=.25:long+=2;lr.append(f"relative strength vs BTC {rs:+.2f}%")
    elif rs<=-.25:short+=2;sr.append(f"relative weakness vs BTC {rs:+.2f}%")

    if long>=short:
        side="LONG";score=long;reasons=lr;blocks=lb;trigger=lt;trigger_name=lname;level=llevel
    else:
        side="SHORT";score=short;reasons=sr;blocks=sb;trigger=st;trigger_name=sname;level=slevel

    micro_count,micro_text,micro_reasons=_micro_confirmations(c1m,side)
    score+=min(10.0,micro_count*2.5);reasons.extend(micro_reasons[:2])

    bias_ok=(side=="LONG" and v1.trend=="BULLISH") or (side=="SHORT" and v1.trend=="BEARISH")
    regime_opposes=(side=="LONG" and v4.trend=="BEARISH") or (side=="SHORT" and v4.trend=="BULLISH")
    setup_opposes=(side=="LONG" and v15.trend=="BEARISH") or (side=="SHORT" and v15.trend=="BULLISH")
    context_opposes=(side=="LONG" and btc_ctx=="BEARISH" and eth_ctx=="BEARISH") or \
                    (side=="SHORT" and btc_ctx=="BULLISH" and eth_ctx=="BULLISH")
    if not bias_ok:score-=10;blocks.append("1h directional bias is not clean")
    if regime_opposes:score-=10;blocks.append("4h regime opposes trade")
    if setup_opposes:score-=8;blocks.append("15m setup opposes trade")
    if context_opposes:score-=6;blocks.append("BTC + ETH context opposes trade")
    if micro_count<cfg.min_micro_confirmations:
        blocks.append(f"1m confirmation missing ({micro_count}/{cfg.min_micro_confirmations})")

    spread_ok=ticker.spread_pct<=cfg.max_spread_pct
    if not spread_ok:score-=8;blocks.append(f"spread too wide ({ticker.spread_pct:.3f}%)")
    atr5=v5.atr;atr_pct=atr5/price*100 if price else 0.0
    volatility_ok=cfg.min_atr5_pct<=atr_pct<=cfg.max_atr5_pct
    if not volatility_ok:
        score-=8;blocks.append(f"5m volatility outside range ({atr_pct:.3f}%)")
    chase_atr=abs(price-v5.ema_fast)/atr5 if atr5 else 99.0
    range_atr=(c5[-1].h-c5[-1].l)/atr5 if atr5 else 99.0
    too_late=chase_atr>cfg.max_chase_atr or range_atr>cfg.max_5m_range_atr
    if too_late:
        score-=12;blocks.append(f"TOO LATE / extension ({chase_atr:.2f} ATR, bar {range_atr:.2f} ATR)")
    rejected=_opposite_rejection(c5[-1],side)
    if rejected:
        score-=10;blocks.append("fresh opposite 5m rejection wick")

    # Preserve 1R/2R/3R targets; reject a setup if its honest structural SL is impractical.
    entry_low=price-.12*atr5;entry_high=price+.12*atr5
    recent=c5[-10:]
    if side=="LONG":
        swing=min(x.l for x in recent)
        sl=min(price-1.05*atr5,swing-.12*atr5)
        risk=price-sl
        obstacles=[x for x in (v15.resistance,v1.resistance) if x>price]
        obstacle=min(obstacles) if obstacles else 0.0
        rr_space=(obstacle-price)/risk if risk>0 and obstacle else 3.2
        tp1=price+risk;tp2=price+2*risk;tp3=price+3*risk
    else:
        swing=max(x.h for x in recent)
        sl=max(price+1.05*atr5,swing+.12*atr5)
        risk=sl-price
        obstacles=[x for x in (v15.support,v1.support) if 0<x<price]
        obstacle=max(obstacles) if obstacles else 0.0
        rr_space=(price-obstacle)/risk if risk>0 and obstacle else 3.2
        tp1=price-risk;tp2=price-2*risk;tp3=price-3*risk
    stop_atr=risk/atr5 if atr5 else 99.0
    stop_pct=risk/price*100 if price and risk>0 else 99.0
    stop_ok=(risk>0 and cfg.min_stop_atr<=stop_atr<=cfg.max_stop_atr and
             cfg.min_stop_pct<=stop_pct<=cfg.max_stop_pct)
    if not stop_ok:
        score-=12;blocks.append(f"structural SL rejected ({stop_atr:.2f} ATR / {stop_pct:.2f}%)")
    obstacle_rr=rr_space*.92 if obstacle else rr_space
    room_ok=obstacle_rr>=cfg.min_rr_tp2
    if not room_ok:
        score-=12;blocks.append(f"not enough safe room to 15m/1h obstacle ({obstacle_rr:.2f}R)")

    rr=2.0 if risk>0 else 0.0
    score=max(0.0,min(100.0,score));fresh=not too_late
    execute=(score>=cfg.execute_score and trigger and bias_ok and not regime_opposes and
             not setup_opposes and micro_count>=cfg.min_micro_confirmations and fresh and
             spread_ok and volatility_ok and not rejected and stop_ok and room_ok and
             not (cfg.context_hard_block and context_opposes))
    status="EXECUTE" if execute else "POTENTIAL" if score>=cfg.potential_score else "WAIT"
    quality="A+" if score>=92 else "A" if score>=86 else "B+" if score>=cfg.potential_score else "C"
    return TradeAnalysis(
        inst_id,base,side,status,score,quality,price,entry_low,entry_high,sl,tp1,tp2,tp3,rr,
        v1.trend,v15.trend+" / "+v15.structure,trigger_name,btc_ctx,eth_ctx,rs,
        ticker.spread_pct,v5.volume_ratio,atr5,c5[-1].ts,fresh,too_late,reasons,blocks,
        regime_4h=v4.trend,micro_1m=micro_text,micro_confirmations=micro_count,
        atr_5m_pct=atr_pct,stop_atr=stop_atr,stop_pct=stop_pct,
        obstacle_rr=obstacle_rr,core_version="2.6"
    )
