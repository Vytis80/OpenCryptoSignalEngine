import asyncio,time
from types import SimpleNamespace
from bybit import Bybit

class FakeBybit(Bybit):
    def __init__(self):
        cfg=SimpleNamespace(quote='USDT',bybit_min_request_interval_sec=0,bybit_retry_429_base_sec=1,rest_url='https://api.bybit.com')
        super().__init__(cfg,None)
    async def get(self,path,params=None,retries=3):
        params=params or {}
        if path.endswith('/instruments-info'):
            if not params.get('cursor'):
                return {'list':[
                    {'symbol':'BTCUSDT','baseCoin':'BTC','quoteCoin':'USDT','settleCoin':'USDT','contractType':'LinearPerpetual','status':'Trading'},
                    {'symbol':'BTCUSDT-30DEC30','baseCoin':'BTC','quoteCoin':'USDT','settleCoin':'USDT','contractType':'LinearFutures','status':'Trading'},
                    {'symbol':'ETHUSDC','baseCoin':'ETH','quoteCoin':'USDC','settleCoin':'USDC','contractType':'LinearPerpetual','status':'Trading'},
                ],'nextPageCursor':'next'}
            return {'list':[{'symbol':'SUIUSDT','baseCoin':'SUI','quoteCoin':'USDT','settleCoin':'USDT','contractType':'LinearPerpetual','status':'Trading'}],'nextPageCursor':''}
        if path.endswith('/tickers'):
            if params.get('symbol'):
                return {'list':[{'symbol':'BTCUSDT','lastPrice':'100','prevPrice24h':'98','highPrice24h':'105','lowPrice24h':'95','turnover24h':'1234567','bid1Price':'99.9','ask1Price':'100.1'}]}
            return {'list':[
                {'symbol':'BTCUSDT','lastPrice':'100','prevPrice24h':'98','highPrice24h':'105','lowPrice24h':'95','turnover24h':'1234567','bid1Price':'99.9','ask1Price':'100.1'},
                {'symbol':'SUIUSDT','lastPrice':'1','prevPrice24h':'0.9','highPrice24h':'1.1','lowPrice24h':'0.8','turnover24h':'5000000','bid1Price':'0.999','ask1Price':'1.001'},
                {'symbol':'BTCUSDT-30DEC30','lastPrice':'100','prevPrice24h':'98','highPrice24h':'105','lowPrice24h':'95','turnover24h':'9999999','bid1Price':'99','ask1Price':'101'},
            ]}
        if path.endswith('/kline'):
            interval={'1':60_000,'5':300_000,'15':900_000,'60':3_600_000}[params['interval']]
            now=int(time.time()*1000);cur=(now//interval)*interval;prev=cur-interval
            return {'list':[
                [str(cur),'100','101','99','100.5','10','1005'],
                [str(prev),'99','101','98','100','20','2000'],
            ]}
        raise AssertionError((path,params))

async def main():
    b=FakeBybit()
    live=await b.live_perpetuals()
    assert live=={'BTCUSDT':'BTC','SUIUSDT':'SUI'}, live
    ticks=await b.tickers()
    assert set(ticks)==set(live), ticks.keys()
    assert ticks['BTCUSDT'].quote_vol_24h==1234567
    assert abs(ticks['BTCUSDT'].spread_pct-0.2)<1e-9
    tk=await b.ticker('BTCUSDT');assert tk and tk.base=='BTC'
    closed=await b.candles('BTCUSDT','5m',2)
    livebars=await b.candles_live('BTCUSDT','5m',2)
    assert len(closed)==1 and closed[0].confirm
    assert len(livebars)==2 and livebars[-1].confirm is False
    print('OK: Bybit adapter pagination/filter/ticker/confirmed-candle semantics passed')

asyncio.run(main())
