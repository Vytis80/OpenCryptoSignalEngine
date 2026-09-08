from types import SimpleNamespace

from models import Candle
from tools.replay_compare import aggregate,evaluate_path,finish


rows=[]
for i in range(10):
    rows.append(Candle(i*60_000,100+i*.01,100.2+i*.01,99.8+i*.01,100.05+i*.01,1,100,True))
five=aggregate(rows,300_000)
assert len(five)==2
assert five[0].ts==0 and five[1].ts==300_000
assert five[0].o==rows[0].o and five[0].c==rows[4].c

a=SimpleNamespace(side="LONG",price=100.0,sl=99.0,tp1=101.0,tp2=102.0,tp3=103.0)
future=[
    Candle(0,100,101.1,99.5,100.8,1,1,True),
    Candle(60_000,100.8,102.1,100.5,101.8,1,1,True),
    Candle(120_000,101.8,103.1,101.5,103.0,1,1,True),
]
r=evaluate_path(future,0,a,3_600_000,0.0)
assert r["tp1"] and r["tp2"] and r["tp3"]
assert abs(r["gross"]-1.9)<1e-9,r

ambiguous=[Candle(0,100,101.2,98.8,100,1,1,True)]
bad=evaluate_path(ambiguous,0,a,3_600_000,0.0)
assert bad["full_sl"] and bad["gross"]==-1.0,bad

summary=finish("TEST",[r,bad])
assert summary.signals==2 and summary.tp3==1 and summary.full_sl==1

print("OK: replay aggregation, 40/30/30 R accounting and conservative same-bar rule")
