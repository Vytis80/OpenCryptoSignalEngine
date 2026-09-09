import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from storage import Storage
from ai_judge import AIJudgement


async def main():
    with tempfile.TemporaryDirectory() as td:
        dbp=Path(td)/"test.db"
        st=Storage(str(dbp),5000)
        await st.init()
        a=SimpleNamespace(
            inst_id="TESTUSDT",base="TEST",side="LONG",quality="A",score=88,
            trigger_candle_ts=1,price=100.0,entry_low=99.8,entry_high=100.2,sl=98.5,
            tp1=101.5,tp2=103,tp3=105,reasons=[],blocks=[],btc_context="BULLISH",
            eth_context="BULLISH",relative_strength=0.8,trigger_5m="CONFIRMED",
            trigger_close=100.0,analysis_delay_sec=5,stop_pct=1.5,volume_ratio_5m=1.4,
            spread_pct=0.03,estimated_cost_r=0.1,
        )
        sid=await st.create_signal(a,time.time()+900)
        j=AIJudgement(
            inst_id="TESTUSDT",checked_at=time.time(),provider="groq",model="openai/gpt-oss-120b",
            status="OK",verdict="APPROVE",confidence=83,setup_quality="A",risk="MEDIUM",
            summary="test",strengths=["x"],risks=["y"],latency_ms=900,
            prompt_tokens=1200,completion_tokens=150,total_tokens=1350,
        )
        await st.save_ai_judgement(sid,j)
        recent=await st.ai_recent(5)
        assert len(recent)==1 and recent[0]["total_tokens"]==1350
        usage=await st.ai_usage(time.time()-3600)
        assert usage["requests"]==1 and usage["prompt_tokens"]==1200
        assert usage["completion_tokens"]==150 and usage["total_tokens"]==1350
        stats=await st.ai_stats(time.time()-3600)
        assert stats and stats[0]["verdict"]=="APPROVE"
    print("OK: V2.5 AI persistence, outcome stats and Groq token usage tracking")

asyncio.run(main())
