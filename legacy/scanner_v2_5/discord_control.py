import asyncio,time,os
import discord,psutil
from discord import app_commands

VERSION="2.5.1"

def age(sec):
    sec=max(0,int(sec))
    if sec<60:return f"{sec}s"
    if sec<3600:return f"{sec//60}m {sec%60}s"
    return f"{sec//3600}h {(sec%3600)//60}m"

def fmt(a):
    return (f"**{a.inst_id} {a.side}** · {a.status} · {a.quality} `{a.score:.0f}/100`\n"
            f"1H {a.bias_1h} · 15M {a.setup_15m} · 5M {a.trigger_5m}")

class TradeDiscord(discord.Client):
    def __init__(self,scanner,cfg):
        intents=discord.Intents.none();intents.guilds=True
        super().__init__(intents=intents)
        self.tree=app_commands.CommandTree(self);self.s=scanner;self.c=cfg
        self.register()

    async def setup_hook(self):
        if self.c.discord_guild_id:
            g=discord.Object(id=self.c.discord_guild_id)
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
        else:
            await self.tree.sync()

    async def auth(self,i):
        if self.c.discord_allowed_user_id and i.user.id!=self.c.discord_allowed_user_id:
            await i.response.send_message("⛔ Not allowed.",ephemeral=True);return False
        if self.c.discord_control_channel_id and i.channel_id!=self.c.discord_control_channel_id:
            await i.response.send_message("⛔ Use the Trade Scanner control channel.",ephemeral=True);return False
        return True

    async def defer(self,i):
        if not await self.auth(i):return False
        # Always acknowledge immediately; avoids Discord Unknown Interaction timeouts.
        await i.response.defer(ephemeral=True,thinking=True)
        return True

    def register(self):
        @self.tree.command(name="bybit_status",description="Bybit Trade Scanner status")
        async def status(i):
            if not await self.defer(i):return
            h=self.s.health()
            await i.followup.send(
                f"🟢 **Bybit 5m Trade Scanner V{VERSION} SAFE**\n"
                f"Uptime **{age(h['uptime'])}** · markets **{h['markets']}** · active **{h['active']}** · hotlist **{h['hotlist']}**\n"
                f"Last scan **{age(h['last_scan_age'])} ago** · duration **{h['last_scan_duration']:.1f}s**",
                ephemeral=True)

        @self.tree.command(name="bybit_health",description="Process, Bybit and scanner health")
        async def health(i):
            if not await self.defer(i):return
            h=self.s.health();p=psutil.Process(os.getpid())
            await i.followup.send(
                f"🩺 **HEALTH**\nRAM **{p.memory_info().rss/1024/1024:.0f} MB** · CPU **{psutil.cpu_percent():.0f}%**\n"
                f"Bybit universe **{h['markets']} USDT linear perpetuals**\n"
                f"ACTIVE WebSocket **{'ONLINE' if h['ws_connected'] else 'RECONNECTING'}** · last tick **{age(h['last_ws_tick_age']) if h['last_ws_tick_age']<999999 else 'n/a'} ago**\n"
                f"Demo bridge outbox **{h.get('bridge_outbox',{}).get('PENDING',0)} pending / "
                f"{h.get('bridge_outbox',{}).get('RETRY',0)} retrying**"
                f" · last delivery **{age(h['last_bridge_delivery_age'])+' ago' if h.get('last_bridge_delivery_age',999999)<999999 else 'n/a'}**\n"
                f"SMART shadow **{'ON' if h.get('smart_shadow') else 'OFF'}** · model `{h.get('smart_model','n/a')}` · live **{h.get('smart_managed',0)}**\n"
                f"Bridge error: `{h.get('last_bridge_error','')[-350:] or 'none'}`\n"
                f"Last error: `{h['last_error'][-700:] or 'none'}`",
                ephemeral=True)

        @self.tree.command(name="bybit_scan",description="Force a fresh whole-market scan now")
        async def scan(i):
            if not await self.defer(i):return
            before=self.s.last_scan_at;self.s.request_scan()
            for _ in range(50):
                await asyncio.sleep(.4)
                if self.s.last_scan_at>before:break
            rows=self.s.last_scan_results[:5]
            text=["🔎 **FRESH MARKET SCAN**"]
            text += [f"{n}. {x.inst_id} **{x.side}** · {x.status} · `{x.score:.0f}`" for n,x in enumerate(rows,1)]
            if self.s.last_scan_at<=before:text.append("\n⏳ Scan is still running; use `/bybit_potentials` shortly.")
            await i.followup.send("\n".join(text),ephemeral=True)

        @self.tree.command(name="bybit_check",description="Full 1h/15m/5m analysis of one coin")
        @app_commands.describe(coin="e.g. SUI")
        async def check(i,coin:str):
            if not await self.defer(i):return
            a=await self.s.manual_analysis(coin)
            if not a:
                await i.followup.send("Coin not found as a live Bybit USDT perpetual.",ephemeral=True);return
            reasons="\n".join("• "+x for x in a.reasons) or "• no strong confirmations"
            blocks="\n".join("• "+x for x in a.blocks) or "• none"
            await i.followup.send(
                f"🔎 **{a.inst_id}**\n**{a.side} · {a.status} · {a.quality} · {a.score:.0f}/100**\n\n"
                f"1H: **{a.bias_1h}**\n15M: **{a.setup_15m}**\n5M: **{a.trigger_5m}**\n"
                f"BTC: **{a.btc_context}** · ETH: **{a.eth_context}** · RS `{a.relative_strength:+.2f}%`\n\n"
                f"Entry `{a.entry_low:.10g}–{a.entry_high:.10g}`\nSL `{a.sl:.10g}` · TP1 `{a.tp1:.10g}` · TP2 `{a.tp2:.10g}` · TP3 `{a.tp3:.10g}`\n\n"
                f"**Why**\n{reasons[:1200]}\n\n**Blocks/warnings**\n{blocks[:1000]}",
                ephemeral=True)

        @self.tree.command(name="bybit_why",description="Explain why a coin is EXECUTE/POTENTIAL/WAIT")
        @app_commands.describe(coin="e.g. DOGE")
        async def why(i,coin:str):
            if not await self.defer(i):return
            a=await self.s.manual_analysis(coin)
            if not a:
                await i.followup.send("Coin not found.",ephemeral=True);return
            yes="\n".join("✅ "+x for x in a.reasons) or "No strong confirmations."
            no="\n".join("⚠️ "+x for x in a.blocks) or "No hard blockers."
            await i.followup.send(
                f"🧠 **WHY {a.inst_id}: {a.status} {a.side} ({a.score:.0f})**\n{yes[:1800]}\n\n{no[:1600]}",
                ephemeral=True)

        @self.tree.command(name="bybit_compare",description="Compare up to five Bybit perpetual setups")
        @app_commands.describe(coin1="required",coin2="required",coin3="optional",coin4="optional",coin5="optional")
        async def compare(i,coin1:str,coin2:str,coin3:str="",coin4:str="",coin5:str=""):
            if not await self.defer(i):return
            coins=[x for x in (coin1,coin2,coin3,coin4,coin5) if x]
            rows=await asyncio.gather(*(self.s.manual_analysis(x) for x in coins))
            rows=[x for x in rows if x]
            rows.sort(key=lambda x:x.score,reverse=True)
            await i.followup.send("\n\n".join([f"**{n}. {a.inst_id} — {a.side} {a.status} {a.score:.0f}**\n1H {a.bias_1h} · 15M {a.setup_15m} · 5M {a.trigger_5m}" for n,a in enumerate(rows,1)]) or "No valid markets.",ephemeral=True)

        @self.tree.command(name="bybit_potentials",description="Best current setups closest to EXECUTE")
        @app_commands.describe(limit="1–15")
        async def potentials(i,limit:app_commands.Range[int,1,15]=10):
            if not await self.defer(i):return
            rows=self.s.potentials(limit)
            await i.followup.send("\n".join(["🔥 **POTENTIALS**"]+
                [f"{n}. **{a.inst_id} {a.side}** · {a.status} · {a.score:.0f} · 5m {a.trigger_5m}" for n,a in enumerate(rows,1)])
                if rows else "No fresh potentials.",ephemeral=True)

        @self.tree.command(name="bybit_hotlist",description="EARLY / ARMING candidates before normal EXECUTE")
        async def hotlist(i):
            if not await self.defer(i):return
            rows=self.s.hot_rows()
            if not rows:
                await i.followup.send("No EARLY hotlist candidates right now.",ephemeral=True);return
            lines=["🔥 **SAFE EARLY HOTLIST** · heads-up only, not EXECUTE"]
            for a,e,stage in rows:
                if e:
                    lines.append(f"• **{a.inst_id} {a.side}** · **{stage}** · early `{e.score:.0f}` · `{e.distance_atr:.2f} ATR` away · 5m ~`{e.seconds_to_close}s`")
                else:
                    lines.append(f"• **{a.inst_id} {a.side}** · **WATCH** · core score `{a.score:.0f}`")
            await i.followup.send("\n".join(lines),ephemeral=True)

        @self.tree.command(name="bybit_bias",description="Strongest LONG and SHORT biases")
        async def bias(i):
            if not await self.defer(i):return
            longs,shorts=self.s.bias_rows(5)
            l="\n".join(f"• {a.inst_id} `{a.score:.0f}` · {a.status}" for a in longs) or "none"
            sh="\n".join(f"• {a.inst_id} `{a.score:.0f}` · {a.status}" for a in shorts) or "none"
            await i.followup.send(f"🟢 **LONG**\n{l}\n\n🔴 **SHORT**\n{sh}",ephemeral=True)

        @self.tree.command(name="bybit_active",description="Active EXECUTE signals with live management")
        async def active(i):
            if not await self.defer(i):return
            rows=sorted(self.s.active.values(),key=lambda x:x.confirmed_at)
            if not rows:
                await i.followup.send("No active EXECUTE signals.",ephemeral=True);return
            now=time.time();blocks=[]
            for s in rows:
                mg=self.s.management_for(s.inst_id);risk=abs(s.entry-s.sl);risk_pct=(risk/s.entry*100) if s.entry and risk else 0
                sm=self.s.smart_management.get(s.inst_id,{})
                current_r=((s.last_price-s.entry)/risk) if risk and s.side=="LONG" else ((s.entry-s.last_price)/risk) if risk else 0
                mfe=(s.max_gain_pct/risk_pct) if risk_pct else 0;mae=(abs(s.max_drawdown_pct)/risk_pct) if risk_pct else 0
                opened=f"<t:{int(s.confirmed_at)}:T> · <t:{int(s.confirmed_at)}:R>"
                checked=f"<t:{int(s.last_checked_at)}:R>" if s.last_checked_at else "n/a"
                changed=f"<t:{int(mg.get('updated_at',0))}:R>" if mg.get('updated_at') else "n/a"
                if s.entry_window_notified or not s.expires_at or now>=s.expires_at:
                    ew="CLOSED · existing trade still managed"
                else:
                    ew=f"{s.validity_state} · {age(s.expires_at-now)} left"
                shadow=s.shadow_status
                if shadow=="WOULD_BLOCK":shadow="⚠️ WOULD BLOCK (manual Demo gate)"
                elif shadow=="PASS":shadow="✅ PASS"
                blocks.append(
                    f"**{s.inst_id} {s.side} · {s.quality} {s.score:.0f}**\n"
                    f"Opened **{opened}**\n"
                    f"Entry `{s.entry:.10g}` · current `{s.last_price:.10g}` · SL `{s.sl:.10g}` · **{current_r:+.2f}R**\n"
                    f"MFE `{mfe:+.2f}R` · MAE `-{mae:.2f}R`\n"
                    f"TP1 {'✅' if s.tp1_hit else '⬜'} · TP2 {'✅' if s.tp2_hit else '⬜'} · TP3 {'✅' if s.tp3_hit else '⬜'}\n"
                    f"Entry window **{ew}** · validity `{s.validity_score:.0f}/100`\n"
                    f"Management **{mg['action']}** · last change **{changed}**\n"
                    f"SMART signal **{getattr(s,'smart_status','PENDING')} {getattr(s,'smart_score',0):.0f}/100** · "
                    f"live **{sm.get('action','CALIBRATING')}** `{float(sm.get('current_r') or 0):+.2f}R`\n"
                    f"Last live check **{checked}** · Shadow **{shadow}**\n"
                    f"_{s.validity_note[:160]}_"
                )
            blocks.append(
                "_ACTIVE means the scanner is tracking a confirmed signal. It does not by itself prove "
                "that the integrated Demo AutoTrader currently has an open position._"
            )
            await i.followup.send("\n\n".join(blocks)[:7900],ephemeral=True)

        @self.tree.command(name="bybit_recent",description="Recent confirmed signals and outcomes")
        @app_commands.describe(limit="1–15")
        async def recent(i,limit:app_commands.Range[int,1,15]=10):
            if not await self.defer(i):return
            rows=await self.s.storage.recent(limit)
            if not rows:
                await i.followup.send("No confirmed signals yet.",ephemeral=True);return
            lines=["🕘 **RECENT SIGNALS**"]
            for r in rows:
                result=r["close_reason"] or r["status"]
                lines.append(f"• **{r['inst_id']} {r['side']}** · {r['quality']} {r['score']:.0f} · **{result}** · max {r['max_gain_pct']:+.2f}% / DD {r['max_drawdown_pct']:+.2f}%")
            await i.followup.send("\n".join(lines),ephemeral=True)

        @self.tree.command(name="bybit_performance",description="Directional performance after 5/15/30/60 minutes")
        @app_commands.describe(days="1–30")
        async def performance(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.performance(time.time()-days*86400)
            if not rows:
                await i.followup.send("No performance snapshots yet.",ephemeral=True);return
            lines=[f"📈 **PERFORMANCE {days}d**"]
            for r in rows:
                n=r["n"];pos=(r["positive"]/n*100 if n else 0)
                lines.append(f"**{r['horizon_min']}m** n={n} · avg `{r['avg_move']:+.2f}%` · positive `{pos:.0f}%` · +1% `{r['hit1']/n*100:.0f}%` · +2% `{r['hit2']/n*100:.0f}%`")
            await i.followup.send("\n".join(lines),ephemeral=True)

        @self.tree.command(name="bybit_stats",description="Clear lifecycle and performance statistics")
        @app_commands.describe(days="1–30")
        async def stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return

            r=await self.s.storage.report_stats(time.time()-days*86400)

            n=r.get("n") or 0
            closed=r.get("closed_n") or 0
            active=r.get("active_n") or 0

            if not n:
                await i.followup.send(
                    f"No signals in the last {days}d.",
                    ephemeral=True
                )
                return

            def pct(v,den):
                return (v or 0)/den*100 if den else 0.0

            def pf_text(value):
                if value==float("inf"):
                    return "∞"
                if isinstance(value,(int,float)):
                    return f"{value:.2f}"
                return "—"

            final_pf_txt=pf_text(r.get("profit_factor"))
            plan_pf_txt=pf_text(r.get("planned_profit_factor"))
            net_pf_txt=pf_text(r.get("estimated_net_profit_factor"))

            outcome_total=(
                (r.get("tp3_finish") or 0)+
                (r.get("sl_all") or 0)+
                (r.get("invalidated") or 0)+
                (r.get("expired") or 0)+
                (r.get("close_early") or 0)+
                (r.get("other_closed") or 0)
            )

            lines=[
                f"📊 **STATS — {days} DAYS**",
                f"**{days}D · {n} signals · {closed} closed · {active} active · "
                f"Full SL {pct(r.get('full_sl'),closed):.0f}% · "
                f"TP3 finish {pct(r.get('tp3_finish'),closed):.0f}% · "
                f"Avg plan {(r.get('avg_planned_r') or 0):+.2f}R**",

                "",
                "**Overview**",
                f"Signals **{n}** · LONG **{r.get('longs') or 0}** · SHORT **{r.get('shorts') or 0}**",
                f"Closed **{closed}** · Active **{active}**",

                "",
                "**Closed outcomes**",
                f"✅ TP3 finish **{r.get('tp3_finish') or 0}** ({pct(r.get('tp3_finish'),closed):.0f}%)",
                f"🛡️ SL after TP1+ **{r.get('sl_after_tp') or 0}** ({pct(r.get('sl_after_tp'),closed):.0f}%)",
                f"❌ Full SL before TP1 **{r.get('full_sl') or 0}** ({pct(r.get('full_sl'),closed):.0f}%)",
                f"⚠️ Invalidated **{r.get('invalidated') or 0}** ({pct(r.get('invalidated'),closed):.0f}%)",
                f"⏳ Expired **{r.get('expired') or 0}** ({pct(r.get('expired'),closed):.0f}%)",
                f"↩️ Close early **{r.get('close_early') or 0}** ({pct(r.get('close_early'),closed):.0f}%)",
            ]

            if r.get("other_closed"):
                lines.append(
                    f"❔ Other closed **{r.get('other_closed')}** "
                    f"({pct(r.get('other_closed'),closed):.0f}%)"
                )

            lines += [
                "",
                "**Target progress**",
                f"TP1 reached **{r.get('tp1') or 0} / {n}** ({pct(r.get('tp1'),n):.0f}%)",
                f"TP2 reached **{r.get('tp2') or 0} / {n}** ({pct(r.get('tp2'),n):.0f}%)",
                f"TP3 reached **{r.get('tp3') or 0} / {n}** ({pct(r.get('tp3'),n):.0f}%)",

                "",
                "**Loss detail**",
                f"SL before TP1 **{r.get('full_sl') or 0}**",
                f"TP1 → SL **{r.get('tp1_to_sl') or 0}**",
                f"TP2 → SL **{r.get('tp2_to_sl') or 0}**",

                "",
                "**Performance**",
                f"Avg planned lifecycle **{(r.get('avg_planned_r') or 0):+.2f}R** · profit factor **{plan_pf_txt}**",
                f"Avg estimated after configured fees/slippage **{(r.get('avg_estimated_net_r') or 0):+.2f}R** "
                f"· profit factor **{net_pf_txt}** · sample **{r.get('estimated_net_r_n') or 0}**",
                f"Avg final-leg **{(r.get('avg_final_r') or 0):+.2f}R** · sample **{r.get('final_r_n') or 0}**",
                f"Final-leg profit factor **{final_pf_txt}**",
                f"Avg MFE **{(r.get('avg_mfe_r') or 0):+.2f}R** · "
                f"Avg MAE **-{(r.get('avg_mae_r') or 0):.2f}R**",
                f"Best final-leg **{(r.get('best_final_r') or 0):+.2f}R** · "
                f"Worst **{(r.get('worst_final_r') or 0):+.2f}R**",
                f"Avg max gain **{(r.get('avg_gain') or 0):+.2f}%** · "
                f"Avg DD **{(r.get('avg_dd') or 0):+.2f}%**",

                "",
                f"_Closed outcome % use {closed} closed signals as denominator; "
                f"target progress uses all {n} signals._",
                "_Planned lifecycle uses the scanner's 40/30/30 TP model and breakeven remainder after TP1. "
                "Estimated net uses configured fee/slippage assumptions; it is not exchange-confirmed account PnL._",
                "_Final-leg R/PF remain diagnostic only and do not represent total realized PnL after partials._",
            ]

            if outcome_total!=closed:
                lines.append(
                    f"⚠️ Outcome accounting check: "
                    f"**{outcome_total}/{closed}** closed rows classified."
                )

            await i.followup.send(
                "\n".join(lines)[:7900],
                ephemeral=True
            )

        @self.tree.command(name="bybit_setup_stats",description="TP/SL and MAE/MFE statistics by setup type")
        @app_commands.describe(days="1–30")
        async def setup_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.setup_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No setup statistics yet.",ephemeral=True);return
            lines=[f"🧪 **SETUP STATS {days}d**"]
            for r in rows:
                n=r['n'] or 1
                lines.append(f"• **{r['setup_type']}** n={n} · TP1 `{(r['tp1'] or 0)/n*100:.0f}%` · TP2 `{(r['tp2'] or 0)/n*100:.0f}%` · TP3 `{(r['tp3'] or 0)/n*100:.0f}%` · SL `{(r['sl'] or 0)/n*100:.0f}%` · MFE `{(r['avg_mfe_r'] or 0):.2f}R` · MAE `{(r['avg_mae_r'] or 0):.2f}R`")
            await i.followup.send("\n".join(lines)[:7900],ephemeral=True)

        @self.tree.command(name="bybit_ai_last",description="Latest GPT-OSS 120B AI Judge verdicts")
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

        @self.tree.command(name="bybit_shadow_stats",description="Compare anti-SL SHADOW decisions with real outcomes")
        @app_commands.describe(days="1–30")
        async def shadow_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.shadow_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No SHADOW sample yet. It starts collecting on new EXECUTE signals.",ephemeral=True);return
            lines=[f"🛡️ **ANTI-SL SHADOW {days}d** · scanner analytics + integrated Demo manual gate"]
            for r in rows:
                n=r['n'] or 1;label="WOULD BLOCK" if r['would_block'] else "PASS"
                lines.append(f"• **{label}** n={n} · SL `{(r['sl'] or 0)/n*100:.0f}%` · TP1 `{(r['tp1'] or 0)/n*100:.0f}%` · TP2 `{(r['tp2'] or 0)/n*100:.0f}%` · TP3 `{(r['tp3'] or 0)/n*100:.0f}%` · MFE `{(r['avg_mfe_r'] or 0):.2f}R` · MAE `{(r['avg_mae_r'] or 0):.2f}R`")
            lines.append(
                "\nSHADOW never changes the scanner's EXECUTE, SL or TP. In the integrated Demo flow, "
                "WOULD BLOCK is sent for manual approval instead of blind automatic execution. "
                "Treat comparisons below 50 closed signals per group as preliminary."
            )
            await i.followup.send("\n".join(lines),ephemeral=True)

        @self.tree.command(name="bybit_smart_active",description="Live SMART observations for active EXECUTE signals")
        async def smart_active(i):
            if not await self.defer(i):return
            rows=sorted(self.s.active.values(),key=lambda x:x.confirmed_at)
            if not rows:
                await i.followup.send("No active EXECUTE signals.",ephemeral=True);return
            lines=["🧠 **V2.5.1 SMART ACTIVE · observation only**"]
            for s in rows:
                sm=self.s.smart_management.get(s.inst_id,{})
                lines.append(
                    f"• **{s.inst_id} {s.side}** · signal **{getattr(s,'smart_status','PENDING')} "
                    f"{getattr(s,'smart_score',0):.0f}/100** · {getattr(s,'smart_setup','UNKNOWN')} / "
                    f"{getattr(s,'smart_regime','TRANSITION')}\n"
                    f"  Live **{sm.get('action','CALIBRATING')}** · health `{float(sm.get('health_score') or 0):.0f}` · "
                    f"now `{float(sm.get('current_r') or 0):+.2f}R` · max `{float(sm.get('max_r') or 0):+.2f}R` · "
                    f"giveback `{float(sm.get('giveback_r') or 0):.2f}R`"
                )
            lines.append("\n_All EXECUTE signals still reach AutoTrader; SMART does not alter an order._")
            await i.followup.send("\n".join(lines)[:7900],ephemeral=True)

        @self.tree.command(name="bybit_smart_stats",description="Compare SMART groups with actual signal outcomes")
        @app_commands.describe(days="1–30")
        async def smart_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.smart_signal_stats(time.time()-days*86400)
            live=await self.s.storage.smart_management_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No SMART sample yet. It starts with new EXECUTE signals.",ephemeral=True);return
            lines=[f"🧠 **V2.5.1 SMART SHADOW {days}d**"]
            for r in rows:
                n=r['n'] or 1;closed=r['closed_n'] or 0
                lines.append(
                    f"• **{r['verdict']} · {r['setup_family']} · {r['regime']}** n={n}, closed={closed} · "
                    f"full SL `{(r['full_sl'] or 0)/closed*100 if closed else 0:.0f}%` · "
                    f"TP1 `{(r['tp1'] or 0)/n*100:.0f}%` · TP2 `{(r['tp2'] or 0)/n*100:.0f}%` · "
                    f"TP3 `{(r['tp3'] or 0)/n*100:.0f}%` · MFE `{(r['avg_mfe_r'] or 0):.2f}R` · MAE `{(r['avg_mae_r'] or 0):.2f}R`"
                )
            if live:
                lines.append("\n**Latest live management states**")
                lines.extend(f"• {r['action']} `{r['n']}` · avg now `{(r['avg_current_r'] or 0):+.2f}R`" for r in live)
            lines.append("\n_Preliminary until every important setup/regime group has a materially larger closed sample._")
            await i.followup.send("\n".join(lines)[:7900],ephemeral=True)

        @self.tree.command(name="bybit_sources",description="Data source and scan coverage")
        async def sources(i):
            if not await self.defer(i):return
            h=self.s.health()
            await i.followup.send(
                f"🌐 **SOURCE: Bybit PUBLIC MARKET DATA**\n"
                f"Market: **USDT perpetual swaps only**\n"
                f"Live universe: **{h['markets']} markets**\n"
                f"Broad scan: **all tickers every {self.c.scan_interval_sec}s**\n"
                f"Deep analysis: **up to {self.c.deep_candidates_per_scan} markets/cycle** using the 1H + 15M + confirmed 5M core\n"
                f"EARLY hotlist: **~{self.c.hot_monitor_sec:.0f}s** · ACTIVE price: **Bybit WebSocket** · full ACTIVE context: **~{self.c.active_context_sec:.0f}s**\n"
                f"SMART/SHADOW: **observation only for ALL_EXECUTE validation** · scanner market data remains public-only.",
                ephemeral=True)


        @self.tree.command(name="bybit_risk",description="Calculate position size from scanner SL")
        @app_commands.describe(
            coin="e.g. SUI",
            account_eur="Trading account size in EUR",
            risk_pct="Maximum account risk if SL hits, e.g. 1",
            leverage="Used only to estimate required margin"
        )
        async def trade_risk(
            i,
            coin:str,
            account_eur:app_commands.Range[float,1.0,10000000.0],
            risk_pct:app_commands.Range[float,0.1,10.0]=1.0,
            leverage:app_commands.Range[int,1,50]=1
        ):
            if not await self.defer(i):return
            a=await self.s.manual_analysis(coin)
            if not a:
                await i.followup.send("Coin not found as a live Bybit USDT perpetual.",ephemeral=True);return
            entry=a.price
            stop_pct=abs(entry-a.sl)/entry if entry>0 else 0
            if stop_pct<=0:
                await i.followup.send("Cannot calculate risk from this setup.",ephemeral=True);return
            risk_eur=account_eur*risk_pct/100
            notional=risk_eur/stop_pct
            margin=notional/leverage
            warn=""
            if margin>account_eur:
                warn="\n⚠️ Required margin exceeds account size at this leverage."
            await i.followup.send(
                f"🧮 **RISK — {a.inst_id} {a.side}**\n"
                f"Scanner status: **{a.status} {a.score:.0f}/100**\n"
                f"Account `{account_eur:.2f} €` · risk `{risk_pct:.2f}% = {risk_eur:.2f} €`\n"
                f"Entry `{entry:.10g}` · SL `{a.sl:.10g}` · stop distance `{stop_pct*100:.2f}%`\n"
                f"Approx position notional **{notional:.2f} €**\n"
                f"Approx margin @ {leverage}x **{margin:.2f} €**{warn}\n\n"
                f"This only sizes the scanner's current SL; it does not place an order.",
                ephemeral=True)

        @self.tree.command(name="bybit_version",description="Crypto Scanner version and safety mode")
        async def version(i):
            if not await self.defer(i):return
            await i.followup.send(
                f"**Crypto Scanner V{VERSION} SMART_SHADOW + SAFE EARLY + DYNAMIC VALIDITY + REALTIME ACTIVE**\n"
                "Bybit only · every confirmed EXECUTE is relayed; SMART is observation-only.",ephemeral=True)

        @self.tree.command(name="bybit_help",description="Trade Scanner commands")
        async def help_cmd(i):
            if not await self.defer(i):return
            await i.followup.send(
                f"**Bybit Trade Scanner V{VERSION} SAFE commands**\n"
                "`/bybit_status` `/bybit_health` `/bybit_scan`\n"
                "`/bybit_check SUI` `/bybit_why SUI`\n"
                "`/bybit_compare SUI DOGE HYPE`\n"
                "`/bybit_potentials` `/bybit_hotlist` `/bybit_bias` `/bybit_active`\n"
                "`/bybit_recent` `/bybit_performance` `/bybit_stats` `/bybit_setup_stats` `/bybit_shadow_stats`\n"
                "`/bybit_smart_active` `/bybit_smart_stats`\n"
                "`/bybit_ai_last` `/bybit_ai_stats` `/bybit_ai_usage`\n"
                "`/bybit_sources` `/bybit_risk` `/bybit_version`\n\n"
                "Commands use the `bybit_` prefix so they cannot be confused with Pump Hunter or Radar commands.",
                ephemeral=True)
