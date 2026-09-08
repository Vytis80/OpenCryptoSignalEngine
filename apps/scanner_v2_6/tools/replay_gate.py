#!/usr/bin/env python3
"""Fail closed unless a V2.6 replay materially beats the frozen V2.5 core."""

import argparse
import json
from pathlib import Path


def assess(payload,min_sample=50,min_edge_improvement=.03,allow_dd_ratio=1.0):
    rows={x["engine"]:x for x in payload.get("summaries",[])}
    old=rows.get("V2.5");new=rows.get("V2.6")
    if not old or not new:return False,["missing V2.5 or V2.6 summary"]
    reasons=[]
    if old.get("signals",0)<min_sample:reasons.append(f"V2.5 sample {old.get('signals',0)} < {min_sample}")
    if new.get("signals",0)<min_sample:reasons.append(f"V2.6 sample {new.get('signals',0)} < {min_sample}")
    edge_gain=new.get("avg_net_r",0)-old.get("avg_net_r",0)
    if new.get("avg_net_r",0)<=0:reasons.append(f"V2.6 net expectancy {new.get('avg_net_r',0):+.3f}R is not positive")
    if edge_gain<min_edge_improvement:reasons.append(f"net edge improvement {edge_gain:+.3f}R < {min_edge_improvement:.3f}R")
    if new.get("profit_factor",0)<old.get("profit_factor",0):reasons.append("V2.6 profit factor is below V2.5")
    old_full=old.get("full_sl",0)/max(1,old.get("signals",0))
    new_full=new.get("full_sl",0)/max(1,new.get("signals",0))
    if new_full>old_full:reasons.append(f"full-SL rate worsened {old_full:.1%} -> {new_full:.1%}")
    old_dd=max(0.01,old.get("max_drawdown_r",0))
    if new.get("max_drawdown_r",0)>old_dd*allow_dd_ratio:
        reasons.append(f"max drawdown worsened {old_dd:.2f}R -> {new.get('max_drawdown_r',0):.2f}R")
    return not reasons,reasons


def main():
    p=argparse.ArgumentParser(description="Promotion gate for a V2.5/V2.6 replay report")
    p.add_argument("report")
    p.add_argument("--min-sample",type=int,default=50)
    p.add_argument("--min-edge-improvement",type=float,default=.03)
    p.add_argument("--allow-dd-ratio",type=float,default=1.0)
    a=p.parse_args();payload=json.loads(Path(a.report).read_text())
    ok,reasons=assess(payload,a.min_sample,a.min_edge_improvement,a.allow_dd_ratio)
    if ok:
        print("PASS: V2.6 promotion gate")
        return 0
    print("FAIL: V2.6 remains unpromoted")
    for x in reasons:print("- "+x)
    return 2


if __name__=="__main__":
    raise SystemExit(main())
