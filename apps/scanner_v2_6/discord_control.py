import asyncio,time,os,logging
import discord,psutil
from discord import app_commands

VERSION="2.6.0-rc2"
log=logging.getLogger(__name__)

def age(sec):
    sec=max(0,int(sec))
    if sec<60:return f"{sec}s"
    if sec<3600:return f"{sec//60}m {sec%60}s"
    return f"{sec//3600}h {(sec%3600)//60}m"

def fmt(a):
    return (f"**{a.inst_id} {a.side}** · {a.status} · {a.quality} `{a.score:.0f}/100`\n"
            f"4H {a.regime_4h} · 1H {a.bias_1h} · 15M {a.setup_15m} · "
            f"5M {a.trigger_5m} · 1M {a.micro_confirmations}")

class TradeDiscord(discord.Client):
    def __init__(self,scanner,cfg):
        intents=discord.Intents.none();intents.guilds=True
        super().__init__(intents=intents)
        self.tree=app_commands.CommandTree(self);self.s=scanner;self.c=cfg
        self.command_audit_task=None
        self.register()

        async def command_error(interaction,error):
            name=str((interaction.data or {}).get("name","") if interaction.data else "")
            # A shared bot token also receives remote unrelated_* interactions. This
            # process deliberately ignores commands it does not own.
            if isinstance(error,app_commands.CommandNotFound) and not name.startswith("byscan_"):
                return
            log.error("Discord command %s failed: %s",name or "unknown",error)
            message="Command failed. Check `/byscan_health` and scanner logs."
            try:
                if interaction.response.is_done():await interaction.followup.send(message,ephemeral=True)
                else:await interaction.response.send_message(message,ephemeral=True)
            except Exception:pass
        self.tree.on_error=command_error

    async def _merge_commands(self,missing_only=False):
        if self.application_id is None:
            raise RuntimeError("Discord application_id unavailable during command merge")
        guild_id=self.c.discord_guild_id or 0
        remote_names=set()
        if missing_only:
            rows=(await self.http.get_guild_commands(self.application_id,guild_id)
                  if guild_id else await self.http.get_global_commands(self.application_id))
            remote_names={str(row.get("name","")) for row in rows}
        repaired=0
        for command in self.tree.get_commands():
            if missing_only and command.name in remote_names:continue
            payload=command.to_dict(self.tree)
            if guild_id:await self.http.upsert_guild_command(self.application_id,guild_id,payload)
            else:await self.http.upsert_global_command(self.application_id,payload)
            repaired+=1
        self.s.last_discord_command_audit_at=time.time()
        if missing_only and repaired:
            self.s.discord_command_repairs+=repaired
            log.warning("Restored %s missing byscan_* command(s) without touching unrelated commands",repaired)
        return repaired

    async def _command_audit_loop(self):
        interval=max(30.0,float(self.c.discord_command_audit_sec))
        while not self.is_closed():
            await asyncio.sleep(interval)
            try:await self._merge_commands(missing_only=True)
            except asyncio.CancelledError:raise
            except Exception as e:log.warning("Discord shared-command audit failed: %s",e)

    async def setup_hook(self):
        mode=self.c.discord_command_sync_mode
        guild=discord.Object(id=self.c.discord_guild_id) if self.c.discord_guild_id else None
        if mode=="off":
            log.warning("Discord command sync disabled; existing remote commands are preserved")
            return
        if mode=="replace":
            # Explicit opt-in only: bulk sync may remove commands owned by the
            # same shared Discord application (for example unrelated existing).
            if guild:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            return
        if mode!="merge":
            raise ValueError("DISCORD_COMMAND_SYNC_MODE must be merge, replace or off")

        # Safe shared-bot mode: POST/upsert each byscan_* command individually.
        # Unlike CommandTree.sync(), this does not bulk-delete unrelated existing commands.
        merged=await self._merge_commands()
        log.info("Merged %s Bybit commands without deleting existing Discord commands",merged)
        self.command_audit_task=asyncio.create_task(self._command_audit_loop(),name="discord-command-audit")

    async def close(self):
        if self.command_audit_task:
            self.command_audit_task.cancel()
            await asyncio.gather(self.command_audit_task,return_exceptions=True)
        await super().close()

    async def on_ready(self):
        log.info("Discord ready as %s",self.user)

    async def on_disconnect(self):
        log.warning("Discord Gateway disconnected; capped reconnect remains active")

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

    async def send_long(self,i,value):
        """Send long command output as valid <=1900-character ephemeral chunks."""
        text=str(value or "")
        chunks=[];current=""
        for line in text.splitlines(keepends=True):
            if len(line)>1900:
                if current:chunks.append(current);current=""
                chunks.extend(line[n:n+1900] for n in range(0,len(line),1900))
            elif len(current)+len(line)>1900:
                chunks.append(current);current=line
            else:
                current+=line
        if current or not chunks:chunks.append(current or "No data.")
        for chunk in chunks:
            await i.followup.send(chunk,ephemeral=True)

    def register(self):
        @self.tree.command(name="byscan_status",description="Bybit Trade Scanner status")
        async def status(i):
            if not await self.defer(i):return
            h=self.s.health()
            sf=h['safety']
            await i.followup.send(
                f"{sf['icon']} **Bybit 5m Trade Scanner V{VERSION} · {sf['state']}**\n"
                f"Uptime **{age(h['uptime'])}** · markets **{h['markets']}** · active **{h['active']}** · hotlist **{h['hotlist']}**\n"
                f"Last scan **{age(h['last_scan_age'])} ago** · duration **{h['last_scan_duration']:.1f}s**",
                ephemeral=True)

        @self.tree.command(name="byscan_health",description="System safety, Bybit, WebSocket and scanner health")
        async def health(i):
            if not await self.defer(i):return
            h=self.s.health();sf=h['safety'];cov=sf['coverage'];p=psutil.Process(os.getpid());db_ok=await self.s.storage.ping()
            def dot(ok):return '🟢' if ok else '🔴'
            ws_label='n/a (no ACTIVE)' if not h['active'] else f"{age(sf['worst_ws_age'])} worst"
            price_label='n/a' if not h['active'] else f"{age(sf['worst_price_age'])} worst"
            ctx_label='n/a' if not h['active'] else f"{age(sf['worst_context_age'])} worst"
            coverage_age='building' if cov['oldest_age']>=999999 else age(cov['oldest_age'])
            rl='🟡 recent' if sf['recent_rate_limit'] else '🟢 clear'
            await i.followup.send(
                f"{sf['icon']} **SYSTEM: {sf['state']}**\n"
                f"{dot(sf['rest_ok'])} Bybit REST · age **{age(sf['rest_age']) if sf['rest_age']<999999 else 'n/a'}** · latency **{h['rest_latency']*1000:.0f}ms**\n"
                f"{dot(sf['scan_ok'])} Scanner · last scan **{age(sf['scan_age']) if sf['scan_age']<999999 else 'n/a'} ago**\n"
                f"{dot(cov['ok'])} Fair coverage · eligible **{cov['eligible']}** · unscanned **{cov['unscanned']}** · oldest **{coverage_age}**\n"
                f"{dot(sf['ws_ok']) if h['active'] else '🟢'} ACTIVE WS · **{'ONLINE' if h['ws_connected'] else 'RECONNECTING'}** · {ws_label} · reconnects **{h['ws_reconnects']}**\n"
                f"{dot(sf['data_fresh'])} Price freshness · **{price_label}**\n"
                f"{dot(sf['context_fresh'])} Active context · **{ctx_label}**\n"
                f"{dot(sf['monitor_ok'])} REST safety monitor · age **{age(sf['monitor_age']) if sf['monitor_age']<999999 else 'n/a'}**\n"
                f"{'🟢' if db_ok else '🔴'} Database · **{'OK' if db_ok else 'ERROR'}**\n"
                f"{rl} · total rate limits **{sf['rate_limit_count']}** · IP cooldown **{age(sf['ip_cooldown']) if sf['ip_cooldown'] else 'none'}**\n"
                f"Discord alert failures **{h['discord_delivery_failures']}** · command repairs **{h['discord_command_repairs']}** · audit age **{age(h['last_discord_command_audit_age']) if h['last_discord_command_audit_age']<999999 else 'starting'}**\n"
                f"RAM **{p.memory_info().rss/1024/1024:.0f} MB** · CPU **{psutil.cpu_percent():.0f}%** · markets **{h['markets']}**\n"
                f"Last error: `{h['last_error'][-450:] or 'none'}`",
                ephemeral=True)

        @self.tree.command(name="byscan_scan",description="Force a fresh whole-market scan now")
        async def scan(i):
            if not await self.defer(i):return
            before=self.s.last_scan_at;self.s.request_scan()
            for _ in range(50):
                await asyncio.sleep(.4)
                if self.s.last_scan_at>before:break
            rows=self.s.last_scan_results[:5]
            text=["🔎 **FRESH MARKET SCAN**"]
            text += [f"{n}. {x.inst_id} **{x.side}** · {x.status} · `{x.score:.0f}`" for n,x in enumerate(rows,1)]
            if self.s.last_scan_at<=before:text.append("\n⏳ Scan is still running; use `/byscan_potentials` shortly.")
            await i.followup.send("\n".join(text),ephemeral=True)

        @self.tree.command(name="byscan_check",description="Full 4h/1h/15m/5m/1m analysis of one coin")
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
                f"4H: **{a.regime_4h}**\n1H: **{a.bias_1h}**\n15M: **{a.setup_15m}**\n"
                f"5M: **{a.trigger_5m}**\n1M: **{a.micro_confirmations} confirms** · {a.micro_1m}\n"
                f"BTC: **{a.btc_context}** · ETH: **{a.eth_context}** · RS `{a.relative_strength:+.2f}%`\n\n"
                f"Entry `{a.entry_low:.10g}–{a.entry_high:.10g}`\nSL `{a.sl:.10g}` · TP1 `{a.tp1:.10g}` · TP2 `{a.tp2:.10g}` · TP3 `{a.tp3:.10g}`\n"
                f"SL quality `{a.stop_atr:.2f} ATR / {a.stop_pct:.2f}%` · safe obstacle room `{a.obstacle_rr:.2f}R`\n\n"
                f"**Why**\n{reasons[:1200]}\n\n**Blocks/warnings**\n{blocks[:1000]}",
                ephemeral=True)

        @self.tree.command(name="byscan_why",description="Explain why a coin is EXECUTE/POTENTIAL/WAIT")
        @app_commands.describe(coin="e.g. DOGE")
        async def why(i,coin:str):
            if not await self.defer(i):return
            a=await self.s.manual_analysis(coin)
            if not a:
                await i.followup.send("Coin not found.",ephemeral=True);return
            yes="\n".join("✅ "+x for x in a.reasons) or "No strong confirmations."
            no="\n".join("⚠️ "+x for x in a.blocks) or "No hard blockers."
            await self.send_long(i,
                f"🧠 **WHY {a.inst_id}: {a.status} {a.side} ({a.score:.0f})**\n{yes[:1800]}\n\n{no[:1600]}")

        @self.tree.command(name="byscan_compare",description="Compare up to five Bybit perpetual setups")
        @app_commands.describe(coin1="required",coin2="required",coin3="optional",coin4="optional",coin5="optional")
        async def compare(i,coin1:str,coin2:str,coin3:str="",coin4:str="",coin5:str=""):
            if not await self.defer(i):return
            coins=[x for x in (coin1,coin2,coin3,coin4,coin5) if x]
            rows=await asyncio.gather(*(self.s.manual_analysis(x) for x in coins))
            rows=[x for x in rows if x]
            rows.sort(key=lambda x:x.score,reverse=True)
            await i.followup.send("\n\n".join([f"**{n}. {a.inst_id} — {a.side} {a.status} {a.score:.0f}**\n4H {a.regime_4h} · 1H {a.bias_1h} · 15M {a.setup_15m} · 5M {a.trigger_5m} · 1M {a.micro_confirmations}" for n,a in enumerate(rows,1)]) or "No valid markets.",ephemeral=True)

        @self.tree.command(name="byscan_potentials",description="Best current setups closest to EXECUTE")
        @app_commands.describe(limit="1–15")
        async def potentials(i,limit:app_commands.Range[int,1,15]=10):
            if not await self.defer(i):return
            rows=self.s.potentials(limit)
            await i.followup.send("\n".join(["🔥 **POTENTIALS**"]+
                [f"{n}. **{a.inst_id} {a.side}** · {a.status} · {a.score:.0f} · 5m {a.trigger_5m}" for n,a in enumerate(rows,1)])
                if rows else "No fresh potentials.",ephemeral=True)

        @self.tree.command(name="byscan_hotlist",description="EARLY / ARMING candidates before normal EXECUTE")
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

        @self.tree.command(name="byscan_bias",description="Strongest LONG and SHORT biases")
        async def bias(i):
            if not await self.defer(i):return
            longs,shorts=self.s.bias_rows(5)
            l="\n".join(f"• {a.inst_id} `{a.score:.0f}` · {a.status}" for a in longs) or "none"
            sh="\n".join(f"• {a.inst_id} `{a.score:.0f}` · {a.status}" for a in shorts) or "none"
            await i.followup.send(f"🟢 **LONG**\n{l}\n\n🔴 **SHORT**\n{sh}",ephemeral=True)

        @self.tree.command(name="byscan_active",description="Active EXECUTE signals with live management")
        async def active(i):
            if not await self.defer(i):return
            rows=sorted(self.s.active.values(),key=lambda x:x.confirmed_at)
            if not rows:
                await i.followup.send("No active EXECUTE signals.",ephemeral=True);return
            now=time.time();blocks=[]
            for s in rows:
                mg=self.s.management_for(s.inst_id);risk=abs(s.entry-s.sl);risk_pct=(risk/s.entry*100) if s.entry and risk else 0
                current_r=((s.last_price-s.entry)/risk) if risk and s.side=="LONG" else ((s.entry-s.last_price)/risk) if risk else 0
                net_r,cost_r,cost_pct=self.s.cost_estimate_r(s,current_r)
                mfe=(s.max_gain_pct/risk_pct) if risk_pct else 0;mae=(abs(s.max_drawdown_pct)/risk_pct) if risk_pct else 0
                opened=f"<t:{int(s.confirmed_at)}:T> · <t:{int(s.confirmed_at)}:R>"
                checked=f"<t:{int(s.last_checked_at)}:R>" if s.last_checked_at else "n/a"
                changed=f"<t:{int(mg.get('updated_at',0))}:R>" if mg.get('updated_at') else "n/a"
                price_age=self.s._active_price_age(s,now);context_age=self.s._active_context_age(s,now)
                fresh="🟢 FRESH" if self.s._management_data_fresh(s) else "🔴 STALE · decisions frozen"
                if s.entry_window_notified or not s.expires_at or now>=s.expires_at:
                    ew="CLOSED · existing trade still managed"
                else:
                    ew=f"{s.validity_state} · {age(s.expires_at-now)} left"
                shadow=s.shadow_status
                if shadow=="WOULD_BLOCK":shadow="⚠️ WOULD BLOCK (shadow only)"
                elif shadow=="PASS":shadow="✅ PASS (shadow only)"
                blocks.append(
                    f"**{s.inst_id} {s.side} · {s.quality} {s.score:.0f}**\n"
                    f"Opened **{opened}**\n"
                    f"Entry `{s.entry:.10g}` · current `{s.last_price:.10g}` · SL `{s.sl:.10g}` · **{current_r:+.2f}R**\n"
                    f"Estimated net now **{net_r:+.2f}R** · est. round-trip costs `{cost_r:.2f}R / {cost_pct:.3f}%`\n"
                    f"MFE `{mfe:+.2f}R` · MAE `-{mae:.2f}R`\n"
                    f"TP1 {'✅' if s.tp1_hit else '⬜'} · TP2 {'✅' if s.tp2_hit else '⬜'} · TP3 {'✅' if s.tp3_hit else '⬜'}\n"
                    f"Entry window **{ew}** · validity `{s.validity_score:.0f}/100`\n"
                    f"Management **{mg['action']}** · last change **{changed}**\n"
                    f"Data **{fresh}** · price `{age(price_age)}` · context `{age(context_age)}` · checked **{checked}**\n"
                    f"Shadow **{shadow}**\n"
                    f"_{s.validity_note[:160]}_"
                )
            await self.send_long(i,"\n\n".join(blocks))

        @self.tree.command(name="byscan_recent",description="Recent confirmed signals and outcomes")
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

        @self.tree.command(name="byscan_performance",description="Directional performance after 5/15/30/60 minutes")
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

        @self.tree.command(name="byscan_stats",description="Clear lifecycle and performance statistics")
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

            pf=r.get("profit_factor")

            if pf==float("inf"):
                pf_txt="∞"
            elif isinstance(pf,(int,float)):
                pf_txt=f"{pf:.2f}"
            else:
                pf_txt="—"

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
                f"Avg final-leg {(r.get('avg_final_r') or 0):+.2f}R**",

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
                f"Avg final-leg **{(r.get('avg_final_r') or 0):+.2f}R** · sample **{r.get('final_r_n') or 0}**",
                f"Final-leg profit factor **{pf_txt}**",
                f"Avg MFE **{(r.get('avg_mfe_r') or 0):+.2f}R** · "
                f"Avg MAE **-{(r.get('avg_mae_r') or 0):.2f}R**",
                f"Best final-leg **{(r.get('best_final_r') or 0):+.2f}R** · "
                f"Worst **{(r.get('worst_final_r') or 0):+.2f}R**",
                f"Avg max gain **{(r.get('avg_gain') or 0):+.2f}%** · "
                f"Avg DD **{(r.get('avg_dd') or 0):+.2f}%**",

                "",
                f"_Closed outcome % use {closed} closed signals as denominator; "
                f"target progress uses all {n} signals._",
                "_Final-leg R/PF describe the remaining-position close, "
                "not total realized PnL after partials._",
            ]

            if outcome_total!=closed:
                lines.append(
                    f"⚠️ Outcome accounting check: "
                    f"**{outcome_total}/{closed}** closed rows classified."
                )

            await self.send_long(i,"\n".join(lines))

        @self.tree.command(name="byscan_setup_stats",description="TP/SL and MAE/MFE statistics by setup type")
        @app_commands.describe(days="1–30")
        async def setup_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.setup_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No setup statistics yet.",ephemeral=True);return
            lines=[f"🧪 **SETUP STATS {days}d**"]
            for r in rows:
                n=r['n'] or 1;closed=r['closed_n'] or 0
                full_sl_pct=(r['full_sl'] or 0)/closed*100 if closed else 0
                lines.append(
                    f"• **{r['setup_type']}** n={n} / closed={closed} · "
                    f"TP1 `{(r['tp1'] or 0)/n*100:.0f}%` · TP2 `{(r['tp2'] or 0)/n*100:.0f}%` · TP3 `{(r['tp3'] or 0)/n*100:.0f}%` · "
                    f"Full SL `{full_sl_pct:.0f}%` · final `{(r['avg_final_r'] or 0):+.2f}R` · "
                    f"MFE `{(r['avg_mfe_r'] or 0):.2f}R` · MAE `{(r['avg_mae_r'] or 0):.2f}R`")
            await self.send_long(i,"\n".join(lines))

        @self.tree.command(name="byscan_edge_stats",description="Raw and estimated cost-adjusted signal edge")
        @app_commands.describe(days="1–30")
        async def edge_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            cost=self.s.estimated_roundtrip_cost_pct()
            r=await self.s.storage.edge_stats(time.time()-days*86400,cost)
            n=r.get('n') or 0;closed=r.get('closed_n') or 0
            if not n:
                await i.followup.send(f"No signals in the last {days}d.",ephemeral=True);return
            def pct(value,den):return (value or 0)/den*100 if den else 0.0
            await i.followup.send(
                f"📐 **EDGE STATS {days}d** · signals **{n}** · closed **{closed}** · active **{r.get('active_n') or 0}**\n"
                f"Avg final-leg raw **{(r.get('avg_final_r') or 0):+.2f}R** · estimated net **{(r.get('avg_est_net_final_r') or 0):+.2f}R**\n"
                f"Cost assumption **{cost:.3f}% round trip** ({self.c.est_fee_pct_per_side:.3f}% fee + {self.c.est_slippage_pct_per_side:.3f}% slippage per side)\n"
                f"TP1 **{pct(r.get('tp1'),n):.0f}%** · TP2 **{pct(r.get('tp2'),n):.0f}%** · TP3 **{pct(r.get('tp3'),n):.0f}%** · "
                f"Full SL **{pct(r.get('full_sl'),closed):.0f}% of closed**\n"
                f"Avg MFE **{(r.get('avg_mfe_r') or 0):+.2f}R** · Avg MAE **-{(r.get('avg_mae_r') or 0):.2f}R**\n\n"
                "_Cost-adjusted values are analytics only and never change EXECUTE, Entry, SL, TP or management._",
                ephemeral=True)

        @self.tree.command(name="byscan_ai_last",description="Show the latest AI Judge verdicts")
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

        @self.tree.command(name="byscan_shadow_stats",description="Compare anti-SL SHADOW decisions with real outcomes")
        @app_commands.describe(days="1–30")
        async def shadow_stats(i,days:app_commands.Range[int,1,30]=7):
            if not await self.defer(i):return
            rows=await self.s.storage.shadow_stats(time.time()-days*86400)
            if not rows:
                await i.followup.send("No SHADOW sample yet. It starts collecting on new EXECUTE signals.",ephemeral=True);return
            lines=[f"🛡️ **ANTI-SL SHADOW {days}d** · analytics only"]
            for r in rows:
                n=r['n'] or 1;label="WOULD BLOCK" if r['would_block'] else "PASS"
                lines.append(f"• **{label}** n={n} · Full SL `{(r['full_sl'] or 0)/n*100:.0f}%` · all SL `{(r['sl'] or 0)/n*100:.0f}%` · TP1 `{(r['tp1'] or 0)/n*100:.0f}%` · TP2 `{(r['tp2'] or 0)/n*100:.0f}%` · TP3 `{(r['tp3'] or 0)/n*100:.0f}%` · MFE `{(r['avg_mfe_r'] or 0):.2f}R` · MAE `{(r['avg_mae_r'] or 0):.2f}R`")
            lines.append("\nNo SHADOW result changes EXECUTE, SL or TP. Use this after ~30–50 signals before enabling any filter.")
            await self.send_long(i,"\n".join(lines))

        @self.tree.command(name="byscan_sources",description="Data source and scan coverage")
        async def sources(i):
            if not await self.defer(i):return
            h=self.s.health()
            await i.followup.send(
                f"🌐 **SOURCE: Bybit PUBLIC MARKET DATA**\n"
                f"Market: **USDT perpetual swaps only**\n"
                f"Live universe: **{h['markets']} markets**\n"
                f"Broad scan: **all tickers every {self.c.scan_interval_sec}s**\n"
                f"Deep analysis: **{self.c.deep_candidates_per_scan} priority/fair slots per cycle**, including **{self.c.rotating_candidates} least-recently-scanned slots**\n"
                f"Coverage target: every liquid eligible market within **{self.c.max_deep_scan_age_sec/60:.0f} min** using the V2.6 4H + 1H + 15M + confirmed 5M + 1M core\n"
                f"EARLY hotlist: **~{self.c.hot_monitor_sec:.0f}s** · ACTIVE price: **Bybit WebSocket** · full ACTIVE context: **~{self.c.active_context_sec:.0f}s**\n"
                f"Stale-data guard + automatic REST fallback: **ON**\n"
                f"Anti-SL: **SHADOW ONLY** · scanner exchange access: **public data only** · DEMO bridge: **{'ON' if self.s.demo_bridge else 'OFF'}**.",
                ephemeral=True)


        @self.tree.command(name="byscan_risk",description="Calculate position size from scanner SL")
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

        @self.tree.command(name="byscan_version",description="Crypto Scanner version and safety mode")
        async def version(i):
            if not await self.defer(i):return
            await i.followup.send(
                f"**Crypto Scanner V{VERSION} · SIGNAL CORE RELEASE CANDIDATE**\n"
                "4H/1H/15M/5M/1M hard gates · honest SL/obstacle checks · fair whole-market rotation · stale-data freeze · WS/REST failover.\n"
                "Bybit only · frozen V2.5 baseline retained for replay comparison · TP1/TP2/TP3 remain 1R/2R/3R.",ephemeral=True)

        @self.tree.command(name="byscan_help",description="Trade Scanner commands")
        async def help_cmd(i):
            if not await self.defer(i):return
            await i.followup.send(
                f"**Bybit Trade Scanner V{VERSION} commands**\n"
                "`/byscan_status` `/byscan_health` `/byscan_scan`\n"
                "`/byscan_check SUI` `/byscan_why SUI`\n"
                "`/byscan_compare SUI DOGE HYPE`\n"
                "`/byscan_potentials` `/byscan_hotlist` `/byscan_bias` `/byscan_active`\n"
                "`/byscan_recent` `/byscan_performance` `/byscan_stats` `/byscan_edge_stats`\n"
                "`/byscan_setup_stats` `/byscan_shadow_stats`\n"
                "`/byscan_ai_last` `/byscan_ai_stats`\n"
                "`/byscan_sources` `/byscan_risk` `/byscan_version`\n\n"
                "Commands use the `byscan_` prefix so they cannot be confused with Pump Hunter or Radar commands.",
                ephemeral=True)
