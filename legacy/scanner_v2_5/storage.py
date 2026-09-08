
import time,json,aiosqlite
from pathlib import Path
from models import ActiveSignal

class Storage:
    def __init__(self,path,busy_timeout_ms=5000):
        self.path=Path(path);self.busy_timeout_ms=max(100,int(busy_timeout_ms))

    def _connect(self):
        return aiosqlite.connect(self.path,timeout=self.busy_timeout_ms/1000.0)

    async def init(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        async with self._connect() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
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
              trigger_close REAL DEFAULT 0, analysis_delay_sec REAL DEFAULT 0,
              stop_pct REAL DEFAULT 0, volume_ratio_5m REAL DEFAULT 0,
              relative_strength REAL DEFAULT 0, spread_pct REAL DEFAULT 0,
              estimated_cost_r REAL DEFAULT 0
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
              suggested_sl REAL, suggested_sl_atr REAL, micro_momentum_pct REAL,
              estimated_cost_r REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bridge_outbox(
              event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
              attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
              last_error TEXT, created_at REAL NOT NULL, delivered_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_bridge_outbox_pending
              ON bridge_outbox(status,next_attempt_at);
            CREATE TABLE IF NOT EXISTS smart_signal_checks(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL,
              checked_at REAL NOT NULL, verdict TEXT NOT NULL, smart_score REAL NOT NULL,
              setup_family TEXT NOT NULL, regime TEXT NOT NULL,
              confidence_margin REAL NOT NULL, reasons TEXT,
              suggested_entry_low REAL, suggested_entry_high REAL, suggested_sl REAL,
              features_json TEXT NOT NULL, model_version TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_smart_signal_verdict
              ON smart_signal_checks(verdict,checked_at);
            CREATE TABLE IF NOT EXISTS smart_management_checks(
              signal_id INTEGER NOT NULL, inst_id TEXT NOT NULL,
              candle_ts INTEGER NOT NULL, checked_at REAL NOT NULL,
              action TEXT NOT NULL, health_score REAL NOT NULL,
              current_r REAL NOT NULL, max_r REAL NOT NULL, giveback_r REAL NOT NULL,
              regime TEXT NOT NULL, reasons TEXT, features_json TEXT NOT NULL,
              model_version TEXT NOT NULL,
              PRIMARY KEY(signal_id,candle_ts)
            );
            CREATE INDEX IF NOT EXISTS idx_smart_management_action
              ON smart_management_checks(action,checked_at);
            CREATE TABLE IF NOT EXISTS smart_management_state(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL,
              checked_at REAL NOT NULL, candle_ts INTEGER NOT NULL,
              action TEXT NOT NULL, health_score REAL NOT NULL,
              current_r REAL NOT NULL, max_r REAL NOT NULL, giveback_r REAL NOT NULL,
              regime TEXT NOT NULL, reasons TEXT, features_json TEXT NOT NULL,
              model_version TEXT NOT NULL
            );
            """)
            cols={r[1] for r in await (await db.execute("PRAGMA table_info(signals)")).fetchall()}
            migrations={
              "setup_type":"TEXT DEFAULT 'UNKNOWN'",
              "trigger_close":"REAL DEFAULT 0",
              "analysis_delay_sec":"REAL DEFAULT 0",
              "stop_pct":"REAL DEFAULT 0",
              "volume_ratio_5m":"REAL DEFAULT 0",
              "relative_strength":"REAL DEFAULT 0",
              "spread_pct":"REAL DEFAULT 0",
              "estimated_cost_r":"REAL DEFAULT 0",
            }
            for name,sql_type in migrations.items():
                if name not in cols:
                    await db.execute(f"ALTER TABLE signals ADD COLUMN {name} {sql_type}")
            shadow_cols={r[1] for r in await (await db.execute("PRAGMA table_info(shadow_checks)")).fetchall()}
            if "estimated_cost_r" not in shadow_cols:
                await db.execute("ALTER TABLE shadow_checks ADD COLUMN estimated_cost_r REAL DEFAULT 0")
            await db.commit()

    async def create_signal(self,a,expires,confirmed_at=None):
        ctx=json.dumps({"btc":a.btc_context,"eth":a.eth_context,"rs":a.relative_strength},ensure_ascii=False)
        confirmed_at=float(confirmed_at if confirmed_at is not None else time.time())
        async with self._connect() as db:
            c=await db.execute("""INSERT INTO signals(
                inst_id,base,side,quality,score,confirmed_at,trigger_candle_ts,
                entry,entry_low,entry_high,sl,tp1,tp2,tp3,expires_at,status,reasons,blocks,context,setup_type,
                trigger_close,analysis_delay_sec,stop_pct,volume_ratio_5m,relative_strength,spread_pct,estimated_cost_r
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?,?,?,?,?,?,?,?,?,?,?)""",
              (a.inst_id,a.base,a.side,a.quality,a.score,confirmed_at,a.trigger_candle_ts,
               a.price,a.entry_low,a.entry_high,a.sl,a.tp1,a.tp2,a.tp3,expires,
               json.dumps(a.reasons,ensure_ascii=False),json.dumps(a.blocks,ensure_ascii=False),ctx,a.trigger_5m,
               a.trigger_close,a.analysis_delay_sec,a.stop_pct,a.volume_ratio_5m,a.relative_strength,a.spread_pct,
               a.estimated_cost_r))
            await db.commit();return c.lastrowid

    async def mark_tp(self,sid,n):
        col={1:"tp1_hit",2:"tp2_hit",3:"tp3_hit"}[n]
        async with self._connect() as db:
            await db.execute(f"UPDATE signals SET {col}=1 WHERE id=?",(sid,));await db.commit()

    async def close_signal(self,sid,reason,price):
        async with self._connect() as db:
            await db.execute("""UPDATE signals SET status='CLOSED',closed_at=?,close_reason=?,close_price=? WHERE id=?""",
                             (time.time(),reason,price,sid));await db.commit()

    async def update_excursion(self,sid,gain,dd):
        async with self._connect() as db:
            await db.execute("""UPDATE signals SET max_gain_pct=MAX(max_gain_pct,?),max_drawdown_pct=MIN(max_drawdown_pct,?) WHERE id=?""",
                             (gain,dd,sid));await db.commit()

    async def update_entry_window(self,sid,expires_at):
        async with self._connect() as db:
            await db.execute("UPDATE signals SET expires_at=? WHERE id=?",(expires_at,sid));await db.commit()

    async def save_shadow(self,sid,assessment):
        async with self._connect() as db:
            await db.execute("""INSERT INTO shadow_checks(signal_id,inst_id,checked_at,would_block,status,reasons,suggested_sl,suggested_sl_atr,micro_momentum_pct,estimated_cost_r)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(signal_id) DO UPDATE SET checked_at=excluded.checked_at,would_block=excluded.would_block,status=excluded.status,
                reasons=excluded.reasons,suggested_sl=excluded.suggested_sl,suggested_sl_atr=excluded.suggested_sl_atr,
                micro_momentum_pct=excluded.micro_momentum_pct,estimated_cost_r=excluded.estimated_cost_r""",
              (sid,assessment.inst_id,assessment.checked_at,int(assessment.would_block),assessment.status,
               json.dumps(assessment.reasons,ensure_ascii=False),assessment.suggested_sl,assessment.suggested_sl_atr,
               assessment.micro_momentum_pct,assessment.estimated_cost_r))
            await db.commit()

    async def shadow_for_signal(self,sid):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("SELECT * FROM shadow_checks WHERE signal_id=?",(sid,));r=await c.fetchone()
            return dict(r) if r else None

    async def save_smart_signal(self,sid,assessment):
        async with self._connect() as db:
            await db.execute("""INSERT INTO smart_signal_checks(
              signal_id,inst_id,checked_at,verdict,smart_score,setup_family,regime,
              confidence_margin,reasons,suggested_entry_low,suggested_entry_high,
              suggested_sl,features_json,model_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id) DO UPDATE SET
              checked_at=excluded.checked_at,verdict=excluded.verdict,
              smart_score=excluded.smart_score,setup_family=excluded.setup_family,
              regime=excluded.regime,confidence_margin=excluded.confidence_margin,
              reasons=excluded.reasons,suggested_entry_low=excluded.suggested_entry_low,
              suggested_entry_high=excluded.suggested_entry_high,
              suggested_sl=excluded.suggested_sl,features_json=excluded.features_json,
              model_version=excluded.model_version""",
              (sid,assessment.inst_id,assessment.checked_at,assessment.verdict,assessment.score,
               assessment.setup_family,assessment.regime,assessment.confidence_margin,
               json.dumps(assessment.reasons,ensure_ascii=False),assessment.suggested_entry_low,
               assessment.suggested_entry_high,assessment.suggested_sl,
               json.dumps(assessment.feature_payload(),separators=(",",":"),ensure_ascii=False),
               assessment.model_version))
            await db.commit()

    async def smart_for_signal(self,sid):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("SELECT * FROM smart_signal_checks WHERE signal_id=?",(sid,))
            r=await c.fetchone();return dict(r) if r else None

    async def save_smart_management(self,assessment):
        values=(assessment.signal_id,assessment.inst_id,assessment.candle_ts,
                assessment.checked_at,assessment.action,assessment.health_score,
                assessment.current_r,assessment.max_r,assessment.giveback_r,
                assessment.regime,json.dumps(assessment.reasons,ensure_ascii=False),
                json.dumps(assessment.features,separators=(",",":"),ensure_ascii=False),
                assessment.model_version)
        async with self._connect() as db:
            await db.execute("""INSERT INTO smart_management_checks(
              signal_id,inst_id,candle_ts,checked_at,action,health_score,current_r,
              max_r,giveback_r,regime,reasons,features_json,model_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id,candle_ts) DO UPDATE SET
              checked_at=excluded.checked_at,action=excluded.action,
              health_score=excluded.health_score,current_r=excluded.current_r,
              max_r=MAX(smart_management_checks.max_r,excluded.max_r),
              giveback_r=excluded.giveback_r,regime=excluded.regime,
              reasons=excluded.reasons,features_json=excluded.features_json,
              model_version=excluded.model_version""",values)
            await db.execute("""INSERT INTO smart_management_state(
              signal_id,inst_id,candle_ts,checked_at,action,health_score,current_r,
              max_r,giveback_r,regime,reasons,features_json,model_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id) DO UPDATE SET
              inst_id=excluded.inst_id,candle_ts=excluded.candle_ts,
              checked_at=excluded.checked_at,action=excluded.action,
              health_score=excluded.health_score,current_r=excluded.current_r,
              max_r=MAX(smart_management_state.max_r,excluded.max_r),
              giveback_r=excluded.giveback_r,regime=excluded.regime,
              reasons=excluded.reasons,features_json=excluded.features_json,
              model_version=excluded.model_version""",values)
            await db.commit()

    async def latest_smart_management(self,sid):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("SELECT * FROM smart_management_state WHERE signal_id=?",(sid,))
            r=await c.fetchone();return dict(r) if r else None

    async def load_active(self):
        async with self._connect() as db:
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
                    False,x.get("setup_type") or "UNKNOWN",
                    trigger_candle_ts=x.get("trigger_candle_ts") or 0,
                    trigger_close=x.get("trigger_close") or 0,
                    analysis_delay_sec=x.get("analysis_delay_sec") or 0,
                    stop_pct=x.get("stop_pct") or 0,
                    volume_ratio_5m=x.get("volume_ratio_5m") or 0,
                    relative_strength=x.get("relative_strength") or 0,
                    spread_pct=x.get("spread_pct") or 0,
                    estimated_cost_r=x.get("estimated_cost_r") or 0,
                ))
            return out

    async def recent(self,limit=10):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row;c=await db.execute("SELECT * FROM signals ORDER BY confirmed_at DESC LIMIT ?",(limit,))
            return [dict(x) for x in await c.fetchall()]

    async def last_confirmed(self,inst_id):
        async with self._connect() as db:
            c=await db.execute("SELECT confirmed_at,trigger_candle_ts FROM signals WHERE inst_id=? ORDER BY confirmed_at DESC LIMIT 1",(inst_id,));r=await c.fetchone()
            return (r[0],r[1]) if r else (0,None)

    async def snapshot_done(self,sid):
        async with self._connect() as db:
            c=await db.execute("SELECT horizon_min FROM snapshots WHERE signal_id=?",(sid,));return {int(x[0]) for x in await c.fetchall()}

    async def snapshot(self,sid,h,price,move,sample_ts=None):
        async with self._connect() as db:
            await db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?)",
                             (sid,h,float(sample_ts if sample_ts is not None else time.time()),price,move));await db.commit()

    async def save_scan(self,seen,deep,best):
        async with self._connect() as db:
            await db.execute("INSERT INTO scans(ts,markets_seen,markets_deep,best_json) VALUES(?,?,?,?)",
                             (time.time(),seen,deep,json.dumps(best,ensure_ascii=False)));await db.commit()

    async def enqueue_bridge(self,event_id,event_type,payload):
        """Durably queue a non-secret bridge payload before network delivery."""
        async with self._connect() as db:
            await db.execute("""INSERT OR IGNORE INTO bridge_outbox(
                event_id,event_type,payload_json,status,attempts,next_attempt_at,created_at
              ) VALUES(?,?,?,'PENDING',0,0,?)""",
              (str(event_id),str(event_type),json.dumps(payload,separators=(",",":"),ensure_ascii=False),time.time()))
            await db.commit()

    async def pending_bridge(self,limit=25):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT * FROM bridge_outbox
              WHERE status IN ('PENDING','RETRY') AND next_attempt_at<=?
              ORDER BY created_at,event_id LIMIT ?""",(time.time(),int(limit)))
            return [dict(x) for x in await c.fetchall()]

    async def mark_bridge_delivered(self,event_id):
        async with self._connect() as db:
            await db.execute("""UPDATE bridge_outbox SET status='DELIVERED',delivered_at=?,last_error=NULL
              WHERE event_id=?""",(time.time(),str(event_id)));await db.commit()

    async def mark_bridge_retry(self,event_id,error):
        async with self._connect() as db:
            c=await db.execute("SELECT attempts FROM bridge_outbox WHERE event_id=?",(str(event_id),))
            row=await c.fetchone();attempts=(int(row[0]) if row else 0)+1
            delay=min(300.0,2.0**min(attempts,8))
            await db.execute("""UPDATE bridge_outbox SET status='RETRY',attempts=?,next_attempt_at=?,last_error=?
              WHERE event_id=?""",(attempts,time.time()+delay,str(error)[:500],str(event_id)));await db.commit()

    async def bridge_outbox_counts(self):
        async with self._connect() as db:
            c=await db.execute("SELECT status,COUNT(*) FROM bridge_outbox GROUP BY status")
            return {str(x[0]):int(x[1]) for x in await c.fetchall()}

    async def stats(self,since):
        async with self._connect() as db:
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
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT side,status,close_reason,tp1_hit,tp2_hit,tp3_hit,
                                  entry,sl,tp1,tp2,tp3,close_price,max_gain_pct,max_drawdown_pct,
                                  estimated_cost_r
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
        planned_rs=[]
        estimated_net_rs=[]
        cost_r_n=0

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
                    level=lambda p: ((float(p)-entry)/risk) if side=="LONG" else ((entry-float(p))/risk)
                    r1=level(x["tp1"]);r2=level(x["tp2"]);r3=level(x["tp3"])
                    if tp3:
                        planned=.4*r1+.3*r2+.3*r3
                    elif tp2:
                        remainder=0.0 if reason=="SL" else fr
                        planned=.4*r1+.3*r2+.3*remainder
                    elif tp1:
                        remainder=0.0 if reason=="SL" else fr
                        planned=.4*r1+.6*remainder
                    else:
                        planned=fr
                    planned_rs.append(planned)
                    cost_r=float(x["estimated_cost_r"] or 0)
                    if cost_r>0:
                        estimated_net_rs.append(planned-cost_r);cost_r_n+=1

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

        plan_wins=[v for v in planned_rs if v>0];plan_losses=[v for v in planned_rs if v<0]
        planned_pf=(sum(plan_wins)/abs(sum(plan_losses))) if plan_losses else (float("inf") if plan_wins else None)
        net_wins=[v for v in estimated_net_rs if v>0];net_losses=[v for v in estimated_net_rs if v<0]
        estimated_net_pf=(sum(net_wins)/abs(sum(net_losses))) if net_losses else (float("inf") if net_wins else None)

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
            "avg_planned_r":avg(planned_rs),
            "planned_profit_factor":planned_pf,
            "avg_estimated_net_r":avg(estimated_net_rs),
            "estimated_net_profit_factor":estimated_net_pf,
            "estimated_net_r_n":cost_r_n,
        })

        return r

    async def setup_stats(self,since,min_n=1):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT COALESCE(setup_type,'UNKNOWN') setup_type,COUNT(*) n,
              SUM(close_reason='SL') sl,SUM(close_reason='CLOSE_EARLY') close_early,
              SUM(tp1_hit=1) tp1,SUM(tp2_hit=1) tp2,SUM(tp3_hit=1) tp3,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN max_gain_pct/(ABS(entry-sl)/entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN entry>0 AND ABS(entry-sl)>0 THEN ABS(max_drawdown_pct)/(ABS(entry-sl)/entry*100.0) END) avg_mae_r
              FROM signals WHERE confirmed_at>=? GROUP BY COALESCE(setup_type,'UNKNOWN')
              HAVING COUNT(*)>=? ORDER BY n DESC""",(since,min_n));return [dict(x) for x in await c.fetchall()]

    async def shadow_stats(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT sh.would_block,COUNT(*) n,
              SUM(s.close_reason='SL') sl,SUM(s.tp1_hit=1) tp1,SUM(s.tp2_hit=1) tp2,SUM(s.tp3_hit=1) tp3,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN s.max_gain_pct/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN ABS(s.max_drawdown_pct)/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mae_r
              FROM shadow_checks sh JOIN signals s ON s.id=sh.signal_id
              WHERE s.confirmed_at>=? GROUP BY sh.would_block ORDER BY sh.would_block""",(since,));return [dict(x) for x in await c.fetchall()]

    async def smart_signal_stats(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT ss.verdict,ss.setup_family,ss.regime,COUNT(*) n,
              SUM(s.status='CLOSED') closed_n,
              SUM(s.close_reason='SL' AND s.tp1_hit=0) full_sl,
              SUM(s.tp1_hit=1) tp1,SUM(s.tp2_hit=1) tp2,SUM(s.tp3_hit=1) tp3,
              AVG(ss.smart_score) avg_smart_score,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0
                THEN s.max_gain_pct/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0
                THEN ABS(s.max_drawdown_pct)/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mae_r
              FROM smart_signal_checks ss JOIN signals s ON s.id=ss.signal_id
              WHERE s.confirmed_at>=?
              GROUP BY ss.verdict,ss.setup_family,ss.regime
              ORDER BY ss.verdict,COUNT(*) DESC""",(since,))
            return [dict(x) for x in await c.fetchall()]

    async def smart_management_stats(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT action,COUNT(*) n,
              AVG(health_score) avg_health,AVG(current_r) avg_current_r,
              AVG(giveback_r) avg_giveback_r
              FROM smart_management_state WHERE checked_at>=?
              GROUP BY action ORDER BY n DESC""",(since,))
            return [dict(x) for x in await c.fetchall()]

    async def performance(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT s.horizon_min,COUNT(*) n,AVG(s.move_pct) avg_move,
              SUM(s.move_pct>0) positive,SUM(s.move_pct>=1) hit1,SUM(s.move_pct>=2) hit2,SUM(s.move_pct<=-1) loss1
              FROM snapshots s JOIN signals g ON g.id=s.signal_id
              WHERE g.confirmed_at>=? GROUP BY s.horizon_min ORDER BY s.horizon_min""",(since,));return [dict(x) for x in await c.fetchall()]
