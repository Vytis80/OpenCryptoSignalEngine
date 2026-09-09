#!/usr/bin/env python3
"""One-shot patcher for the 2026-09-09 shadow AI Judge sync.

This file is removed before the final import commit. It patches only explicit
AI-sidecar integration points and fails closed if the expected public anchors
have moved.
"""
from pathlib import Path


def _read(path):
    return Path(path).read_text()


def _write(path, text):
    Path(path).write_text(text)


def _once(text, needle, path):
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"anchor count {count} != 1 in {path}: {needle[:100]!r}")


def insert_before(path, anchor, block):
    text = _read(path)
    if block.strip() in text:
        return
    _once(text, anchor, path)
    _write(path, text.replace(anchor, block + anchor, 1))


def insert_after(path, anchor, block):
    text = _read(path)
    if block.strip() in text:
        return
    _once(text, anchor, path)
    _write(path, text.replace(anchor, anchor + block, 1))


def replace_once(path, old, new):
    text = _read(path)
    if new in text:
        return
    _once(text, old, path)
    _write(path, text.replace(old, new, 1))


V26 = Path("apps/scanner_v2_6")
V25 = Path("legacy/scanner_v2_5")

AI_CONFIG = '''    # Optional GPT-OSS AI Judge — observational second opinion only.
    # Public default is opt-in: enabling sends structured signal evidence to the configured provider.
    ai_judge_enabled:bool=_b("AI_JUDGE_ENABLED",False)
    groq_api_key:str=os.getenv("GROQ_API_KEY","").strip()
    ai_judge_model:str=os.getenv("AI_JUDGE_MODEL","openai/gpt-oss-120b").strip()
    ai_judge_base_url:str=os.getenv("AI_JUDGE_BASE_URL","https://api.groq.com/openai/v1").strip()
    ai_judge_timeout_sec:float=_f("AI_JUDGE_TIMEOUT_SEC",5.0)
    ai_judge_reasoning_effort:str=os.getenv("AI_JUDGE_REASONING_EFFORT","low").strip().lower()

'''
for path in (V26 / "config.py", V25 / "config.py"):
    insert_before(path, "    # Tracking\n", AI_CONFIG)

AI_ENV = '''
# Optional AI Judge second opinion (shadow-only; external Groq API)
AI_JUDGE_ENABLED=false
GROQ_API_KEY=your_groq_api_key
AI_JUDGE_MODEL=openai/gpt-oss-120b
AI_JUDGE_BASE_URL=https://api.groq.com/openai/v1
AI_JUDGE_TIMEOUT_SEC=5
AI_JUDGE_REASONING_EFFORT=low
'''
for path in (V26 / ".env.example", V25 / ".env.example"):
    text = _read(path)
    if "AI_JUDGE_ENABLED=" not in text:
        _write(path, text.rstrip() + "\n" + AI_ENV)

# Scanner V2.6 integration.
p = V26 / "scanner.py"
insert_after(p, "from bridge_client import DemoBridgeClient\n", "from ai_judge import AIJudge\n")
insert_after(p, "        self.demo_tasks=set()\n", "        self.ai_judge=None\n")
insert_before(p, "        self.bybit=Bybit(self.cfg,self.session)\n", '''        if self.cfg.ai_judge_enabled and self.cfg.groq_api_key:
            self.ai_judge=AIJudge(self.cfg,self.session)
            log.info("AI JUDGE shadow enabled: %s",self.cfg.ai_judge_model)
        elif self.cfg.ai_judge_enabled:
            log.warning("AI JUDGE requested but GROQ_API_KEY is missing; shadow AI disabled")
''')
insert_before(p, "    async def _update_dynamic_validity", '''    async def _ai_for_execute(self,s,a,shadow=None):
        """Persist an observational AI verdict. Never blocks bridge or mutates signal fields."""
        if not self.ai_judge:return None
        try:
            j=await self.ai_judge.assess(a,shadow)
            await self.storage.save_ai_judgement(s.id,j)
            if j.ok:
                log.info("AI JUDGE %s %s confidence=%s quality=%s risk=%s latency=%sms",
                         a.inst_id,j.verdict,j.confidence,j.setup_quality,j.risk,j.latency_ms)
            else:
                log.warning("AI JUDGE unavailable %s: %s",a.inst_id,j.error)
            return j
        except Exception as e:
            log.exception("AI JUDGE sidecar failed %s: %s",a.inst_id,e)
            return None

''')
replace_once(p,
    "        delivered=await execute_alert(self.session,self.cfg,a,s.expires_at,sh)\n",
    '''        # The Demo bridge task above is spawned before the AI await. AI cannot delay,
        # veto or mutate AutoTrader execution; it only enriches the Discord/research record.
        ai_judgement=await self._ai_for_execute(s,a,sh)
        delivered=await execute_alert(self.session,self.cfg,a,s.expires_at,sh,ai_judgement)
''')

