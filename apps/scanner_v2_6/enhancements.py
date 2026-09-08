
import time
from statistics import mean
from models import EarlyAnalysis,ShadowAssessment
from strategy import tf_view
from indicators import close_position

def pct(a,b):return (a/b-1)*100 if b else 0.0

def _rng(c):return max(c.h-c.l,1e-12)
def _upper_wick(c):return max(0.0,c.h-max(c.o,c.c))
def _lower_wick(c):return max(0.0,min(c.o,c.c)-c.l)

def analyze_early(base_analysis,c5_live,c1m,cfg,now_ms=None):
    """Heads-up only. This function can return EARLY/POTENTIAL but can never create EXECUTE."""
    if not base_analysis or base_analysis.too_late or base_analysis.score<cfg.early_min_base_score:return None
    confirmed=[x for x in c5_live if x.confirm]
    current=next((x for x in reversed(c5_live) if not x.confirm),None)
    if len(confirmed)<25 or current is None:return None
    v5=tf_view(confirmed,9,21)
    if v5.atr<=0:return None
    side=base_analysis.side
    bias_ok=(side=='LONG' and base_analysis.bias_1h=='BULLISH') or (side=='SHORT' and base_analysis.bias_1h=='BEARISH')
    if not bias_ok:return None
    now_ms=now_ms or int(time.time()*1000)
    elapsed=max(.08,min(.99,(now_ms-current.ts)/300000.0))
    avg_vol=mean([x.vol for x in confirmed[-20:] if x.vol>0]) if confirmed else 0
    projected=(current.vol/max(elapsed,.08))/avg_vol if avg_vol>0 else 0.0
    m=[x for x in c1m if x.confirm]
    mom=pct(m[-1].c,m[-4].c) if len(m)>=4 else 0.0
    last3=m[-3:];bull=sum(x.c>x.o for x in last3);bear=sum(x.c<x.o for x in last3)
    micro=(mom>0 and bull>=2) if side=='LONG' else (mom<0 and bear>=2)
    ema_anchor=max(v5.ema_fast,v5.ema_slow) if side=='LONG' else min(v5.ema_fast,v5.ema_slow)
    prior=confirmed[-22:-2] if len(confirmed)>=24 else confirmed[:-2]
    if not prior:return None
    breakout=max(x.h for x in prior) if side=='LONG' else min(x.l for x in prior)
    d_ema=abs(current.c-ema_anchor)/v5.atr;d_break=abs(current.c-breakout)/v5.atr
    distance=min(d_ema,d_break)
    hint='EMA reaction' if d_ema<=d_break else ('breakout/retest' if side=='LONG' else 'breakdown/retest')
    current_aligned=(current.c>=current.o and close_position(current)>=.52) if side=='LONG' else (current.c<=current.o and close_position(current)<=.48)
    score=float(base_analysis.score);reasons=[]
    if distance<=cfg.early_trigger_distance_atr:score+=4;reasons.append(f'trigger {distance:.2f} ATR away')
    if micro:score+=5;reasons.append(f'1m momentum {mom:+.2f}% aligned')
    elif current_aligned:score+=2;reasons.append('current 5m candle moving with setup')
    if projected>=1.15:score+=5;reasons.append(f'projected 5m volume {projected:.2f}x')
    elif projected>=cfg.early_min_projected_volume:score+=2;reasons.append(f'projected 5m volume {projected:.2f}x')
    score=max(0,min(100,score));secs=max(0,int((current.ts+300000-now_ms)/1000));stage='NONE'
    if score>=cfg.early_alert_score and distance<=cfg.early_trigger_distance_atr and projected>=cfg.early_min_projected_volume and (micro or current_aligned):stage='EARLY'
    if score>=cfg.early_potential_score and distance<=cfg.early_potential_distance_atr and projected>=cfg.early_potential_projected_volume and micro and secs<=cfg.early_potential_max_sec_to_close:stage='POTENTIAL'
    if stage=='NONE':return None
    return EarlyAnalysis(base_analysis.inst_id,base_analysis.base,side,stage,score,current.c,distance,projected,mom,micro,secs,hint,current.ts,reasons)

