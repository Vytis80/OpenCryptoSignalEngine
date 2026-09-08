import asyncio
import alerts


class Response:
    def __init__(self,status):self.status=status;self.headers={}
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def text(self):return "temporary"


class Session:
    def __init__(self):self.statuses=[500,204];self.calls=0
    def post(self,*args,**kwargs):
        self.calls+=1
        return Response(self.statuses.pop(0))


async def main():
    session=Session();original_sleep=alerts.asyncio.sleep
    async def no_sleep(*args,**kwargs):pass
    alerts.asyncio.sleep=no_sleep
    try:ok=await alerts._post(session,"https://example.invalid","scanner",{"title":"test"})
    finally:alerts.asyncio.sleep=original_sleep
    assert ok and session.calls==2
    print("OK: Discord webhook retries a transient server error and recovers")


asyncio.run(main())