# Scanner V2.5 integration; frozen strategy decisions remain untouched.
p = V25 / "scanner.py"
insert_after(p, "from bridge_client import DemoBridgeClient\n", "from ai_judge import AIJudge\n")
insert_after(p, "        self.smart_management={}\n", "        self.ai_judge=None\n")
insert_before(p, "        self.bybit=Bybit(self.cfg,self.session)\n", '''        if self.cfg.ai_judge_enabled and self.cfg.groq_api_key:
            self.ai_judge=AIJudge(self.cfg,self.session)
            log.info("AI JUDGE shadow enabled: %s",self.cfg.ai_judge_model)
        elif self.cfg.ai_judge_enabled:
            log.warning("AI JUDGE enabled but GROQ_API_KEY is missing; AI verdicts unavailable")
''')
insert_before(p, "    async def _update_dynamic_validity", '''    async def _ai_for_execute(self,s,a,shadow=None,smart=None):
        """Persist an observational AI verdict. Never blocks bridge or mutates trade state."""
        if not self.ai_judge:return None
        try:
            j=await self.ai_judge.assess(a,shadow,smart)
            await self.storage.save_ai_judgement(s.id,j)
            if j.ok:
                log.info("AI JUDGE %s %s confidence=%s quality=%s risk=%s latency=%sms tokens=%s",
                         a.inst_id,j.verdict,j.confidence,j.setup_quality,j.risk,j.latency_ms,j.total_tokens)
            else:
                log.warning("AI JUDGE unavailable %s: %s",a.inst_id,j.error)
            return j
        except Exception as e:
            log.exception("AI JUDGE sidecar failed %s: %s",a.inst_id,e)
            return None

''')
replace_once(p,
    "        await execute_alert(self.session,self.cfg,a,s.expires_at,sh,smart)\n",
    '''        # V2.5 bridge is already queued above; AI remains observational and cannot
        # veto or change Entry/SL/TP/size/management.
        ai_judgement=await self._ai_for_execute(s,a,sh,smart)
        await execute_alert(self.session,self.cfg,a,s.expires_at,sh,smart,ai_judgement)
''')

# EXECUTE alert cards.
p = V26 / "alerts.py"
replace_once(p,
    "async def execute_alert(session,cfg,a,expires,shadow=None):\n",
    "async def execute_alert(session,cfg,a,expires,shadow=None,ai_judgement=None):\n")
insert_before(p, "    if blocks:\n", '''    if ai_judgement is not None:
        if getattr(ai_judgement,"ok",False):
            approve=getattr(ai_judgement,"verdict","")=="APPROVE"
            verdict="✅ **APPROVE**" if approve else "⛔ **REJECT**"
            strengths="; ".join(getattr(ai_judgement,"strengths",[])[:3]) or "No major strengths listed."
            risks="; ".join(getattr(ai_judgement,"risks",[])[:3]) or "No major risks listed."
            value=(
                f"{verdict} · confidence **{getattr(ai_judgement,'confidence',0)}/100** · "
                f"quality **{getattr(ai_judgement,'setup_quality','C')}** · risk **{getattr(ai_judgement,'risk','MEDIUM')}**\n"
                f"{getattr(ai_judgement,'summary','')[:420]}\n"
                f"Strengths: {strengths[:300]}\nRisks: {risks[:300]}\n"
                f"`{getattr(ai_judgement,'model','')}` · {getattr(ai_judgement,'latency_ms',0)} ms\n"
                "*AI SHADOW ONLY — it did not change or delay the AutoTrader decision.*"
            )
        else:
            value=(f"⚪ **UNAVAILABLE** · {getattr(ai_judgement,'error','No AI result')[:420]}\n"
                   "*AI SHADOW ONLY — it did not change or delay the AutoTrader decision.*")
        embed["fields"].append({"name":"GPT-OSS AI Judge · observation only","value":value[:1024],"inline":False})
''')