def shadow_assess(a,c5,c1m,cfg):
    """Anti-SL analytics only. It NEVER edits TradeAnalysis and NEVER blocks an EXECUTE."""
    now=time.time();reasons=[];critical=[];atr=max(a.atr_5m,1e-12)
    confirmed=[x for x in c5 if x.confirm]
    recent=confirmed[-max(3,cfg.shadow_swing_lookback):]
    if not recent:
        return ShadowAssessment(a.inst_id,False,'NO_DATA',a.sl,0.0,0.0,now,['not enough 5m candles'])
    if a.side=='LONG':suggested=min(x.l for x in recent)-cfg.shadow_buffer_atr*atr;sl_atr=(a.price-suggested)/atr
    else:suggested=max(x.h for x in recent)+cfg.shadow_buffer_atr*atr;sl_atr=(suggested-a.price)/atr
    original_atr=abs(a.price-a.sl)/atr
    if original_atr<cfg.shadow_min_stop_atr:critical.append(f'original SL may sit inside normal noise ({original_atr:.2f} ATR)')
    if original_atr>cfg.shadow_max_stop_atr:critical.append(f'original SL is wide ({original_atr:.2f} ATR)')
    r5=_rng(recent[-1])/atr
    if r5>cfg.shadow_max_5m_spike_atr:critical.append(f'5m volatility spike ({r5:.2f} ATR)')
    m=[x for x in c1m if x.confirm];mom=0.0
    if len(m)>=4:
        last3=m[-3:];mom=pct(m[-1].c,m[-4].c)
        aligned=sum((x.c>x.o) if a.side=='LONG' else (x.c<x.o) for x in last3)
        direction_ok=(mom>0) if a.side=='LONG' else (mom<0)
        if not direction_ok or aligned<cfg.shadow_min_aligned_1m:critical.append(f'1m momentum weak/opposite ({mom:+.3f}%, aligned {aligned}/3)')
        spike=max(_rng(x) for x in last3)/atr
        if spike>cfg.shadow_max_1m_spike_atr:critical.append(f'1m volatility spike ({spike:.2f} of 5m ATR)')
        last=m[-1];body=max(abs(last.c-last.o),atr*.005)
        opp=(_upper_wick(last)/body) if a.side=='LONG' else (_lower_wick(last)/body)
        if opp>1.8:reasons.append(f'opposite 1m wick elevated ({opp:.2f}x body)')
    else:reasons.append('not enough 1m candles for full shadow check')
    reasons += critical
    would=bool(critical)
    return ShadowAssessment(a.inst_id,would,'WOULD_BLOCK' if would else 'PASS',suggested,sl_atr,mom,now,reasons or ['shadow filters see no extra risk'])

def dynamic_validity(s,a,c1m,cfg,now=None):
    """Return absolute expiry, state, score, note. Entry validity only; never a trade exit."""
    now=now or time.time()
    if s.entry_window_notified:return s.expires_at,'CLOSED',0.0,'Entry window already closed for this signal.'
    total=float(cfg.signal_validity_sec);score=55.0;notes=[];force_close=False
    setup=(s.setup_type or a.trigger_5m or '').upper()
    if 'BREAKOUT' in setup or 'BREAKDOWN' in setup:total*=.85;notes.append('fast breakout/retest setup')
    elif 'PULLBACK' in setup:total*=1.20;score+=8;notes.append('pullback can remain valid longer')
    elif 'EMA' in setup:score+=4;notes.append('EMA reaction setup')
    aligned_1h=(s.side=='LONG' and a.bias_1h=='BULLISH') or (s.side=='SHORT' and a.bias_1h=='BEARISH')
    aligned_15=(s.side=='LONG' and a.setup_15m.startswith('BULLISH')) or (s.side=='SHORT' and a.setup_15m.startswith('BEARISH'))
    if aligned_1h:total+=90;score+=8
    else:total-=180;score-=18;notes.append('1H alignment weakened')
    if aligned_15:total+=120;score+=10
    else:total-=180;score-=20;notes.append('15M alignment weakened')
    if a.volume_ratio_5m>=1.30:total+=120;score+=8;notes.append('5m volume persists')
    elif a.volume_ratio_5m<0.90:total-=150;score-=10;notes.append('5m volume faded')
    ctx_good=(s.side=='LONG' and a.btc_context!='BEARISH') or (s.side=='SHORT' and a.btc_context!='BULLISH')
    if ctx_good:score+=4
    else:total-=150;score-=10;notes.append('BTC context opposes entry')
    risk=max(abs(s.entry-s.sl),1e-12);current_r=((a.price-s.entry)/risk) if s.side=='LONG' else ((s.entry-a.price)/risk)
    dist_r=abs(a.price-s.entry)/risk
    if current_r>=.75:force_close=True;notes.append(f'price already moved +{current_r:.2f}R from original entry')
    elif dist_r>=.55:total-=180;score-=12;notes.append(f'price {dist_r:.2f}R away from original entry')
    if current_r<=-.55:force_close=True;notes.append(f'price moved {current_r:.2f}R against original entry')
    m=[x for x in c1m if x.confirm]
    if len(m)>=4:
        mom=pct(m[-1].c,m[-4].c);aligned=(mom>0) if s.side=='LONG' else (mom<0)
        if aligned:total+=60;score+=7
        elif abs(mom)>=.08:total-=180;score-=12;notes.append(f'1m momentum opposes ({mom:+.2f}%)')
        if (s.side=='LONG' and mom<=-.18) or (s.side=='SHORT' and mom>=.18):total-=180;score-=10
    opposite=(a.side!=s.side and a.score>=78)
    structural=(s.side=='LONG' and a.bias_1h=='BEARISH' and a.setup_15m.startswith('BEARISH')) or (s.side=='SHORT' and a.bias_1h=='BULLISH' and a.setup_15m.startswith('BULLISH'))
    if opposite or structural:force_close=True;notes.append('fresh structure no longer supports a new entry')
    total=max(cfg.dynamic_validity_min_sec,min(cfg.dynamic_validity_max_sec,total))
    expiry=s.confirmed_at+total
    if force_close:expiry=min(expiry,now)
    remaining=expiry-now;score=max(0,min(100,score))
    state='CLOSED' if remaining<=0 else 'STRONG' if score>=75 and remaining>300 else 'WEAKENING' if score<45 or remaining<180 else 'NORMAL'
    note='; '.join(notes[:4]) or 'structure, momentum and price location remain normal'
    return expiry,state,score,note
