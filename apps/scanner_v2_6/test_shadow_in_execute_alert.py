import asyncio
from types import SimpleNamespace
import alerts

async def main():
    captured={}
    async def fake_post(session,url,username,embed):
        captured["embed"]=embed
        return True
    alerts._post=fake_post
    a=SimpleNamespace(
        side="LONG",inst_id="TESTUSDT",quality="A",score=84,
        reasons=["trend aligned"],blocks=[],entry_low=100,entry_high=101,sl=98,
        tp1=103,tp2=105,tp3=107,bias_1h="BULLISH",setup_15m="BULLISH",
        trigger_5m="BREAKOUT + RETEST",btc_context="NEUTRAL",eth_context="BULLISH",
        relative_strength=1.2,volume_ratio_5m=1.5,spread_pct=0.02,rr_tp2=2.0,
    )
    cfg=SimpleNamespace(discord_webhook_url="x",discord_username="x")
    sh=SimpleNamespace(status="WOULD_BLOCK",reasons=["1m momentum weak","5m volatility spike"])
    ok=await alerts.execute_alert(None,cfg,a,9999999999,sh)
    assert ok
    fields=captured["embed"]["fields"]
    sf=[x for x in fields if x["name"]=="Shadow"]
    assert len(sf)==1
    assert "WOULD BLOCK" in sf[0]["value"]
    assert "Observational only" in sf[0]["value"]
    print("OK: SHADOW verdict is embedded in EXECUTE alert only")

asyncio.run(main())
