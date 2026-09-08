
from models import Candle,TradeAnalysis
from enhancements import shadow_assess
from config import Config

c=Config();cand=[];p=100.0
for i in range(30):
    o=p;p=p*(1.0004 if i%2==0 else .9999)
    cand.append(Candle(i,o,max(o,p)*1.001,min(o,p)*.999,p,100,10000,True))
m=[];q=100
for i in range(8):
    o=q;q*=1.0002;m.append(Candle(i,o,q*1.0002,o*.9999,q,10,1000,True))
a=TradeAnalysis('TESTUSDT','TEST','LONG','EXECUTE',84,'B+',100,99.9,100.1,98.8,101.2,102.4,103.6,2.0,'BULLISH','BULLISH / HH_HL','PULLBACK REACTION','NEUTRAL','BULLISH',.1,.01,1.3,1.0,123,True,False,['x'],[])
orig=(a.status,a.sl,a.tp1,a.tp2,a.tp3,a.score)
sh=shadow_assess(a,cand,m,c)
assert (a.status,a.sl,a.tp1,a.tp2,a.tp3,a.score)==orig
assert sh.status in {'PASS','WOULD_BLOCK','NO_DATA'}
print('OK: anti-SL SHADOW is observational and does not mutate EXECUTE/SL/TP')
