import asyncio
import tempfile
import time
from pathlib import Path

import aiosqlite
from storage import Storage


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        storage=Storage(Path(tmp)/"edge.db");await storage.init();now=time.time()
        async with aiosqlite.connect(storage.path) as db:
            rows=[
                ("AUSDT","A","LONG",now,100,98,"CLOSED","TP3",104,1,1,1,4,-1),
                ("BUSDT","B","LONG",now,100,98,"CLOSED","SL",98,0,0,0,0,-2),
            ]
            await db.executemany("""INSERT INTO signals(
                inst_id,base,side,confirmed_at,entry,sl,status,close_reason,close_price,
                tp1_hit,tp2_hit,tp3_hit,max_gain_pct,max_drawdown_pct)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",rows)
            await db.commit()
        r=await storage.edge_stats(now-1,0.13)
        assert r["n"]==2 and r["closed_n"]==2 and r["full_sl"]==1
        assert abs(r["avg_final_r"]-0.5)<1e-9
        assert abs(r["avg_est_net_final_r"]-0.435)<1e-9
    print("OK: edge stats keep raw R and calculate display-only estimated net R")


asyncio.run(main())
