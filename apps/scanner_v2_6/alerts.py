import asyncio,aiohttp,logging,time
log=logging.getLogger(__name__)

async def _post(session,url,username,embed):
    if not url:return False
    for attempt in range(1,4):
        try:
            async with session.post(url,json={"username":username,"embeds":[embed]},
                                    timeout=aiohttp.ClientTimeout(total=8)) as r:
                body=await r.text()
                if r.status<300:return True
                if r.status==429 and attempt<3:
                    retry_after=r.headers.get("Retry-After")
                    try:
                        payload=await r.json(content_type=None)
                        delay=float(payload.get("retry_after") or retry_after or attempt)
                    except Exception:
                        try:delay=float(retry_after or attempt)
                        except Exception:delay=float(attempt)
                    log.warning("Discord webhook rate limited; retrying in %.1fs",delay)
                    await asyncio.sleep(min(max(delay,0.25),10.0));continue
                if r.status>=500 and attempt<3:
                    log.warning("Discord webhook HTTP %s; retry %s/3",r.status,attempt+1)
                    await asyncio.sleep(float(attempt));continue
                log.error("Discord webhook HTTP %s after %s attempt(s): %s",r.status,attempt,body[:200])
                return False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if attempt<3:
                log.warning("Discord webhook attempt %s/3 failed: %s",attempt,e)
                await asyncio.sleep(float(attempt));continue
            log.error("Discord webhook failed after 3 attempts (scanner continues): %s",e)
    return False

async def execute_alert(session,cfg,a,expires,shadow=None):
    side_icon="🟢" if a.side=="LONG" else "🔴"
    reasons="\n".join("• "+x for x in a.reasons[:7]) or "• Multi-timeframe alignment"
    blocks="\n".join("• "+x for x in a.blocks[:5])
    embed={
      "title":f"{side_icon} EXECUTE {a.side} — {a.inst_id}",
      "description":f"**Setup Quality {a.quality} · Setup Score {a.score:.0f}/100**\nStatus: **FRESH**",
      "color":0x2ECC71 if a.side=="LONG" else 0xE74C3C,
      "fields":[
        {"name":"Entry","value":f"`{a.entry_low:.10g} – {a.entry_high:.10g}`","inline":True},
        {"name":"Stop","value":f"`{a.sl:.10g}`","inline":True},
        {"name":"Targets","value":f"TP1 `{a.tp1:.10g}`\nTP2 `{a.tp2:.10g}`\nTP3 `{a.tp3:.10g}`","inline":True},
        {"name":"Structure","value":f"4H **{getattr(a,'regime_4h','NEUTRAL')}** · 1H **{a.bias_1h}**\n15M **{a.setup_15m}**\n5M **{a.trigger_5m}** · 1M **{getattr(a,'micro_confirmations',0)} confirms**","inline":False},
        {"name":"Market context","value":f"BTC **{a.btc_context}** · ETH **{a.eth_context}**\nRelative strength vs BTC `{a.relative_strength:+.2f}%`","inline":False},
        {"name":"Execution quality","value":f"5m volume `{a.volume_ratio_5m:.2f}×` · ATR `{getattr(a,'atr_5m_pct',0.0):.2f}%` · spread `{a.spread_pct:.3f}%`\nSL `{getattr(a,'stop_atr',0.0):.2f} ATR / {getattr(a,'stop_pct',0.0):.2f}%` · safe obstacle room `{getattr(a,'obstacle_rr',0.0):.2f}R` · TP2 `{a.rr_tp2:.1f}R`\nEntry valid <t:{int(expires)}:R>","inline":False},
        {"name":"Historical edge","value":(
            f"**{getattr(a,'edge_label','COLLECTING')}** · sample `{getattr(a,'edge_sample',0)}`"
            if getattr(a,'edge_label','COLLECTING')=='COLLECTING' else
            f"**{a.edge_label}** · sample `{a.edge_sample}` · estimated net `{a.edge_net_r:+.2f}R` · TP2 `{a.edge_tp2_rate*100:.0f}%`"
        ),"inline":False},
        {"name":"Why","value":reasons[:1024],"inline":False},
      ],
      "footer":{"text":"V2.6 core: 4H → 1H → 15M → confirmed 5M → 1M → risk gates. Do not chase."}
    }
    # Anti-SL SHADOW is observational only. Show the verdict inside EXECUTE so
    # Discord stays clean and the user sees the extra risk context at entry time.
    if shadow is not None:
        status=getattr(shadow,"status","NO_DATA")
        if status=="WOULD_BLOCK":
            verdict="⚠️ **WOULD BLOCK (shadow only)**"
        elif status=="PASS":
            verdict="✅ **WOULD ALLOW (shadow only)**"
        else:
            verdict="⚪ **NO DATA (shadow only)**"
        shadow_reasons=getattr(shadow,"reasons",[]) or []
        reason="; ".join(shadow_reasons[:3]) if shadow_reasons else "No additional shadow note."
        embed["fields"].append({
            "name":"Shadow",
            "value":f"{verdict}\n{reason[:850]}\n*Observational only — EXECUTE, SL and TP are unchanged.*",
            "inline":False,
        })
    if blocks:
        embed["fields"].append({"name":"Warnings filtered","value":blocks[:1024],"inline":False})
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)

