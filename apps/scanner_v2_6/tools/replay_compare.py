#!/usr/bin/env python3
"""Bybit public-data V2.5 vs V2.6 replay.

Run on the new VM before production cutover. It downloads closed 1m candles,
builds every higher timeframe without look-ahead and applies the same future
1m path to both strategy cores. Results are signal-quality evidence, not a
profit guarantee or an execution-engine backtest.
"""

import argparse
import asyncio
import bisect
import json
import math
import sys
import time
from dataclasses import dataclass,asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import aiohttp

from config import Config
from models import Candle,MarketTicker
from strategy import analyze,analyze_v25,tf_view


BAR_MS={"1m":60_000,"5m":300_000,"15m":900_000,"1H":3_600_000,"4H":14_400_000}
DEFAULT_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,SUIUSDT,HYPEUSDT,LINKUSDT,AAVEUSDT,AVAXUSDT,ADAUSDT,BNBUSDT,PEPEUSDT,BTRUSDT"


def aggregate(rows,bar_ms):
    buckets={}
    for c in rows:
        start=(c.ts//bar_ms)*bar_ms
        buckets.setdefault(start,[]).append(c)
    expected=bar_ms//60_000
    out=[]
    for start,x in sorted(buckets.items()):
        x.sort(key=lambda c:c.ts)
        if len(x)!=expected or x[0].ts!=start or x[-1].ts!=start+bar_ms-60_000:
            continue
        out.append(Candle(
            start,x[0].o,max(c.h for c in x),min(c.l for c in x),x[-1].c,
            sum(c.vol for c in x),sum(c.quote_vol for c in x),True
        ))
    return out


class Window:
    def __init__(self,rows,bar_ms):
        self.rows=rows
        self.closed=[x.ts+bar_ms for x in rows]

    def at(self,at_ms,limit):
        i=bisect.bisect_right(self.closed,at_ms)
        return self.rows[max(0,i-limit):i]


class PublicHistory:
    def __init__(self,base_url,session,pace=.08):
        self.base=base_url.rstrip("/");self.s=session;self.pace=pace
        self._lock=asyncio.Lock();self._last=0.0

    async def _get(self,params,retries=4):
        for attempt in range(retries):
            async with self._lock:
                wait=self.pace-(time.monotonic()-self._last)
                if wait>0:await asyncio.sleep(wait)
                self._last=time.monotonic()
            try:
                async with self.s.get(self.base+"/v5/market/kline",params=params,
                                      timeout=aiohttp.ClientTimeout(total=20)) as r:
                    raw=await r.text()
                    if r.status in {403,429}:
                        raise RuntimeError(f"Bybit HTTP {r.status}")
                    if r.status>=400:raise RuntimeError(f"HTTP {r.status}: {raw[:160]}")
                    data=json.loads(raw)
                    if int(data.get("retCode",-1))!=0:
                        raise RuntimeError(f"Bybit {data.get('retCode')}: {data.get('retMsg')}")
                    return data.get("result",{}).get("list",[])
            except Exception:
                if attempt+1>=retries:raise
                await asyncio.sleep(min(8.0,1.0*(2**attempt)))

    async def one_minute(self,symbol,start_ms,end_ms):
        found={};cursor=end_ms
        while cursor>=start_ms:
            page=await self._get({
                "category":"linear","symbol":symbol,"interval":"1",
                "start":str(start_ms),"end":str(cursor),"limit":"1000",
            })
            if not page:break
            oldest=None
            for x in page:
                try:
                    ts=int(x[0]);oldest=ts if oldest is None else min(oldest,ts)
                    if start_ms<=ts<=end_ms:
                        found[ts]=Candle(ts,float(x[1]),float(x[2]),float(x[3]),
                                         float(x[4]),float(x[5]),float(x[6]),True)
                except (ValueError,TypeError,IndexError):
                    continue
            if oldest is None or oldest<=start_ms:break
            next_cursor=oldest-1
            if next_cursor>=cursor:break
            cursor=next_cursor
        return [found[k] for k in sorted(found)]


@dataclass
class Result:
    engine:str
    signals:int=0
    wins:int=0
    full_sl:int=0
    tp1:int=0
    tp2:int=0
    tp3:int=0
    total_gross_r:float=0.0
    total_net_r:float=0.0
    profit_factor:float=0.0
    max_drawdown_r:float=0.0
    avg_net_r:float=0.0


def evaluate_path(rows,start_ms,a,max_hold_ms,cost_pct,parts=(.40,.30,.30)):
    starts=[x.ts for x in rows]
    i=bisect.bisect_left(starts,start_ms)
    end=start_ms+max_hold_ms
    risk=abs(a.price-a.sl)
    if risk<=0:return None
    f1,f2,f3=parts;total=f1+f2+f3
    f1,f2,f3=f1/total,f2/total,f3/total
    remaining=1.0;gross=0.0;hit1=hit2=hit3=False;last=a.price;ended=start_ms
    for c in rows[i:]:
        if c.ts>=end:break
        last=c.c;ended=c.ts+60_000
        stop=(c.l<=a.sl) if a.side=="LONG" else (c.h>=a.sl)
        h1=(c.h>=a.tp1) if a.side=="LONG" else (c.l<=a.tp1)
        h2=(c.h>=a.tp2) if a.side=="LONG" else (c.l<=a.tp2)
        h3=(c.h>=a.tp3) if a.side=="LONG" else (c.l<=a.tp3)
        # Unknown same-minute ordering is resolved conservatively.
        if stop:
            gross-=remaining
            remaining=0.0
            break
        if h1 and not hit1:
            gross+=f1*1.0;remaining-=f1;hit1=True
        if h2 and not hit2:
            gross+=f2*2.0;remaining-=f2;hit2=True
        if h3 and not hit3:
            gross+=f3*3.0;remaining-=f3;hit3=True
            break
    if remaining>1e-9:
        current_r=((last-a.price)/risk) if a.side=="LONG" else ((a.price-last)/risk)
        gross+=remaining*current_r
    stop_pct=risk/a.price*100 if a.price else 0.0
    net=gross-(cost_pct/stop_pct if stop_pct>0 else 0.0)
    return {"gross":gross,"net":net,"tp1":hit1,"tp2":hit2,"tp3":hit3,
            "full_sl":not hit1 and gross<=-0.99,"ended":ended}


def finish(engine,outcomes):
    r=Result(engine=engine,signals=len(outcomes))
    equity=peak=0.0;profits=losses=0.0
    for x in outcomes:
        net=x["net"];r.total_gross_r+=x["gross"];r.total_net_r+=net
        r.wins+=int(net>0);r.full_sl+=int(x["full_sl"])
        r.tp1+=int(x["tp1"]);r.tp2+=int(x["tp2"]);r.tp3+=int(x["tp3"])
        profits+=max(0.0,net);losses+=max(0.0,-net)
        equity+=net;peak=max(peak,equity);r.max_drawdown_r=max(r.max_drawdown_r,peak-equity)
    r.avg_net_r=r.total_net_r/r.signals if r.signals else 0.0
    r.profit_factor=profits/losses if losses>0 else (math.inf if profits>0 else 0.0)
    return r


def replay_symbol(symbol,one_minute,cfg,start_eval_ms,end_ms,spread_pct,cost_pct,max_hold_ms):
    frames={name:aggregate(one_minute,ms) for name,ms in BAR_MS.items() if name!="1m"}
    frames["1m"]=one_minute
    windows={name:Window(rows,BAR_MS[name]) for name,rows in frames.items()}
    return frames,windows


def analysis_at(symbol,windows,contexts,at_ms,cfg,spread_pct):
    c4=windows["4H"].at(at_ms,90);c1h=windows["1H"].at(at_ms,90)
    c15=windows["15m"].at(at_ms,100);c5=windows["5m"].at(at_ms,120)
    c1m=windows["1m"].at(at_ms,60)
    if min(len(c4),len(c1h),len(c15),len(c5),len(c1m))<25:return None,None
    price=c5[-1].c;half=spread_pct/200
    ticker=MarketTicker(symbol,symbol[:-4],price,price,price,price,10_000_000,
                        price*(1-half),price*(1+half),at_ms/1000)
    btc,eth=contexts
    old=analyze_v25(symbol,ticker,c1h,c15,c5,btc,eth,cfg)
    new=analyze(symbol,ticker,c4,c1h,c15,c5,c1m,btc,eth,cfg)
    return old,new


def context_at(windows,at_ms):
    h=windows["1H"].at(at_ms,90);m=windows["15m"].at(at_ms,100)
    return tf_view(h,20,50),tf_view(m,9,21)


async def run(args):
    cfg=Config();now_ms=int(time.time()*1000)
    end_ms=args.end_ms or (now_ms//60_000-2)*60_000
    eval_start=end_ms-args.days*86_400_000
    fetch_start=eval_start-args.warmup_days*86_400_000
    symbols=list(dict.fromkeys(x.strip().upper() for x in args.symbols.split(",") if x.strip()))
    for x in ("BTCUSDT","ETHUSDT"):
        if x not in symbols:symbols.append(x)
    cache=Path(args.cache_dir);cache.mkdir(parents=True,exist_ok=True)
    datasets={}
    async with aiohttp.ClientSession(headers={"User-Agent":"Bybit-V2.6-Replay/1.0"}) as session:
        api=PublicHistory(cfg.rest_url,session,cfg.bybit_min_request_interval_sec)
        for symbol in symbols:
            path=cache/f"{symbol}_{fetch_start}_{end_ms}.json"
            if path.exists():
                raw=json.loads(path.read_text())
                rows=[Candle(*x) for x in raw]
            else:
                print(f"Downloading {symbol} 1m...",flush=True)
                rows=await api.one_minute(symbol,fetch_start,end_ms)
                path.write_text(json.dumps([[c.ts,c.o,c.h,c.l,c.c,c.vol,c.quote_vol,c.confirm] for c in rows]))
            if len(rows)<args.days*1200:
                print(f"SKIP {symbol}: only {len(rows)} one-minute candles",flush=True)
                continue
            datasets[symbol]=rows
    if "BTCUSDT" not in datasets or "ETHUSDT" not in datasets:
        raise RuntimeError("BTCUSDT and ETHUSDT history are required for context")

    prepared={s:replay_symbol(s,rows,cfg,eval_start,end_ms,args.spread_pct,
                              args.cost_pct,args.max_hold_hours*3_600_000)
              for s,rows in datasets.items()}
    btc_w=prepared["BTCUSDT"][1];eth_w=prepared["ETHUSDT"][1]
    results={"V2.5":[],"V2.6":[]};next_ok={"V2.5":{},"V2.6":{}}
    for symbol,(frames,windows) in prepared.items():
        five=frames["5m"]
        for bar in five:
            at_ms=bar.ts+BAR_MS["5m"]
            if at_ms<eval_start or at_ms>end_ms:continue
            contexts=(context_at(btc_w,at_ms),context_at(eth_w,at_ms))
            old,new=analysis_at(symbol,windows,contexts,at_ms,cfg,args.spread_pct)
            for name,a in (("V2.5",old),("V2.6",new)):
                if not a or a.status!="EXECUTE":continue
                if at_ms<next_ok[name].get(symbol,0):continue
                outcome=evaluate_path(
                    datasets[symbol],at_ms,a,args.max_hold_hours*3_600_000,
                    args.cost_pct,(cfg.edge_tp1_fraction,cfg.edge_tp2_fraction,cfg.edge_tp3_fraction)
                )
                if not outcome:continue
                outcome.update({"symbol":symbol,"at_ms":at_ms,"setup":a.trigger_5m,
                                "side":a.side,"score":a.score})
                results[name].append(outcome)
                next_ok[name][symbol]=max(outcome["ended"],at_ms+cfg.signal_cooldown_sec*1000)

    summaries=[finish(name,rows) for name,rows in results.items()]
    payload={
        "generated_at":time.time(),"period":{"start_ms":eval_start,"end_ms":end_ms},
        "assumptions":{"spread_pct":args.spread_pct,"roundtrip_cost_pct":args.cost_pct,
                       "max_hold_hours":args.max_hold_hours,"tp_fractions":[cfg.edge_tp1_fraction,cfg.edge_tp2_fraction,cfg.edge_tp3_fraction],
                       "same_bar_rule":"SL first"},
        "symbols":[x for x in symbols if x in datasets],
        "summaries":[asdict(x) for x in summaries],
    }
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,indent=2))
    for x in summaries:
        win=x.wins/x.signals*100 if x.signals else 0
        full=x.full_sl/x.signals*100 if x.signals else 0
        print(f"{x.engine}: n={x.signals} win={win:.1f}% fullSL={full:.1f}% "
              f"avgNet={x.avg_net_r:+.3f}R totalNet={x.total_net_r:+.2f}R "
              f"PF={x.profit_factor:.2f} maxDD={x.max_drawdown_r:.2f}R")
    print(f"Saved {output}")


def parser():
    p=argparse.ArgumentParser(description="Compare frozen V2.5 and candidate V2.6 on Bybit history")
    p.add_argument("--symbols",default=DEFAULT_SYMBOLS)
    p.add_argument("--days",type=int,default=30)
    p.add_argument("--warmup-days",type=int,default=12)
    p.add_argument("--max-hold-hours",type=int,default=12)
    p.add_argument("--spread-pct",type=float,default=.03)
    p.add_argument("--cost-pct",type=float,default=.13)
    p.add_argument("--end-ms",type=int,default=0)
    p.add_argument("--cache-dir",default="data/replay_cache")
    p.add_argument("--output",default="data/v25_v26_replay.json")
    return p


if __name__=="__main__":
    asyncio.run(run(parser().parse_args()))