p = V25 / "alerts.py"
replace_once(p,
    "async def execute_alert(session,cfg,a,expires,shadow=None,smart=None):\n",
    "async def execute_alert(session,cfg,a,expires,shadow=None,smart=None,ai_judgement=None):\n")
insert_before(p, "    if blocks:\n", '''    if ai_judgement is not None:
        if getattr(ai_judgement,"ok",False):
            approve=getattr(ai_judgement,"verdict","")=="APPROVE"
            verdict="✅ **APPROVE**" if approve else "⛔ **REJECT**"
            strengths="; ".join(getattr(ai_judgement,"strengths",[])[:3]) or "No major strengths listed."
            risks="; ".join(getattr(ai_judgement,"risks",[])[:3]) or "No major risks listed."
            value=(
                f"{verdict} · confidence **{getattr(ai_judgement,'confidence',0)}/100** · "
                f"quality **{getattr(ai_judgement,'setup_quality','C')}** · risk **{getattr(ai_judgement,'risk','MEDIUM')}**\n"
                f"{getattr(ai_judgement,'summary','')[:380]}\n"
                f"Strengths: {strengths[:260]}\nRisks: {risks[:260]}\n"
                f"`{getattr(ai_judgement,'model','')}` · {getattr(ai_judgement,'latency_ms',0)} ms · "
                f"tokens `{getattr(ai_judgement,'total_tokens',0)}`\n"
                "*AI SHADOW ONLY — it did not change the V2.5 strategy or AutoTrader decision.*"
            )
        else:
            value=(f"⚪ **UNAVAILABLE** · {getattr(ai_judgement,'error','No AI result')[:420]}\n"
                   "*AI SHADOW ONLY — it did not change the V2.5 strategy or AutoTrader decision.*")
        embed["fields"].append({"name":"GPT-OSS AI Judge · observation only","value":value[:1024],"inline":False})
''')

# Storage schemas and research queries.
V26_DDL='''            CREATE TABLE IF NOT EXISTS ai_judgements(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL, checked_at REAL NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
              verdict TEXT, confidence INTEGER, setup_quality TEXT, risk TEXT,
              summary TEXT, strengths TEXT, risks TEXT, latency_ms INTEGER DEFAULT 0,
              error TEXT, prompt_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_time ON ai_judgements(checked_at);
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_verdict ON ai_judgements(verdict);
'''
insert_before(V26/"storage.py", "            \"\"\")\n            cols=", V26_DDL)
V26_METHODS='''    async def save_ai_judgement(self,sid,j):
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

'''
insert_before(V26/"storage.py", "    async def load_active", V26_METHODS)

