import asyncio
from types import SimpleNamespace

from ai_judge import AIJudge


class DummySession:
    def post(self,*a,**k):
        raise AssertionError("network must not be called when key is missing")


class Cfg:
    ai_judge_base_url="https://api.groq.com/openai/v1"
    ai_judge_model="openai/gpt-oss-120b"
    ai_judge_reasoning_effort="low"
    ai_judge_timeout_sec=5
    groq_api_key=""


def analysis():
    return SimpleNamespace(
        inst_id="TESTUSDT",side="LONG",status="EXECUTE",score=88,quality="A",
        price=100.0,entry_low=99.8,entry_high=100.2,sl=99.0,tp1=101.0,tp2=102.0,tp3=103.0,rr_tp2=2.0,
        regime_4h="BULLISH",bias_1h="BULLISH",setup_15m="BULLISH / HH_HL",trigger_5m="PULLBACK REACTION",
        micro_1m="BULLISH",micro_confirmations=3,btc_context="BULLISH",eth_context="BULLISH",
        relative_strength=.4,spread_pct=.02,volume_ratio_5m=1.4,atr_5m_pct=.8,stop_atr=1.0,stop_pct=1.0,
        obstacle_rr=2.3,fresh=True,too_late=False,edge_label="COLLECTING",edge_sample=5,edge_net_r=0.2,
        edge_tp2_rate=.4,reasons=["aligned"],blocks=[],audit_evidence={"version":"v26-audit1"},core_version="2.6"
    )


async def main():
    j=AIJudge(Cfg(),DummySession())
    a=analysis()
    payload=j._input(a)
    assert payload["symbol"]=="TESTUSDT" and payload["structure"]["1m_confirmations"]==3
    schema=j._schema()["schema"]
    assert schema["additionalProperties"] is False
    r=await j.assess(a)
    assert r.status=="ERROR" and "GROQ_API_KEY" in r.error
    print("OK: AI Judge contract is structured and missing-key path is network-free")


asyncio.run(main())
