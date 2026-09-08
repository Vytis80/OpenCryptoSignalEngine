import aiohttp,logging,time
log=logging.getLogger(__name__)

async def _post(session,url,username,embed):
    if not url:return False
    try:
        async with session.post(url,json={"username":username,"embeds":[embed]},
                                timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status>=300:
                log.warning("Discord webhook HTTP %s: %s",r.status,(await r.text())[:200]);return False
            return True
    except Exception as e:
        log.warning("Discord webhook failed (scanner continues): %s",e);return False

async def execute_alert(session,cfg,a,expires,shadow=None,smart=None):
    side_icon="🟢" if a.side=="LONG" else "🔴"
    reasons="\n".join("• "+x for x in a.reasons[:7]) or "• Multi-timeframe alignment"
    blocks="\n".join("• "+x for x in a.blocks[:5])
    embed={
      "title":f"{side_icon} EXECUTE {a.side} — {a.inst_id}",
      "description":f"**Quality {a.quality} · Confidence {a.score:.0f}/100**\nStatus: **FRESH**",
      "color":0x2ECC71 if a.side=="LONG" else 0xE74C3C,
      "fields":[
        {"name":"Entry","value":f"`{a.entry_low:.10g} – {a.entry_high:.10g}`","inline":True},
        {"name":"Stop","value":f"`{a.sl:.10g}`","inline":True},
        {"name":"Targets","value":f"TP1 `{a.tp1:.10g}`\nTP2 `{a.tp2:.10g}`\nTP3 `{a.tp3:.10g}`","inline":True},
        {"name":"Structure","value":f"1H **{a.bias_1h}**\n15M **{a.setup_15m}**\n5M **{a.trigger_5m}**","inline":False},
        {"name":"Market context","value":f"BTC **{a.btc_context}** · ETH **{a.eth_context}**\nRelative strength vs BTC `{a.relative_strength:+.2f}%`","inline":False},
        {"name":"Execution quality","value":f"5m volume `{a.volume_ratio_5m:.2f}×` · spread `{a.spread_pct:.3f}%` · R:R TP2 `{a.rr_tp2:.1f}R`\nSignal delay `{a.analysis_delay_sec:.0f}s` · estimated costs `{a.estimated_cost_r:.2f}R` · entry valid <t:{int(expires)}:R>","inline":False},
        {"name":"Why","value":reasons[:1024],"inline":False},
      ],
      "footer":{"text":"Trigger → full 5m close → retest/reaction. Do not chase."}
    }
    # Keep SHADOW in the EXECUTE card so the downstream manual-gate reason is visible.
    if shadow is not None:
        status=getattr(shadow,"status","NO_DATA")
        if status=="WOULD_BLOCK":
            verdict="⚠️ **WOULD BLOCK in legacy SHADOW policy**"
        elif status=="PASS":
            verdict="✅ **WOULD ALLOW**"
        else:
            verdict="⚪ **NO DATA**"
        shadow_reasons=getattr(shadow,"reasons",[]) or []
        reason="; ".join(shadow_reasons[:3]) if shadow_reasons else "No additional shadow note."
        embed["fields"].append({
            "name":"Shadow",
            "value":f"{verdict}\n{reason[:850]}\n*Diagnostic only when AutoTrader runs in ALL_EXECUTE mode.*",
            "inline":False,
        })
    if smart is not None:
        smart_reasons=getattr(smart,"reasons",[]) or []
        smart_note="; ".join(smart_reasons[:3]) if smart_reasons else "No SMART note."
        embed["fields"].append({
            "name":"V2.5.1 SMART · observation only",
            "value":f"**{getattr(smart,'verdict','PENDING')}** · {getattr(smart,'score',0):.0f}/100 · "
                    f"{getattr(smart,'setup_family','UNKNOWN')} · {getattr(smart,'regime','TRANSITION')}\n"
                    f"{smart_note[:850]}",
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
      "footer":{"text":"Integrated Demo mode can relay management to AutoTrader; verify the current Demo position."}
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


async def early_alert(session,cfg,e):
    potential=e.stage=="POTENTIAL";icon="🟠" if potential else "🟡"
    embed={
      "title":f"{icon} {e.stage if potential else 'EARLY / ARMING'} {e.side} — {e.inst_id}",
      "description":f"**Early confidence {e.score:.0f}/100** · this is NOT an EXECUTE.",
      "color":0xE67E22 if potential else 0xF1C40F,
      "fields":[
        {"name":"Timing","value":f"Current 5m closes in ~`{e.seconds_to_close}s` · idea **{e.trigger_hint}**","inline":False},
        {"name":"Fast view","value":f"1m momentum `{e.momentum_1m_pct:+.2f}%` · projected 5m volume `{e.projected_volume_ratio:.2f}x` · distance `{e.distance_atr:.2f} ATR`","inline":False},
        {"name":"Action","value":"Prepare only. **Wait for the confirmed EXECUTE logic.**","inline":False},
      ],
      "footer":{"text":"SAFE EARLY layer only — core EXECUTE/SL/TP logic is unchanged."}
    }
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)

async def early_cancelled_alert(session,cfg,inst_id,side,reason):
    embed={"title":f"⚪ EARLY CANCELLED — {inst_id}","description":f"Previous **{side}** early setup stopped arming.","color":0x95A5A6,
           "fields":[{"name":"Why","value":reason[:1024],"inline":False}],"footer":{"text":"Wait for a fresh setup."}}
    return await _post(session,cfg.discord_webhook_url,cfg.discord_username,embed)