V25_DDL='''            CREATE TABLE IF NOT EXISTS ai_judgements(
              signal_id INTEGER PRIMARY KEY, inst_id TEXT NOT NULL, checked_at REAL NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
              verdict TEXT, confidence INTEGER, setup_quality TEXT, risk TEXT,
              summary TEXT, strengths TEXT, risks TEXT, latency_ms INTEGER DEFAULT 0,
              prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
              total_tokens INTEGER DEFAULT 0, error TEXT, prompt_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_time ON ai_judgements(checked_at);
            CREATE INDEX IF NOT EXISTS idx_ai_judgements_verdict ON ai_judgements(verdict);
'''
insert_before(V25/"storage.py", "            CREATE TABLE IF NOT EXISTS smart_management_checks(", V25_DDL)
insert_before(V25/"storage.py", "            await db.commit()\n", '''            ai_cols={r[1] for r in await (await db.execute("PRAGMA table_info(ai_judgements)")).fetchall()}
            ai_migrations={
              "prompt_tokens":"INTEGER DEFAULT 0",
              "completion_tokens":"INTEGER DEFAULT 0",
              "total_tokens":"INTEGER DEFAULT 0",
            }
            for name,sql_type in ai_migrations.items():
                if name not in ai_cols:
                    await db.execute(f"ALTER TABLE ai_judgements ADD COLUMN {name} {sql_type}")
''')
V25_METHODS='''    async def save_ai_judgement(self,sid,j):
        async with self._connect() as db:
            await db.execute("""INSERT INTO ai_judgements(
              signal_id,inst_id,checked_at,provider,model,status,verdict,confidence,setup_quality,risk,
              summary,strengths,risks,latency_ms,prompt_tokens,completion_tokens,total_tokens,error,prompt_version
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(signal_id) DO UPDATE SET checked_at=excluded.checked_at,provider=excluded.provider,
                model=excluded.model,status=excluded.status,verdict=excluded.verdict,confidence=excluded.confidence,
                setup_quality=excluded.setup_quality,risk=excluded.risk,summary=excluded.summary,
                strengths=excluded.strengths,risks=excluded.risks,latency_ms=excluded.latency_ms,
                prompt_tokens=excluded.prompt_tokens,completion_tokens=excluded.completion_tokens,
                total_tokens=excluded.total_tokens,error=excluded.error,prompt_version=excluded.prompt_version""",
              (sid,j.inst_id,j.checked_at,j.provider,j.model,j.status,j.verdict,j.confidence,j.setup_quality,j.risk,
               j.summary,json.dumps(j.strengths,ensure_ascii=False),json.dumps(j.risks,ensure_ascii=False),
               j.latency_ms,j.prompt_tokens,j.completion_tokens,j.total_tokens,j.error,j.prompt_version))
            await db.commit()

    async def ai_recent(self,limit=5):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT j.*,s.side,s.quality scanner_quality,s.score scanner_score,
              s.status signal_status,s.close_reason,s.tp1_hit,s.tp2_hit,s.tp3_hit,s.max_gain_pct,s.max_drawdown_pct
              FROM ai_judgements j JOIN signals s ON s.id=j.signal_id
              ORDER BY j.checked_at DESC LIMIT ?""",(limit,))
            return [dict(x) for x in await c.fetchall()]

    async def ai_stats(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT j.status,j.verdict,COUNT(*) n,
              SUM(s.status='CLOSED') closed_n,SUM(s.close_reason='SL') sl,
              SUM(s.close_reason='SL' AND s.tp1_hit=0) full_sl,
              SUM(s.tp1_hit=1) tp1,SUM(s.tp2_hit=1) tp2,SUM(s.tp3_hit=1) tp3,
              AVG(j.confidence) avg_confidence,AVG(j.latency_ms) avg_latency_ms,
              SUM(j.prompt_tokens) prompt_tokens,SUM(j.completion_tokens) completion_tokens,SUM(j.total_tokens) total_tokens,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN s.max_gain_pct/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mfe_r,
              AVG(CASE WHEN s.entry>0 AND ABS(s.entry-s.sl)>0 THEN ABS(s.max_drawdown_pct)/(ABS(s.entry-s.sl)/s.entry*100.0) END) avg_mae_r
              FROM ai_judgements j JOIN signals s ON s.id=j.signal_id
              WHERE s.confirmed_at>=? GROUP BY j.status,j.verdict ORDER BY j.status,j.verdict""",(since,))
            return [dict(x) for x in await c.fetchall()]

    async def ai_usage(self,since):
        async with self._connect() as db:
            db.row_factory=aiosqlite.Row
            c=await db.execute("""SELECT COUNT(*) requests,
              SUM(CASE WHEN status='OK' THEN 1 ELSE 0 END) ok_requests,
              SUM(CASE WHEN status!='OK' THEN 1 ELSE 0 END) failed_requests,
              COALESCE(SUM(prompt_tokens),0) prompt_tokens,
              COALESCE(SUM(completion_tokens),0) completion_tokens,
              COALESCE(SUM(total_tokens),0) total_tokens,
              AVG(CASE WHEN total_tokens>0 THEN total_tokens END) avg_total_tokens,
              AVG(latency_ms) avg_latency_ms
              FROM ai_judgements WHERE checked_at>=?""",(since,))
            r=await c.fetchone();return dict(r) if r else {}

'''
insert_before(V25/"storage.py", "    async def save_smart_management", V25_METHODS)

