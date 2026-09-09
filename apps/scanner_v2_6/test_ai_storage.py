import asyncio,tempfile,time
from pathlib import Path
import aiosqlite

from storage import Storage
from ai_judge import AIJudgement


async def main():
    with tempfile.TemporaryDirectory() as td:
        dbp=Path(td)/"test.db"
        s=Storage(dbp);await s.init()
        now=time.time()
        async with aiosqlite.connect(dbp) as db:
            await db.execute("""INSERT INTO signals(id,inst_id,base,side,quality,score,confirmed_at,entry,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,status,tp1_hit,tp2_hit,tp3_hit,close_reason,max_gain_pct,max_drawdown_pct)
                              VALUES(1,'TESTUSDT','TEST','LONG','A',88,?,100,99.8,100.2,99,101,102,103,?,'CLOSED',1,1,0,'SL',2.2,-1.0)""",(now,now+900))
            await db.commit()
        j=AIJudgement('TESTUSDT',now,'groq','openai/gpt-oss-120b','OK','APPROVE',87,'A','LOW','Strong alignment',['trend'],['resistance'],321)
        await s.save_ai_judgement(1,j)
        recent=await s.ai_recent(5)
        assert len(recent)==1 and recent[0]['verdict']=='APPROVE' and recent[0]['confidence']==87
        rows=await s.ai_stats(now-60)
        assert len(rows)==1 and rows[0]['n']==1 and rows[0]['tp2']==1 and rows[0]['sl']==1
        print("OK: AI judgement persistence, recent view and outcome stats")


asyncio.run(main())