async def update_alert(session,cfg,sig,title,text,color=0x3498DB):
    embed={"title":title,"description":text,"color":color,
           "footer":{"text":f"{sig.inst_id} · {sig.side} · signal #{sig.id}"}}
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)



async def management_alert(session,cfg,sig,action,note,price):
    icon={"HOLD":"🟢","PROTECT":"🟡","TRAIL":"🟠","CLOSE EARLY":"🔴"}.get(action,"ℹ️")
    color={"HOLD":0x2ECC71,"PROTECT":0xF1C40F,"TRAIL":0xE67E22,"CLOSE EARLY":0xE74C3C}.get(action,0x3498DB)
    embed={
      "title":f"{icon} TRADE MANAGEMENT — {sig.inst_id}",
      "description":f"**ACTION: {action}** · {sig.side}",
      "color":color,
      "fields":[
        {"name":"Price","value":f"Entry `{sig.entry:.10g}` · current `{price:.10g}`","inline":False},
        {"name":"What to do","value":note[:1024],"inline":False},
      ],
      "footer":{"text":"Advisory signal management only — no exchange order is placed."}
    }
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)

async def entry_window_closed_alert(session,cfg,sig,price,management_action="HOLD"):
    embed={
      "title":f"⏱️ ENTRY WINDOW CLOSED — {sig.inst_id}",
      "description":"**Do not use the old EXECUTE as a new entry. This is NOT an exit signal.**",
      "color":0x95A5A6,
      "fields":[
        {"name":"Existing position","value":f"If you already entered signal #{sig.id}, it remains **ACTIVE** under trade management.","inline":False},
        {"name":"Current management","value":f"**{management_action}** · original SL/TP remain in force unless a later management update changes the recommendation.","inline":False},
        {"name":"Price","value":f"Entry `{sig.entry:.10g}` · current `{price:.10g}`","inline":False},
      ],
      "footer":{"text":"Entry validity and active-trade management are separate."}
    }
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)


async def early_alert(session,cfg,e,display_stage=None):
    stage=display_stage or e.stage
    potential=stage=="POTENTIAL"
    label="POTENTIAL" if potential else "EARLY / ARMING"
    icon="🟠" if potential else "🟡"
    embed={
      "title":f"{icon} {label} {e.side} — {e.inst_id}",
      "description":f"**Early Setup Score {e.score:.0f}/100** · this is NOT an EXECUTE.",
      "color":0xE67E22 if potential else 0xF1C40F,
      "fields":[
        {"name":"Timing","value":f"Current 5m closes in ~`{e.seconds_to_close}s` · idea **{e.trigger_hint}**","inline":False},
        {"name":"Fast view","value":f"1m momentum `{e.momentum_1m_pct:+.2f}%` · projected 5m volume `{e.projected_volume_ratio:.2f}x` · distance `{e.distance_atr:.2f} ATR`","inline":False},
        {"name":"Action","value":"Prepare only. **Wait for the normal proven EXECUTE logic.**","inline":False},
      ],
      "footer":{"text":"EARLY layer only — wait for every V2.6 EXECUTE gate."}
    }
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)

async def system_safety_alert(session,cfg,recovered,note):
    if recovered:
        embed={"title":"✅ DATA RECOVERED — ACTIVE MANAGEMENT RESUMED",
               "description":note,"color":0x2ECC71,
               "footer":{"text":"Bybit V2.6 data freshness safety guard"}}
    else:
        embed={"title":"⚠️ DATA STALE — ACTIVE MANAGEMENT FROZEN",
               "description":note,"color":0xE74C3C,
               "footer":{"text":"No stale-data management decisions are made; reconnect and REST fallback remain active."}}
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)
