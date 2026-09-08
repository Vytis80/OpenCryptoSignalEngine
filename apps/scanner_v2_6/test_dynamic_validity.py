
from types import SimpleNamespace
from config import Config
from enhancements import dynamic_validity
from models import ActiveSignal,Candle

c=Config();now=1_700_000_000.0
s=ActiveSignal(1,'SUIUSDT','SUI','LONG','A',86,now,100,99.9,100.1,99,101,102,103,now+900,setup_type='PULLBACK REACTION',last_price=100)
a=SimpleNamespace(trigger_5m='PULLBACK REACTION',side='LONG',score=86,bias_1h='BULLISH',setup_15m='BULLISH / HH_HL',volume_ratio_5m=1.4,btc_context='BULLISH',price=100)
m=[Candle(i,100+i*.01,100.1+i*.01,99.9+i*.01,100.02+i*.01,1,1,True) for i in range(6)]
exp,state,score,note=dynamic_validity(s,a,m,c,now)
assert exp>now and state in {'STRONG','NORMAL','WEAKENING'}
a.price=100.9
exp2,state2,score2,note2=dynamic_validity(s,a,m,c,now+30)
assert state2=='CLOSED', (exp2,state2,note2)
print('OK: dynamic entry validity adapts and closes entry without closing the ActiveSignal')
