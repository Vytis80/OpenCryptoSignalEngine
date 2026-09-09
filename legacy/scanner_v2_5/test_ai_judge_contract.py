import asyncio
from types import SimpleNamespace

import aiohttp

from ai_judge import AIJudge


def fake_signal():
    return SimpleNamespace(
        inst_id="TESTUSDT", base="TEST", side="LONG", status="EXECUTE", score=88, quality="A",
        price=100.0, entry_low=99.8, entry_high=100.2, sl=98.5, tp1=101.5, tp2=103.0, tp3=105.0,
        rr_tp2=2.0, bias_1h="BULLISH", setup_15m="BREAKOUT_RETEST", trigger_5m="CONFIRMED",
        btc_context="BULLISH", eth_context="BULLISH", relative_strength=0.8,
        spread_pct=0.03, volume_ratio_5m=1.45, atr_5m=0.55, fresh=True, too_late=False,
        stop_pct=1.5, estimated_cost_r=0.10, analysis_delay_sec=15,
        market_regime="TREND", regime_strength=0.8, direction_margin=18,
        funding_rate=0.0001, oi_delta_pct=0.4, reasons=["aligned"], blocks=[]
    )


async def main():
    cfg=SimpleNamespace(
        ai_judge_base_url="https://api.groq.com/openai/v1",
        ai_judge_model="openai/gpt-oss-120b",
        ai_judge_reasoning_effort="low",
        ai_judge_timeout_sec=5,
        groq_api_key="",
    )
    async with aiohttp.ClientSession() as session:
        j=AIJudge(cfg,session)
        payload=j._input(fake_signal())
        assert payload["scanner_version"]=="V2.5.1"
        assert payload["symbol"]=="TESTUSDT"
        assert "execution_quality" in payload and "smart_shadow" in payload
        result=await j.assess(fake_signal())
        assert result.status=="ERROR" and "GROQ_API_KEY" in result.error
        assert result.total_tokens==0
    print("OK: V2.5 AI Judge contract structured; missing-key path is network-free")

asyncio.run(main())
