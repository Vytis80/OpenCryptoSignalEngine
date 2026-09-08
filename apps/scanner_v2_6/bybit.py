import asyncio,time,json,aiohttp
from models import Candle,MarketTicker

def f(v,d=0.0):
    try:return float(v)
    except:return d

class Bybit:
    """Public Bybit V5 market-data adapter for USDT linear perpetuals only."""
    BAR_MAP={"1m":"1","5m":"5","15m":"15","1H":"60","4H":"240"}
    BAR_MS={"1m":60_000,"5m":300_000,"15m":900_000,"1H":3_600_000,"4H":14_400_000}

    def __init__(self,cfg,session):
        self.cfg=cfg;self.s=session
        self._pace_lock=asyncio.Lock();self._last_request_at=0.0
        self._live_symbols=set()
        self.last_success_at=0.0
        self.last_error_at=0.0
        self.last_latency_sec=0.0
        self.rate_limit_count=0
        self.last_rate_limit_at=0.0
        self.ip_blocked_until=0.0
        self.last_limit_remaining=None
        self.last_limit_total=None

    async def _pace(self):
        async with self._pace_lock:
            now=time.monotonic()
            wait=self.cfg.bybit_min_request_interval_sec-(now-self._last_request_at)
            if wait>0:await asyncio.sleep(wait)
            self._last_request_at=time.monotonic()

    async def get(self,path,params=None,retries=3):
        url=self.cfg.rest_url+path;err=None
        for n in range(retries+1):
            try:
                now=time.time()
                if self.ip_blocked_until>now:
                    raise RuntimeError(
                        f"Bybit IP cooldown active for {self.ip_blocked_until-now:.0f}s"
                    )
                await self._pace()
                started=time.monotonic()
                async with self.s.get(url,params=params,timeout=aiohttp.ClientTimeout(total=12)) as r:
                    raw=await r.text()
                    self.last_latency_sec=time.monotonic()-started
                    headers=getattr(r,"headers",{}) or {}
                    try:self.last_limit_remaining=int(headers.get("X-Bapi-Limit-Status",""))
                    except Exception:self.last_limit_remaining=None
                    try:self.last_limit_total=int(headers.get("X-Bapi-Limit",""))
                    except Exception:self.last_limit_total=None
                    if r.status==403:
                        self.rate_limit_count+=1;self.last_rate_limit_at=time.time()
                        # Bybit documents a ten-minute IP cooldown after this response.
                        self.ip_blocked_until=time.time()+600
                        raise RuntimeError("Bybit HTTP 403 access-too-frequent; 10m cooldown activated")
                    if r.status==429:
                        self.rate_limit_count+=1;self.last_rate_limit_at=time.time()
                        retry_after=headers.get("Retry-After")
                        try:delay=float(retry_after) if retry_after else self.cfg.bybit_retry_429_base_sec*(2**n)
                        except Exception:delay=self.cfg.bybit_retry_429_base_sec*(2**n)
                        err=RuntimeError(f"Bybit rate limited; retry in {delay:.1f}s")
                        if n<retries:
                            await asyncio.sleep(min(delay,8.0));continue
                        raise err
                    if r.status>=400:raise RuntimeError(f"HTTP {r.status}: {raw[:180]}")
                    d=json.loads(raw)
                    code=int(d.get("retCode",-1))
                    if code!=0:
                        if code==10006 and n<retries:
                            self.rate_limit_count+=1;self.last_rate_limit_at=time.time()
                            delay=self.cfg.bybit_retry_429_base_sec*(2**n)
                            err=RuntimeError(f"Bybit rate limited (10006); retry in {delay:.1f}s")
                            await asyncio.sleep(min(delay,8.0));continue
                        raise RuntimeError(f"Bybit retCode {code}: {d.get('retMsg','')}")
                    self.last_success_at=time.time()
                    return d.get("result",{})
            except Exception as e:
                err=e;self.last_error_at=time.time()
                if self.ip_blocked_until>time.time():break
                if n<retries:await asyncio.sleep(.4*(n+1))
        raise err

    async def live_perpetuals(self):
        out={};cursor=""
        while True:
            params={"category":"linear","status":"Trading","limit":"1000"}
            if cursor:params["cursor"]=cursor
            result=await self.get("/v5/market/instruments-info",params)
            for x in result.get("list",[]):
                if x.get("status")!="Trading":continue
                if x.get("contractType")!="LinearPerpetual":continue
                if x.get("quoteCoin")!=self.cfg.quote or x.get("settleCoin")!=self.cfg.quote:continue
                sym=x.get("symbol","")
                base=x.get("baseCoin","")
                if sym and base:out[sym]=base
            cursor=result.get("nextPageCursor") or ""
            if not cursor:break
        self._live_symbols=set(out)
        return out

    async def tickers(self):
        result=await self.get("/v5/market/tickers",{"category":"linear"})
        out={};now=time.time()
        for x in result.get("list",[]):
            sym=x.get("symbol","")
            if self._live_symbols and sym not in self._live_symbols:continue
            if not self._live_symbols and not sym.endswith(self.cfg.quote):continue
            last=f(x.get("lastPrice"))
            if last<=0:continue
            base=(sym[:-len(self.cfg.quote)] if sym.endswith(self.cfg.quote) else sym)
            out[sym]=MarketTicker(
                sym,base,last,f(x.get("prevPrice24h")),f(x.get("highPrice24h")),f(x.get("lowPrice24h")),
                f(x.get("turnover24h")),f(x.get("bid1Price")),f(x.get("ask1Price")),now
            )
        return out

    def _bar(self,bar):
        if bar not in self.BAR_MAP:raise ValueError(f"Unsupported Bybit bar: {bar}")
        return self.BAR_MAP[bar],self.BAR_MS[bar]

    async def _candles(self,symbol,bar,limit,include_live):
        interval,bar_ms=self._bar(bar)
        result=await self.get("/v5/market/kline",{"category":"linear","symbol":symbol,"interval":interval,"limit":str(limit)})
        now_ms=int(time.time()*1000)
        out=[]
        for x in result.get("list",[]):
            try:
                ts=int(x[0]);confirm=(ts+bar_ms)<=now_ms
                out.append(Candle(ts,float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5]),float(x[6]),confirm))
            except Exception:pass
        out=list(reversed(out))
        return out if include_live else [c for c in out if c.confirm]

    async def candles(self,symbol,bar,limit=120):
        """Chronological, closed candles only. This preserves SAFE confirmed-candle EXECUTE semantics."""
        return await self._candles(symbol,bar,limit,False)

    async def candles_live(self,symbol,bar,limit=120):
        """Chronological candles including the currently forming candle for EARLY analytics only."""
        return await self._candles(symbol,bar,limit,True)

    async def ticker(self,symbol):
        result=await self.get("/v5/market/tickers",{"category":"linear","symbol":symbol})
        rows=result.get("list",[])
        if not rows:return None
        x=rows[0];last=f(x.get("lastPrice"))
        if last<=0:return None
        base=(symbol[:-len(self.cfg.quote)] if symbol.endswith(self.cfg.quote) else symbol)
        return MarketTicker(symbol,base,last,f(x.get("prevPrice24h")),f(x.get("highPrice24h")),f(x.get("lowPrice24h")),
                            f(x.get("turnover24h")),f(x.get("bid1Price")),f(x.get("ask1Price")),time.time())
