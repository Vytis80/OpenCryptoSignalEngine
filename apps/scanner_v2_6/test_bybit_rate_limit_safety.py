import asyncio
import time
from types import SimpleNamespace

from bybit import Bybit


class Response:
    status=403
    headers={}
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def text(self):return "access too frequent"


class Session:
    def __init__(self):self.calls=0
    def get(self,*args,**kwargs):self.calls+=1;return Response()


async def main():
    session=Session()
    cfg=SimpleNamespace(rest_url="https://api.bybit.com",quote="USDT",
                        bybit_min_request_interval_sec=0,bybit_retry_429_base_sec=1)
    api=Bybit(cfg,session)
    for expected_calls in (1,1):
        try:await api.get("/v5/market/time")
        except RuntimeError:pass
        else:raise AssertionError("403 did not fail")
        assert session.calls==expected_calls
    assert api.rate_limit_count==1
    assert api.ip_blocked_until-time.time()>590
    print("OK: Bybit HTTP 403 activates 10-minute fail-fast IP cooldown")


asyncio.run(main())