# Discord inspection commands.
V26_COMMANDS='''        @self.tree.command(name="byscan_ai_last",description="Show the latest AI Judge verdicts")
        async def ai_last(i):
            if not await self.defer(i):return
            rows=await self.s.storage.ai_recent(5)
            if not rows:
                await i.followup.send("No AI Judge sample yet. New EXECUTE signals will collect it when AI is enabled.",ephemeral=True);return
            lines=["🤖 **AI JUDGE — LATEST** · shadow only"]
            for r in rows:
                if r['status']!='OK':
                    lines.append(f"• **{r['inst_id']} {r['side']}** · ⚪ AI unavailable · `{(r.get('error') or '')[:100]}`");continue
                outcome=r.get('close_reason') or r.get('signal_status');icon='✅' if r['verdict']=='APPROVE' else '⛔'
                lines.append(f"• **{r['inst_id']} {r['side']}** · {icon} **{r['verdict']} {r['confidence']}/100** · AI {r['setup_quality']} / {r['risk']} · outcome **{outcome}**\n  _{(r.get('summary') or '')[:260]}_")
            await self.send_long(i,"\n".join(lines))

        @self.tree.command(name="byscan_ai_stats",description="Compare AI APPROVE/REJECT with real signal outcomes")
        @app_commands.describe(days="1–30")
        async def ai_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.ai_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No AI Judge sample yet. It starts on new EXECUTE signals when AI is enabled.",ephemeral=True);return
            lines=[f"🤖 **AI JUDGE STATS {days}d** · shadow only"]
            for r in rows:
                n=r['n'] or 1
                if r['status']!='OK':
                    lines.append(f"• ⚪ **AI ERROR/NO DATA** n={n} · avg latency `{(r.get('avg_latency_ms') or 0):.0f} ms`");continue
                closed=r.get('closed_n') or 0;verdict=r.get('verdict') or 'NO_DATA';icon='✅' if verdict=='APPROVE' else '⛔'
                lines.append(f"• {icon} **{verdict}** n={n} / closed={closed} · avg confidence `{(r.get('avg_confidence') or 0):.0f}` · TP1 `{(r.get('tp1') or 0)/n*100:.0f}%` · TP2 `{(r.get('tp2') or 0)/n*100:.0f}%` · TP3 `{(r.get('tp3') or 0)/n*100:.0f}%` · Full SL `{(r.get('full_sl') or 0)/closed*100 if closed else 0:.0f}% of closed` · MFE `{(r.get('avg_mfe_r') or 0):.2f}R` · MAE `{(r.get('avg_mae_r') or 0):.2f}R` · latency `{(r.get('avg_latency_ms') or 0):.0f} ms`")
            lines.append("\nAI is observational only. Treat APPROVE/REJECT separation as research, not a trading guarantee.")
            await self.send_long(i,"\n".join(lines))

'''
insert_before(V26/"discord_control.py", '        @self.tree.command(name="byscan_shadow_stats"', V26_COMMANDS)
insert_before(V26/"discord_control.py", '                "`/byscan_sources`', '                "`/byscan_ai_last` `/byscan_ai_stats`\\n"\n')

