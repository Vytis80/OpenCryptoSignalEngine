from tools.replay_gate import assess


def row(engine,signals,avg,pf,full_sl,dd):
    return {"engine":engine,"signals":signals,"avg_net_r":avg,"profit_factor":pf,
            "full_sl":full_sl,"max_drawdown_r":dd}


good={"summaries":[row("V2.5",100,.05,1.10,35,12),row("V2.6",80,.14,1.35,20,8)]}
ok,reasons=assess(good,min_sample=50)
assert ok,reasons

bad={"summaries":[row("V2.5",100,.05,1.20,30,10),row("V2.6",20,-.02,.80,10,14)]}
ok,reasons=assess(bad,min_sample=50)
assert not ok and len(reasons)>=4,reasons

print("OK: replay promotion gate passes better V2.6 and fails weak/insufficient evidence")
