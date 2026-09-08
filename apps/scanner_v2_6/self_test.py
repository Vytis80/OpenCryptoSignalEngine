from models import Candle
from indicators import ema,rsi,atr,volume_ratio,structure
x=[]
p=100.0
for i in range(80):
    o=p;p*=1.001
    x.append(Candle(i,o,p*1.001,o*.999,p,100+i,10000+i*100,True))
assert ema([c.c for c in x],20)>0
assert atr(x)>0
assert 0<=rsi([c.c for c in x])<=100
assert volume_ratio(x)>0
print("OK: Crypto Scanner V2.6 SMART indicator/model self-test passed")
