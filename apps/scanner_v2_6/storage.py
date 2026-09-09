
import time,json,aiosqlite
from pathlib import Path
from models import ActiveSignal

class Storage:
    def __init__(self,path):self.path=Path(path)

    async def init(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS signals(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              inst_id TEXT NOT NULL, base TEXT NOT NULL, side TEXT NOT NULL,
              quality TEXT, score REAL, confirmed_at REAL NOT NULL,
              trigger_candle_ts INTEGER, entry REAL, entry_low REAL, entry_high REAL,
              sl REAL, tp1 REAL, tp2 REAL, tp3 REAL, expires_at REAL,
              status TEXT NOT NULL, tp1_hit INTEGER DEFAULT 0, tp2_hit INTEGER DEFAULT 0,
              tp3_hit INTEGER DEFAULT 0, closed_at REAL, close_reason TEXT,
              close_price REAL, max_gain_pct REAL DEFAULT 0, max_drawdown_pct REAL DEFAULT 0,
              reasons TEXT, blocks TEXT, context TEXT,
              setup_type TEXT DEFAULT 'UNKNOWN', core_version TEXT DEFAULT '2.5',
              regime_4h TEXT DEFAULT 'NEUTRAL', micro_confirmations INTEGER DEFAULT 0,
              stop_atr REAL DEFAULT 0, stop_pct REAL DEFAULT 0, obstacle_rr REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(confirmed_at);
            CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
            CREATE TABLE IF NOT EXISTS snapshots(
              signal_id INTEGER NOT NULL, horizon_min INTEGER NOT NULL,
              ts REAL NOT NULL, price REAL NOT NULL, move_pct REAL NOT NULL,
              PRIMARY KEY(signal_id,horizon_min)
            );
            CREATE TABLE IF NOT EXISTS scans(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
              markets_seen INTEGER, markets_deep INTEGER, best_json TEXT
            );
            CREATE TABLE IF NOT EXISTS shadow_checks(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL, checked_at REAL NOT NULL,
              would_block INTEGER NOT NULL, status TEXT NOT NULL, reasons TEXT,
              suggested_sl REAL, suggested_sl_atr REAL, micro_momentum_pct REAL
            );
            CREATE TABLE IF NOT EXISTS ai_judgements(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL, checked_at REAL NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
              verdict TEXT, confidence INTEGER, setup_quality TEXT, risk TEXT,
              summary TEXT, strengths TEXT, risks TEXT, latency_ms INTEGER DEFAULT 0,
              error TEXT, prompt_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_time ON ai_judgements(checked_at);
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_verdict ON ai_judgements(verdict);
            """)
            cols={r[1] for r in await (await db.execute("PRAGMA table_info(signals)")).fetchall()}
            migrations={
                "setup_type":"TEXT DEFAULT 'UNKNOWN'",
                "core_version":"TEXT DEFAULT '2.5'",
                "regime_4h":"TEXT DEFAULT 'NEUTRAL'",
                "micro_confirmations":"INTEGER DEFAULT 0",
                "stop_atr":"REAL DEFAULT 0",
                "stop_pct":"REAL DEFAULT 0",
                "obstacle_rr":"REAL DEFAULT 0",
            }
            for name,kind in migrations.items():
                if name not in cols:
                    await db.execute(f"ALTER TABLE signals ADD COLUMN {name} {kind}")
            await db.commit()

    async def create_signal(self,a,expires):
        ctx=json.dumps({"btc":a.btc_context,"eth":a.eth_context,"rs":a.relative_strength},ensure_ascii=False)
        async with aiosqlite.connect(self.path) as db:
            c=await db.execute("""INSERT INTO signals(
                inst_id,base,side,quality,score,confirmed_at,trigger_candle_ts,
                entry,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,status,reasons,blocks,context,setup_type,
                core_version,regime_4h,micro_confirmations,stop_atr,stop_pct,obstacle_rr
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?,?,?,?,?,?,?,?,?,?)""",
              (a.inst_id,a.base,a.side,a.quality,a.score,time.time(),a.trigger_candle_ts,
               a.price,a.entry_low,a.entry_high,a.sl,a.tp1,a.tp2,a.tp3,expires,
               json.dumps(a.reasons,ensure_ascii=False),json.dumps(a.blocks,ensure_ascii=False),ctx,a.trigger_5m,
               getattr(a,"core_version","2.5"),getattr(a,"regime_4h","NEUTRAL"),
               getattr(a,"micro_confirmations",0),getattr(a,"stop_atr",0.0),
               getattr(a,"stop_pct",0.0),getattr(a,"obstacle_rr",0.0)))
            await db.commit();return c.lastrowid

    async def mark_tp(self,sid,n):
        col={1:"tp1_hit",2:"tp2_hit",3:"tp3_hit"}[n]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE signals SET {col}=1 WHERE id=?",(sid,));await db.commit()

    async def close_signal(self,sid,reason,price):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""UPDATE signals SET status='CLOSED',closed_at=?,close_reason=?,close_price=? WHERE id=?""",
                             (time.time(),reason,price,sid));await db.commit()

    async def update_excursion(self,sid,gain,dd):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""UPDATE signals SET max_gain_pct=MAX(max_gain_pct,?),max_drawdown_pct=MIN(max_drawdown_pct,?) WHERE id=?""",
                             (gain,dd,sid));await db.commit()

    async def update_entry_window(self,sid,expires_at):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE signals SET expires_at=? WHERE id=?",(expires_at,sid));await db.commit()

    async def save_shadow(self,sid,assessment):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""INSERT INTO shadow_checks(signal_id,inst_id,checked_at,would_block,status,reasons,suggested_sl,suggested_sl_atr,micro_momentum_pct)
              VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(signal_id) DO UPDATE SET checked_at=excluded.checked_at,would_block=excluded.would_block,status=excluded.status,
                reasons=excluded.reasons,suggested_sl=excluded.suggested_sl,suggested_sl_atr=excluded.suggested_sl_atr,micro_momentum_pct=excluded.micro_momentum_pct""",
              (sid,assessment.inst_id,assessment.checked_at,int(assessment.would_block),assessment.status,
               json.dumps(assessment.reasons,ensure_ascii=False),assessment.suggested_sl,assessment.suggested_sl_atr,assessment.micro_momentum_pct))
            await db.commit()

    async def shadow_for_signal(self,sid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("SELECT * FROM shadow_checks WHERE signal_id=?",(sid,));r=await c.fetchone()
            return dict(r) if r else None

    async def save_ai_judgement(self,sid,j):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""INSERT INTO ai_judgements(
              signal_id,inst_id,checked_at,provider,model,status,verdict,confidence,setup_quality,risk,
              summary,strengths,risks,latency_ms,error,prompt_version
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(signal_id) DO UPDATE SET checked_at=excluded.checked_at,provider=excluded.provider,
                model=excluded.model,status=excluded.status,verdict=excluded.verdict,confidence=excluded.confidence,
                setup_quality=excluded.setup_quality,risk=excluded.risk,summary=excluded.summary,
                strengths=excluded.strengths,risks=excluded.risks,latency_ms=excluded.latency_ms,
                error=excluded.error,prompt_version=excluded.prompt_version""",
              (sid,j.inst_id,j.checked_at,j.provider,j.model,j.status,j.verdict,j.confidence,j.setup_quality,j.risk,
               j.summary,json.dumps(j.strengths,ensure_ascii=False),json.dumps(j.risks,ensure_ascii=False),
               j.latency_ms,j.error,j.prompt_version))
            await db.commit()

    async def ai_recent(self,limit=5):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT j.*,s.side,s.quality scanner_quality,s.score scanner_score,
              s.status signal_status,s.close_reason,s.tp1_hit,s.tp2_hit,s.tp3_hit,s.max_gain_pct,s.max_drawdown_pct
              FROM ai_judgements j JOIN signals s ON s.id=j.signal_id
              ORDER BY j.checked_at DESC LIMIT ?""",(limit,))
            return [dict(x) for x in await c.fetchall()]

    async def ai_stats(self,since):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT j.status,j.verdict,COUNT(*) n,
              SUM(s.status='CLOSED') closed_n,SUM(s.close_reason='SL') sl,
              SUM(s.close_reason='SL' AND s.tp1_hit=0) full_sl,
              SUM(s.tp1_hit=1) tp1,SUM(s.tp2_hit=1) tp2,SUM(s.tp3_hit=1) tp3,
              AVG(j.confidence) avg_confidence,AVG(j.latency_ms) avg_latency_ms,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN s.max_gain_pct/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN ABS(s.max_drawdown_pct)/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mae_r
              FROM ai_judgements j JOIN signals s ON s.id=j.signal_id
              WHERE s.confirmed_at>=? GROUP BY j.status,j.verdict ORDER BY j.status,j.verdict""",(since,))
            return [dict(x) for x in await c.fetchall()]

    async def load_active(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("SELECT * FROM signals WHERE status='ACTIVE'")
            out=[]
            for r in await c.fetchall():
                x=dict(r)
                out.append(ActiveSignal(
                    x["id"],x["inst_id"],x["base"],x["side"],x["quality"] or "",x["score"] or 0,
                    x["confirmed_at"],x["entry"],x["entry_low"],x["entry_high"],x["sl"],x["tp1"],x["tp2"],x["tp3"],
                    x["expires_at"],bool(x["tp1_hit"]),bool(x["tp2_hit"]),bool(x["tp3_hit"]),"ACTIVE",
                    x["close_price"] or x["entry"],x["max_gain_pct"] or 0,x["max_drawdown_pct"] or 0,
                    False,x.get("setup_type") or "UNKNOWN"
                ))
            return out

    async def recent(self,limit=10):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row;c=await db.execute("SELECT * FROM signals ORDER BY confirmed_at DESC LIMIT ?",(limit,))
            return [dict(x) for x in await c.fetchall()]

    async def last_confirmed(self,inst_id):
        async with aiosqlite.connect(self.path) as db:
            c=await db.execute("SELECT confirmed_at,trigger_candle_ts FROM signals WHERE inst_id=? ORDER BY confirmed_at DESC LIMIT 1",(inst_id,));r=await c.fetchone()
            return (r[0],r[1]) if r else (0,None)

    async def snapshot_done(self,sid):
        async with aiosqlite.connect(self.path) as db:
            c=await db.execute("SELECT horizon_min FROM snapshots WHERE signal_id=?",(sid,));return {int(x[0]) for x in await c.fetchall()}

    async def snapshot(self,sid,h,price,move):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?)",(sid,h,time.time(),price,move));await db.commit()

    async def save_scan(self,seen,deep,best):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO scans(ts,markets_seen,markets_deep,best_json) VALUES(?,?,?,?)",
                             (time.time(),seen,deep,json.dumps(best,ensure_ascii=False)));await db.commit()

    async def stats(self,since):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT COUNT(*) n,
              SUM(close_reason='TP3') tp3,SUM(close_reason='SL') sl,SUM(close_reason='EXPIRED') expired,
              SUM(close_reason='INVALIDATED') invalidated,SUM(close_reason='CLOSE_EARLY') close_early,
              SUM(tp1_hit=1) tp1,SUM(tp2_hit=1) tp2,
              AVG(max_gain_pct) avg_gain,AVG(max_drawdown_pct) avg_dd,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN max_gain_pct/(ABS(entry-sl)/entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN ABS(max_drawdown_pct)/(ABS(entry-sl)/entry*100.0) END) avg_mae_r,
              SUM(side='LONG') longs,SUM(side='SHORT') shorts
              FROM signals WHERE confirmed_at>=?""",(since,));r=await c.fetchone();return dict(r) if r else {}

    async def report_stats(self,since):
        """Clear, non-overlapping lifecycle stats for Discord reporting."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT side,status,close_reason,tp1_hit,tp2_hit,tp3_hit,
                                  entry,sl,close_price,max_gain_pct,max_drawdown_pct
                                  FROM signals WHERE confirmed_at>=?""",(since,))
            rows=await c.fetchall()

        r={
            "n":len(rows),"longs":0,"shorts":0,"closed_n":0,"active_n":0,
            "tp1":0,"tp2":0,"tp3":0,"tp3_finish":0,
            "sl_all":0,"full_sl":0,"sl_after_tp":0,
            "tp1_to_sl":0,"tp2_to_sl":0,
            "invalidated":0,"expired":0,"close_early":0,"other_closed":0,
        }

        gains=[]
        dds=[]
        mfe=[]
        mae=[]
        final_rs=[]

        for x in rows:
            side=(x["side"] or "").upper()
            status=(x["status"] or "").upper()
            reason=(x["close_reason"] or "").upper()

            tp1=bool(x["tp1_hit"])
            tp2=bool(x["tp2_hit"])
            tp3=bool(x["tp3_hit"])

            r["longs"]+=int(side=="LONG")
            r["shorts"]+=int(side=="SHORT")
            r["closed_n"]+=int(status=="CLOSED")
            r["active_n"]+=int(status=="ACTIVE")

            r["tp1"]+=int(tp1)
            r["tp2"]+=int(tp2)
            r["tp3"]+=int(tp3)

            if status=="CLOSED":
                if reason=="TP3":
                    r["tp3_finish"]+=1

                elif reason=="SL":
                    r["sl_all"]+=1

                    if tp1:
                        r["sl_after_tp"]+=1

                        if tp2:
                            r["tp2_to_sl"]+=1
                        else:
                            r["tp1_to_sl"]+=1
                    else:
                        r["full_sl"]+=1

                elif reason=="INVALIDATED":
                    r["invalidated"]+=1

                elif reason=="EXPIRED":
                    r["expired"]+=1

                elif reason=="CLOSE_EARLY":
                    r["close_early"]+=1

                else:
                    r["other_closed"]+=1

            if x["max_gain_pct"] is not None:
                gains.append(float(x["max_gain_pct"]))

            if x["max_drawdown_pct"] is not None:
                dds.append(float(x["max_drawdown_pct"]))

            entry=float(x["entry"] or 0)
            sl=float(x["sl"] or 0)
            risk=abs(entry-sl)

            if entry>0 and risk>0:
                risk_pct=risk/entry*100.0

                if x["max_gain_pct"] is not None:
                    mfe.append(float(x["max_gain_pct"])/risk_pct)

                if x["max_drawdown_pct"] is not None:
                    mae.append(abs(float(x["max_drawdown_pct"]))/risk_pct)

                if status=="CLOSED" and x["close_price"] is not None:
                    cp=float(x["close_price"])

                    if side=="LONG":
                        fr=(cp-entry)/risk
                    else:
                        fr=(entry-cp)/risk

                    final_rs.append(fr)

        def avg(xs):
            return sum(xs)/len(xs) if xs else 0.0

        wins=[v for v in final_rs if v>0]
        losses=[v for v in final_rs if v<0]

        gross_win=sum(wins)
        gross_loss=abs(sum(losses))

        if gross_loss>0:
            pf=gross_win/gross_loss
        elif gross_win>0:
            pf=float("inf")
        else:
            pf=None

        r.update({
            "avg_gain":avg(gains),
            "avg_dd":avg(dds),
            "avg_mfe_r":avg(mfe),
            "avg_mae_r":avg(mae),
            "avg_final_r":avg(final_rs),
            "best_final_r":max(final_rs) if final_rs else 0.0,
            "worst_final_r":min(final_rs) if final_rs else 0.0,
            "profit_factor":pf,
            "final_r_n":len(final_rs),
        })

        return r

    async def setup_stats(self,since,min_n=1):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT COALESCE(setup_type,'UNKNOWN') setup_type,COUNT(*) n,
              SUM(close_reason='SL') sl,SUM(close_reason='SL' AND tp1_hit=0) full_sl,
              SUM(close_reason='CLOSE_EARLY') close_early,SUM(status='CLOSED') closed_n,
              SUM(tp1_hit=1) tp1,SUM(tp2_hit=1) tp2,SUM(tp3_hit=1) tp3,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN max_gain_pct/(ABS(entry-sl)/entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN ABS(max_drawdown_pct)/(ABS(entry-sl)/entry*100.0) END) avg_mae_r,
              AVG(CASE WHEN status='CLOSED' AND ABS(entry-sl)>0 AND close_price IS NOT NULL
                THEN CASE WHEN side='LONG' THEN (close_price-entry)/ABS(entry-sl) ELSE (entry-close_price)/ABS(entry-sl) END END) avg_final_r
              FROM signals WHERE confirmed_at>=? GROUP BY COALESCE(setup_type,'UNKNOWN')
              HAVING COUNT(*)>=? ORDER BY n DESC""",(since,min_n));return [dict(x) for x in await c.fetchall()]

    async def shadow_stats(self,since):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT sh.would_block,COUNT(*) n,
              SUM(s.close_reason='SL') sl,SUM(s.close_reason='SL' AND s.tp1_hit=0) full_sl,
              SUM(s.tp1_hit=1) tp1,SUM(s.tp2_hit=1) tp2,SUM(s.tp3_hit=1) tp3,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN s.max_gain_pct/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN ABS(s.max_drawdown_pct)/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mae_r
              FROM shadow_checks sh JOIN signals s ON s.id=sh.signal_id
              WHERE s.confirmed_at>=? GROUP BY sh.would_block ORDER BY sh.would_block""",(since,));return [dict(x) for x in await c.fetchall()]

    async def ping(self):
        try:
            async with aiosqlite.connect(self.path) as db:
                c=await db.execute("SELECT 1");r=await c.fetchone()
                return bool(r and r[0]==1)
        except Exception:
            return False

    async def edge_stats(self,since,roundtrip_cost_pct=0.0):
        """Lifecycle edge metrics; estimated costs never alter live signals."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT COUNT(*) n,
              SUM(status='CLOSED') closed_n,SUM(status='ACTIVE') active_n,
              SUM(tp1_hit=1) tp1,SUM(tp2_hit=1) tp2,SUM(tp3_hit=1) tp3,
              SUM(close_reason='SL') sl,SUM(close_reason='SL' AND tp1_hit=0) full_sl,
              SUM(close_reason='INVALIDATED') invalidated,SUM(close_reason='CLOSE_EARLY') close_early,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN max_gain_pct/(ABS(entry-sl)/entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN ABS(max_drawdown_pct)/(ABS(entry-sl)/entry*100.0) END) avg_mae_r,
              AVG(CASE WHEN status='CLOSED' AND ABS(entry-sl)>0 AND close_price IS NOT NULL
                THEN CASE WHEN side='LONG' THEN (close_price-entry)/ABS(entry-sl) ELSE (entry-close_price)/ABS(entry-sl) END END) avg_final_r,
              AVG(CASE WHEN status='CLOSED' AND entry>0 AND ABS(entry-sl)>0 AND close_price IS NOT NULL
                THEN (CASE WHEN side='LONG' THEN (close_price-entry)/ABS(entry-sl) ELSE (entry-close_price)/ABS(entry-sl) END)
                     - (?/(ABS(entry-sl)/entry*100.0)) END) avg_est_net_final_r
              FROM signals WHERE confirmed_at>=?""",(roundtrip_cost_pct,since));r=await c.fetchone()
            return dict(r) if r else {}

    async def setup_edge(self,since,setup_type,side,roundtrip_cost_pct=0.0,
                         tp_fractions=(0.40,0.30,0.30),core_version="2.6"):
        """Closed-trade expectancy for the exact setup/side/core.

        Net R uses the demo trader's default 40/30/30 TP split and subtracts
        one estimated round-trip cost expressed in each trade's initial R.
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT side,entry,sl,close_price,tp1_hit,tp2_hit,tp3_hit,close_reason
              FROM signals WHERE confirmed_at>=? AND status='CLOSED'
                AND COALESCE(setup_type,'UNKNOWN')=? AND side=?
                AND COALESCE(core_version,'2.5')=?""",
                (since,setup_type,side,core_version))
            rows=[dict(x) for x in await c.fetchall()]
        f1,f2,f3=tp_fractions
        total=f1+f2+f3
        if total<=0:f1,f2,f3,total=.40,.30,.30,1.0
        f1,f2,f3=f1/total,f2/total,f3/total
        net=[];gross=[];full_sl=0;tp2=0
        for r in rows:
            entry=float(r.get("entry") or 0);sl=float(r.get("sl") or 0)
            close=float(r.get("close_price") or 0);risk=abs(entry-sl)
            if entry<=0 or risk<=0 or close<=0:continue
            final_r=((close-entry)/risk) if side=="LONG" else ((entry-close)/risk)
            if r.get("tp3_hit"):g=f1*1+f2*2+f3*3
            elif r.get("tp2_hit"):g=f1*1+f2*2+f3*final_r
            elif r.get("tp1_hit"):g=f1*1+(f2+f3)*final_r
            else:g=final_r
            stop_pct=risk/entry*100
            cost_r=roundtrip_cost_pct/stop_pct if stop_pct>0 else 0.0
            gross.append(g);net.append(g-cost_r)
            full_sl+=int(r.get("close_reason")=="SL" and not r.get("tp1_hit"))
            tp2+=int(bool(r.get("tp2_hit")))
        n=len(net)
        avg=lambda xs:sum(xs)/len(xs) if xs else 0.0
        return {
            "n":n,"avg_gross_r":avg(gross),"avg_net_r":avg(net),
            "full_sl_rate":full_sl/n if n else 0.0,
            "tp2_rate":tp2/n if n else 0.0,
        }

    async def performance(self,since):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT s.horizon_min,COUNT(*) n,AVG(s.move_pct) avg_move,
              SUM(s.move_pct>0) positive,SUM(s.move_pct>=1) hit1,SUM(s.move_pct>=2) hit2,SUM(s.move_pct<=-1) loss1
              FROM snapshots s JOIN signals g ON g.id=s.signal_id
              WHERE g.confirmed_at>=? GROUP BY s.horizon_min ORDER BY s.horizon_min""",(since,));return [dict(x) for x in await c.fetchall()]