V25_COMMANDS='''        @self.tree.command(name="bybit_ai_last",description="Latest GPT-OSS 120B AI Judge verdicts")
        async def ai_last(i):
            if not await self.defer(i):return
            rows=await self.s.storage.ai_recent(5)
            if not rows:
                await i.followup.send("No V2.5 AI Judge sample yet. New EXECUTE signals will collect it.",ephemeral=True);return
            lines=["🤖 **V2.5 GPT-OSS AI JUDGE — LATEST** · shadow only"]
            for r in rows:
                if r['status']!='OK':
                    lines.append(f"• **{r['inst_id']} {r['side']}** · ⚪ unavailable · `{(r.get('error') or '')[:90]}`");continue
                outcome=r.get('close_reason') or r.get('signal_status');icon='✅' if r['verdict']=='APPROVE' else '⛔'
                lines.append(f"• **{r['inst_id']} {r['side']}** · {icon} **{r['verdict']} {r['confidence']}/100** · AI {r['setup_quality']} / {r['risk']} · outcome **{outcome}** · `{r.get('total_tokens') or 0} tok`\n  _{(r.get('summary') or '')[:190]}_")
            await i.followup.send("\n".join(lines)[:1950],ephemeral=True)

        @self.tree.command(name="bybit_ai_stats",description="V2.5 AI APPROVE/REJECT vs signal outcomes")
        @app_commands.describe(days="1–30")
        async def ai_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.ai_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No V2.5 AI Judge sample yet.",ephemeral=True);return
            lines=[f"🤖 **V2.5 AI JUDGE STATS {days}d** · shadow only"]
            for r in rows:
                n=r['n'] or 1
                if r['status']!='OK':
                    lines.append(f"• ⚪ **AI ERROR** n={n} · latency `{(r.get('avg_latency_ms') or 0):.0f} ms`");continue
                closed=r.get('closed_n') or 0;icon='✅' if r.get('verdict')=='APPROVE' else '⛔'
                lines.append(f"• {icon} **{r.get('verdict')}** n={n}, closed={closed} · conf `{(r.get('avg_confidence') or 0):.0f}` · TP1 `{(r.get('tp1') or 0)/n*100:.0f}%` · TP2 `{(r.get('tp2') or 0)/n*100:.0f}%` · full SL `{(r.get('full_sl') or 0)/closed*100 if closed else 0:.0f}%` · MFE `{(r.get('avg_mfe_r') or 0):.2f}R` / MAE `{(r.get('avg_mae_r') or 0):.2f}R`")
            lines.append("_V2.5 and V2.6 AI samples must be evaluated separately._")
            await i.followup.send("\n".join(lines)[:1950],ephemeral=True)

        @self.tree.command(name="bybit_ai_usage",description="Groq token usage recorded by V2.5 AI Judge")
        @app_commands.describe(hours="1–168")
        async def ai_usage(i,hours:app_commands.Range[int,1,168]=24):
            if not await self.defer(i):return
            r=await self.s.storage.ai_usage(time.time()-hours*3600);n=int(r.get('requests') or 0)
            if not n:
                await i.followup.send(f"No V2.5 AI requests recorded in the last {hours}h.",ephemeral=True);return
            total=int(r.get('total_tokens') or 0)
            await i.followup.send(f"🧮 **V2.5 GPT-OSS USAGE — {hours}h**\nRequests **{n}** · OK **{int(r.get('ok_requests') or 0)}** · failed **{int(r.get('failed_requests') or 0)}**\nPrompt tokens **{int(r.get('prompt_tokens') or 0):,}**\nCompletion tokens **{int(r.get('completion_tokens') or 0):,}**\nTotal tokens **{total:,}** · avg/request **{(r.get('avg_total_tokens') or 0):,.0f}**\nAvg latency **{(r.get('avg_latency_ms') or 0):.0f} ms**\n_Recorded from Groq API response usage; V2.6 usage is separate._",ephemeral=True)

'''
insert_before(V25/"discord_control.py", '        @self.tree.command(name="bybit_shadow_stats"', V25_COMMANDS)
insert_before(V25/"discord_control.py", '                "`/bybit_sources`', '                "`/bybit_ai_last` `/bybit_ai_stats` `/bybit_ai_usage`\\n"\n')

# V2.6 release gate picks up all new credential-free tests.
p = V26 / "tools/run_offline_tests.py"
text = _read(p)
for test in ("test_ai_judge_contract.py","test_ai_storage.py","test_ai_nonblocking.py"):
    if f'"{test}"' not in text:
        anchor='    "test_setup_score_label.py",\n'
        _once(text, anchor, p)
        text=text.replace(anchor,f'    "{test}",\n'+anchor,1)
_write(p,text)

print("AI live sidecar patch applied successfully")
