import asyncio,time,logging,math,aiohttp,json
from collections import deque
from pathlib import Path
from config import Config
from bybit import Bybit
from strategy import analyze,tf_view
from storage import Storage
from models import ActiveSignal
from alerts import execute_alert,update_alert,management_alert,entry_window_closed_alert,early_alert,system_safety_alert
from enhancements import analyze_early,shadow_assess,dynamic_validity
from bridge_client import DemoBridgeClient

log=logging.getLogger(__name__)

def dir_move(side,price,entry):
    if not entry:return 0.0
    raw=(price/entry-1)*100
    return raw if side=="LONG" else -raw

class TradeScanner:
    def __init__(self,cfg:Config):
        self.cfg=cfg
        self.session=None;self.bybit=None;self.storage=Storage(cfg.db_path)
        self.live={}
        self.last_universe_refresh=0
        self.rotation=deque()
        self.scan_lock=asyncio.Lock()
        self.deep_sem=asyncio.Semaphore(cfg.deep_concurrency)
        self.last_results={}
        self.last_scan_results=[]
        self.last_scan_at=0
        self.last_scan_duration=0
        self.last_error=""
        self.started_at=time.time()
        self.active={}
        self._context_cache=None
        self._context_cache_at=0
        self.scan_requested=asyncio.Event()
        self.management={}  # inst_id -> {action,note,updated_at}
        # SAFE enhancements are sidecars around the proven strategy core.
        self.hotlist={}
        self.hot_states={}
        self.early_notify_memory={}  # (inst_id, side, stage) -> last Discord alert timestamp
        self.hot_sem=asyncio.Semaphore(cfg.hot_concurrency)
        self.ticker_history={}
        self.last_deep_scan_by_iid={}
        self.last_eligible_count=0
        self.last_eligible_symbols=set()
        self.active_context_sem=asyncio.Semaphore(cfg.active_context_concurrency)
        self.closing=set()
        self.last_excursion_write={}
        self.ws_connected=False
        self.last_ws_tick_at=0.0
        self.ws_tick_by_iid={}
        self.ws_reconnects=0
        self.ws_last_connect_at=0.0
        self.ws_last_disconnect_at=0.0
        self.last_ws_message_at=0.0
        self.last_active_monitor_at=0.0
        self.last_active_context_at=0.0
        self.last_rest_fallback_at=0.0
        self.data_stale=False
        self.data_stale_since=0.0
        self.last_safety_state="STARTING"
        self.discord_delivery_failures=0
        self.last_discord_failure_at=0.0
        self.discord_command_repairs=0
        self.last_discord_command_audit_at=0.0
        self.demo_bridge=None
        self.demo_tasks=set()

    async def init(self):
        await self.storage.init()
        self._init_demo_bridge()
        self.session=aiohttp.ClientSession(headers={"User-Agent":"Bybit-5m-Trade-Scanner-V2.6-SAFE/1.0"})
        self.bybit=Bybit(self.cfg,self.session)
        await self.refresh_universe()
        now=time.time()
        for s in await self.storage.load_active():
            s.entry_window_notified=bool(s.expires_at and now>=s.expires_at)
            s.validity_state="CLOSED" if s.entry_window_notified else "NORMAL"
            s.last_checked_at=now
            sh=await self.storage.shadow_for_signal(s.id)
            if sh:
                s.shadow_status=sh.get("status") or "PENDING"
                s.shadow_note=(sh.get("reasons") or "")[:500]
                s.shadow_suggested_sl=sh.get("suggested_sl") or 0.0
            self.active[s.inst_id]=s
            self.management[s.inst_id]={"action":"HOLD","note":"Recovered ACTIVE signal; management recalibrating.","updated_at":now}
        log.info("Loaded %s active signals from DB",len(self.active))

    async def close(self):
        for task in list(self.demo_tasks):task.cancel()
        if self.demo_tasks:
            await asyncio.gather(*list(self.demo_tasks),return_exceptions=True)
        if self.session:await self.session.close()

    async def refresh_universe(self):
        self.live=await self.bybit.live_perpetuals()
        self.rotation=deque(sorted(self.live))
        self.last_deep_scan_by_iid={k:v for k,v in self.last_deep_scan_by_iid.items() if k in self.live}
        self.last_universe_refresh=time.time()
        log.info("Universe: %s live %s linear perpetuals",len(self.live),self.cfg.quote)

    async def context(self,force=False):
        if not force and self._context_cache and time.time()-self._context_cache_at<60:
            return self._context_cache
        async def pair(base):
            iid=f"{base}{self.cfg.quote}"
            h,m=await asyncio.gather(self.bybit.candles(iid,"1H",80),self.bybit.candles(iid,"15m",80))
            return tf_view(h,20,50),tf_view(m,9,21)
        btc,eth=await asyncio.gather(pair("BTC"),pair("ETH"))
        self._context_cache=(btc,eth);self._context_cache_at=time.time()
        return self._context_cache

    def choose_candidates(self,tickers):
        eligible=[t for iid,t in tickers.items() if iid in self.live and t.quote_vol_24h>=self.cfg.min_24h_quote_volume]
        by_vol=sorted(eligible,key=lambda x:x.quote_vol_24h,reverse=True)
        by_move=sorted(eligible,key=lambda x:abs(x.change24),reverse=True)
        self.last_eligible_count=len(eligible)
        self.last_eligible_symbols={t.inst_id for t in eligible}
        selected=[];seen=set()
        def add(iid):
            if iid in tickers and iid in self.live and iid not in seen:
                seen.add(iid);selected.append(iid)

        # Active signals are always re-analysed and do not lose their slot.
        for iid in self.active:add(iid)
        # Reserve an explicit fair-rotation lane. The priority lane gets core,
        # movers and liquid anchors; the rotation lane is least-recently scanned.
        total=max(1,self.cfg.deep_candidates_per_scan)
        rotation_slots=min(max(0,self.cfg.rotating_candidates),total)
        priority_budget=max(0,total-rotation_slots)
        for base in self.cfg.core:
            if len(selected)>=priority_budget+len(self.active):break
            add(f"{base}{self.cfg.quote}")
        for t in by_move:
            if len(selected)>=priority_budget+len(self.active):break
            add(t.inst_id)
        for t in by_vol:
            if len(selected)>=priority_budget+len(self.active):break
            add(t.inst_id)

        never=-1.0
        fair=sorted(
            (t.inst_id for t in eligible if t.inst_id not in seen),
            key=lambda iid:(self.last_deep_scan_by_iid.get(iid,never),iid),
        )
        for iid in fair[:rotation_slots]:add(iid)

        # Fill unused capacity by liquidity without exceeding the configured cap
        # (except unavoidable ACTIVE signals).
        for t in by_vol:
            if len(selected)>=max(total,len(self.active)):break
            add(t.inst_id)

        # ACTIVE may make it slightly larger than configured; keep ACTIVE + cap others.
        active_ids=set(self.active)
        fixed=[x for x in selected if x in active_ids]
        rest=[x for x in selected if x not in active_ids]
        if len(rest)>total:
            selected=fixed+rest[:total]
        return selected,len(eligible)

    async def deep(self,inst_id,ticker,btc_views,eth_views):
        async with self.deep_sem:
            try:
                c4,c1,c15,c5,c1m=await asyncio.gather(
                    self.bybit.candles(inst_id,"4H",90),
                    self.bybit.candles(inst_id,"1H",90),
                    self.bybit.candles(inst_id,"15m",100),
                    self.bybit.candles(inst_id,"5m",120),
                    self.bybit.candles(inst_id,"1m",60),
                )
                if len(c4)<55 or len(c1)<55 or len(c15)<30 or len(c5)<30 or len(c1m)<25:return None
                return analyze(inst_id,ticker,c4,c1,c15,c5,c1m,btc_views,eth_views,self.cfg)
            except Exception as e:
                log.warning("Deep analysis failed %s: %s",inst_id,e)
                return None

    async def manual_analysis(self,coin):
        base=coin.upper().replace("/USDT","").replace("USDT","").split("-")[0].strip()
        iid=f"{base}{self.cfg.quote}"
        if iid not in self.live and time.time()-self.last_universe_refresh>60:
            await self.refresh_universe()
        if iid not in self.live:return None
        t=await self.bybit.ticker(iid)
        if not t:return None
        btc,eth=await self.context()
        return await self.deep(iid,t,btc,eth)


    def _update_ticker_history(self,tickers):
        now=time.time()
        for iid,tk in tickers.items():
            q=self.ticker_history.setdefault(iid,deque(maxlen=6));q.append((now,tk.last))
        if len(self.ticker_history)>len(self.live)+50:
            self.ticker_history={k:v for k,v in self.ticker_history.items() if k in self.live}

    def _velocity_pct(self,iid):
        q=self.ticker_history.get(iid)
        if not q or len(q)<2:return 0.0
        newest=q[-1];older=next((x for x in q if newest[0]-x[0]>=15),q[0])
        return (newest[1]/older[1]-1)*100 if older[1]>0 else 0.0

    async def _refresh_hotlist(self,rows,tickers,btc,eth):
        """Build heads-up candidates without changing the normal EXECUTE candidate list."""
        if not self.cfg.early_enabled:return
        picked=[];seen=set()
        def consider(a):
            if not a or a.inst_id in seen or a.inst_id in self.active or a.too_late:return
            bias_ok=(a.side=='LONG' and a.bias_1h=='BULLISH') or (a.side=='SHORT' and a.bias_1h=='BEARISH')
            if a.score>=self.cfg.early_min_base_score and bias_ok:
                seen.add(a.inst_id);picked.append(a)
        for a in sorted(rows,key=lambda x:x.score,reverse=True):
            if len(picked)>=self.cfg.hotlist_size:break
            consider(a)
        # Fresh velocity seeds are ANALYSIS-ONLY; they cannot create EXECUTE from this path.
        if len(picked)<self.cfg.hotlist_size and self.cfg.early_velocity_seeds>0:
            eligible=[x for x in tickers.values() if x.inst_id in self.live and x.quote_vol_24h>=self.cfg.min_24h_quote_volume and x.inst_id not in seen]
            eligible.sort(key=lambda x:abs(self._velocity_pct(x.inst_id)),reverse=True)
            seeds=eligible[:self.cfg.early_velocity_seeds]
            extras=await asyncio.gather(*(self.deep(x.inst_id,x,btc,eth) for x in seeds),return_exceptions=True)
            for a in extras:
                if isinstance(a,Exception):continue
                consider(a)
                if len(picked)>=self.cfg.hotlist_size:break
        new={a.inst_id:a for a in picked[:self.cfg.hotlist_size]}
        removed=[iid for iid,st in self.hot_states.items() if iid not in new and st.get('stage') in {'EARLY','POTENTIAL'}]
        self.hotlist=new
        # V2.6 clean Discord: pre-EXECUTE cancellations remain internal.
        for iid in removed:
            st=self.hot_states.pop(iid,None)
            if st:log.debug('EARLY silent cancel %s %s: dropped from hotlist',iid,st.get('side','?'))
        now=time.time();cutoff=now-max(900,self.cfg.early_realert_sec*3)
        self.early_notify_memory={k:v for k,v in self.early_notify_memory.items() if v>=cutoff}

    async def _fast_early(self,a):
        async with self.hot_sem:
            try:
                c5,c1=await asyncio.gather(self.bybit.candles_live(a.inst_id,'5m',40),self.bybit.candles(a.inst_id,'1m',12))
                return analyze_early(a,c5,c1,self.cfg)
            except Exception as e:
                log.debug('EARLY fast monitor failed %s: %s',a.inst_id,e);return None

    def _early_notify_allowed(self,iid,side,stage,now):
        key=(iid,side,stage);last=self.early_notify_memory.get(key,0.0)
        if now-last<self.cfg.early_realert_sec:return False
        self.early_notify_memory[key]=now
        return True

    def _record_delivery(self,ok,label,critical=False):
        if ok:return True
        self.discord_delivery_failures+=1;self.last_discord_failure_at=time.time()
        prefix="CRITICAL: " if critical else ""
        self.last_error=f"{prefix}Discord delivery failed: {label}"
        (log.error if critical else log.warning)(self.last_error)
        return False

    async def _handle_early(self,a,e):
        iid=a.inst_id
        if iid in self.active:
            self.hot_states.pop(iid,None);return
        prev=self.hot_states.get(iid,{})
        if e is None:
            if prev.get('stage') in {'EARLY','POTENTIAL'}:
                prev['misses']=prev.get('misses',0)+1;self.hot_states[iid]=prev
                if prev['misses']>=self.cfg.early_cancel_misses:
                    log.debug('EARLY silent cancel %s %s: fast conditions faded',iid,prev.get('side','?'))
                    self.hot_states.pop(iid,None)
            return
        if prev.get('side') and prev.get('side')!=e.side:
            log.debug('EARLY silent cancel %s %s: direction changed to %s',iid,prev.get('side'),e.side)
            prev={}

        same_side=prev.get('side')==e.side
        stable_checks=(prev.get('stable_checks',0)+1) if same_side and prev.get('stage') in {'EARLY','POTENTIAL'} else 1
        notified_rank=prev.get('notified_rank',0) if same_side else 0
        now=time.time()

        # Ordinary EARLY remains internal. POTENTIAL is the first public alert.
        if e.stage=='POTENTIAL' and notified_rank<2:
            if self._early_notify_allowed(iid,e.side,'POTENTIAL',now):
                delivered=await early_alert(self.session,self.cfg,e,'POTENTIAL')
                self._record_delivery(delivered,f"POTENTIAL {e.inst_id}")
                notified_rank=2
                log.info('POTENTIAL %s %s score=%.0f dist=%.2fATR vol=%.2fx',e.side,iid,e.score,e.distance_atr,e.projected_volume_ratio)

        self.hot_states[iid]={'stage':e.stage,'side':e.side,'candle_ts':e.candle_ts,
                              'misses':0,'analysis':e,'stable_checks':stable_checks,
                              'notified_rank':notified_rank,'last_seen_at':now}

    async def hot_monitor_loop(self):
        await asyncio.sleep(5)
        while True:
            try:
                rows=list(self.hotlist.values())
                if rows:
                    results=await asyncio.gather(*(self._fast_early(a) for a in rows))
                    for a,e in zip(rows,results):await self._handle_early(a,e)
            except Exception as e:
                self.last_error=f'hot monitor {type(e).__name__}: {e}';log.exception('Hot monitor failed')
            await asyncio.sleep(self.cfg.hot_monitor_sec)

    def hot_rows(self):
        out=[]
        for iid,a in sorted(self.hotlist.items(),key=lambda kv:kv[1].score,reverse=True):
            st=self.hot_states.get(iid,{})
            out.append((a,st.get('analysis'),st.get('stage','WATCH')))
        return out

    async def _shadow_for_execute(self,s,a):
        """Calculate and persist SHADOW before EXECUTE Discord delivery.

        SHADOW remains observational only: it never blocks EXECUTE and never
        mutates the strategy SL/TP. Returning it lets the EXECUTE embed display
        the verdict without creating a separate Discord message.
        """
        if not self.cfg.shadow_anti_sl_enabled:return None
        try:
            c5,c1=await asyncio.gather(self.bybit.candles(a.inst_id,'5m',50),self.bybit.candles(a.inst_id,'1m',12))
            sh=shadow_assess(a,c5,c1,self.cfg)
            await self.storage.save_shadow(s.id,sh)
            if s.inst_id in self.active:
                s.shadow_status=sh.status;s.shadow_note='; '.join(sh.reasons[:3]);s.shadow_suggested_sl=sh.suggested_sl
            log.info('SHADOW %s %s · suggestedSL=%.10g · %s',a.inst_id,sh.status,sh.suggested_sl,'; '.join(sh.reasons[:2]))
            return sh
        except Exception as e:
            log.warning('Shadow assessment failed %s: %s',a.inst_id,e)
            return None

    async def _update_dynamic_validity(self,s,a):
        if not self.cfg.dynamic_validity_enabled or s.entry_window_notified:return
        try:c1=await self.bybit.candles(s.inst_id,'1m',10)
        except Exception:c1=[]
        old_exp=s.expires_at;old_state=s.validity_state
        exp,state,score,note=dynamic_validity(s,a,c1,self.cfg)
        s.validity_state=state;s.validity_score=score;s.validity_note=note
        if abs((old_exp or 0)-exp)>=20:
            s.expires_at=exp;await self.storage.update_entry_window(s.id,exp)
        if state=='CLOSED' and not s.entry_window_notified:
            s.entry_window_notified=True
            delivered=await entry_window_closed_alert(self.session,self.cfg,s,s.last_price or a.price,self.management_for(s.inst_id)['action'])
            self._record_delivery(delivered,f"ENTRY WINDOW CLOSED {s.inst_id}")
            log.info('DYNAMIC ENTRY WINDOW CLOSED %s · %s',s.inst_id,note)
            if self.demo_bridge:
                self._spawn_demo(
                    self._demo_management_retry(
                        s.inst_id, "ENTRY_WINDOW_CLOSED", note,
                        s.last_price or a.price,
                        signal_id=s.id,
                    ),
                    f"demo-entry-window-closed-{s.id}"
                )
        elif old_state!=state:
            log.info('ENTRY VALIDITY %s %s→%s score=%.0f · %s',s.inst_id,old_state,state,score,note)

    async def _active_context_one(self,iid,s):
        async with self.active_context_sem:
            try:
                tk=await self.bybit.ticker(iid)
                if not tk or not self._ticker_fresh(tk):
                    log.warning('Active context skipped stale ticker %s',iid);return
                now=time.time();s.last_price=tk.last;s.last_price_at=now
                btc,eth=await self.context()
                a=await self.deep(iid,tk,btc,eth)
                if not a:return
                now=time.time();s.last_checked_at=now;s.last_context_at=now;self.last_active_context_at=now
                if iid in self.active:
                    await self._update_dynamic_validity(s,a)
                    await self.maybe_invalidate(a)
                    if iid in self.active:await self.maybe_manage(a)
            except Exception as e:log.warning('Active context refresh failed %s: %s',iid,e)

    async def active_context_loop(self):
        await asyncio.sleep(3)
        while True:
            try:
                rows=list(self.active.items())
                if rows:await asyncio.gather(*(self._active_context_one(iid,s) for iid,s in rows))
            except Exception as e:
                self.last_error=f'active context {type(e).__name__}: {e}';log.exception('Active context loop failed')
            await asyncio.sleep(self.cfg.active_context_sec)

    def _ticker_fresh(self,t):
        return bool(t and t.ts and time.time()-t.ts<=self.cfg.market_data_stale_sec)

    def _active_price_age(self,s,now=None):
        now=now or time.time()
        return now-s.last_price_at if s.last_price_at else 999999.0

    def _active_context_age(self,s,now=None):
        now=now or time.time()
        return now-s.last_context_at if s.last_context_at else 999999.0

    def _management_data_fresh(self,s):
        return (self._active_price_age(s)<=self.cfg.market_data_stale_sec and
                self._active_context_age(s)<=self.cfg.active_context_stale_sec)

    def estimated_roundtrip_cost_pct(self):
        # Display/analytics only; never changes a signal or management action.
        return 2.0*(max(0.0,self.cfg.est_fee_pct_per_side)+max(0.0,self.cfg.est_slippage_pct_per_side))

    def cost_estimate_r(self,s,current_r=0.0):
        risk=abs(s.entry-s.sl);risk_pct=(risk/s.entry*100.0) if s.entry and risk else 0.0
        cost_pct=self.estimated_roundtrip_cost_pct()
        cost_r=(cost_pct/risk_pct) if risk_pct>0 else 0.0
        return current_r-cost_r,cost_r,cost_pct

    def _worst_ws_tick_age(self,now=None):
        now=now or time.time()
        if not self.active:return 0.0
        ages=[now-self.ws_tick_by_iid.get(iid,0.0) if self.ws_tick_by_iid.get(iid,0.0) else 999999.0 for iid in self.active]
        return max(ages) if ages else 0.0

    def _ws_degraded(self):
        return bool(self.active) and (not self.ws_connected or self._worst_ws_tick_age()>self.cfg.ws_watchdog_sec)

    async def _realtime_price(self,iid,price,source_ts=None):
        if price<=0:return
        now=time.time()
        if source_ts and now-source_ts>self.cfg.market_data_stale_sec:
            log.warning('Ignoring stale WS ticker %s age=%.1fs',iid,now-source_ts);return
        s=self.active.get(iid)
        if not s or iid in self.closing:return
        s.last_price=price;s.last_price_at=now;s.last_checked_at=now
        self.last_ws_tick_at=now;self.ws_tick_by_iid[iid]=now
        move=dir_move(s.side,price,s.entry);s.max_gain_pct=max(s.max_gain_pct,move);s.max_drawdown_pct=min(s.max_drawdown_pct,move)
        if now-self.last_excursion_write.get(iid,0)>=self.cfg.realtime_excursion_write_sec:
            self.last_excursion_write[iid]=now;await self.storage.update_excursion(s.id,move,move)
        if s.side=='LONG':stop=price<=s.sl;tp1=price>=s.tp1;tp2=price>=s.tp2;tp3=price>=s.tp3
        else:stop=price>=s.sl;tp1=price<=s.tp1;tp2=price<=s.tp2;tp3=price<=s.tp3
        if stop and not s.tp1_hit:
            await self._close_active(s,'SL',s.sl,f'❌ SL HIT — {iid}',f'Stop `{s.sl:.10g}` reached.\nMax favorable move `{s.max_gain_pct:+.2f}%`');return
        if tp1:await self._hit_tp(s,1,price)
        if tp2:await self._hit_tp(s,2,price)
        if tp3 and iid in self.active:
            await self._hit_tp(s,3,price);await self._close_active(s,'TP3',s.tp3,f'🏆 TP3 HIT — {iid}',f'Full target reached.\nMax favorable move `{s.max_gain_pct:+.2f}%`');return
        if stop and iid in self.active:await self._close_active(s,'SL',s.sl,f'❌ SL HIT — {iid}',f'Stop `{s.sl:.10g}` reached after partial target(s).')

    async def active_ws_loop(self):
        """Bybit ACTIVE stream with watchdog; REST is the per-symbol fallback."""
        while True:
            try:
                async with self.session.ws_connect(self.cfg.bybit_ws_public_url,heartbeat=20,receive_timeout=None) as ws:
                    now=time.time();self.ws_connected=True;self.ws_last_connect_at=now
                    self.last_ws_message_at=now;subscribed=set();last_ping=time.monotonic();log.info('ACTIVE WS connected')
                    while True:
                        desired=set(self.active)
                        add=desired-subscribed;remove=subscribed-desired
                        now=time.time()
                        if add:
                            await ws.send_json({'op':'subscribe','args':[f'tickers.{x}' for x in sorted(add)]})
                            for x in add:self.ws_tick_by_iid[x]=now
                        if remove:
                            await ws.send_json({'op':'unsubscribe','args':[f'tickers.{x}' for x in sorted(remove)]})
                            for x in remove:self.ws_tick_by_iid.pop(x,None)
                        subscribed=desired
                        if time.monotonic()-last_ping>=20:
                            await ws.send_json({'op':'ping'});last_ping=time.monotonic()
                        try:msg=await asyncio.wait_for(ws.receive(),timeout=2.0)
                        except asyncio.TimeoutError:
                            # Reconnect only when the whole socket is silent. A quiet
                            # individual symbol uses REST fallback without churn.
                            if desired and time.time()-self.last_ws_message_at>self.cfg.ws_watchdog_sec:
                                raise RuntimeError(f'Bybit active websocket watchdog: no message for {time.time()-self.last_ws_message_at:.1f}s')
                            continue
                        if msg.type==aiohttp.WSMsgType.TEXT:
                            self.last_ws_message_at=time.time()
                            d=json.loads(msg.data);topic=d.get('topic','')
                            if topic.startswith('tickers.'):
                                rows=d.get('data',[])
                                if isinstance(rows,dict):rows=[rows]
                                source_ts=float(d.get('ts') or 0)/1000.0 or None
                                for x in rows:
                                    try:
                                        px=float(x.get('lastPrice') or 0)
                                        sym=x.get('symbol') or topic.split('.',1)[1]
                                        if px>0:await self._realtime_price(sym,px,source_ts)
                                    except Exception as e:log.debug('WS ticker handling failed: %s',e)
                        elif msg.type in {aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR}:raise RuntimeError('Bybit active websocket closed')
            except asyncio.CancelledError:raise
            except Exception as e:
                self.ws_connected=False;self.ws_reconnects+=1;self.ws_last_disconnect_at=time.time()
                self.last_error=f'active ws {type(e).__name__}: {e}'
                log.warning('ACTIVE WS disconnected: %s; REST fallback active; reconnecting',e);await asyncio.sleep(2)


    def management_for(self,inst_id):
        return self.management.get(inst_id,{"action":"HOLD","note":"setup intact","updated_at":0.0})

    def _management_decision(self,s,a):
        risk=abs(s.entry-s.sl)
        if risk<=0:
            return "HOLD","Original setup remains active."
        px=s.last_price or a.price
        current_r=((px-s.entry)/risk) if s.side=="LONG" else ((s.entry-px)/risk)
        risk_pct=abs(s.entry-s.sl)/s.entry*100 if s.entry else 0.0
        max_r=(s.max_gain_pct/risk_pct) if risk_pct>0 else current_r

        adverse=[]
        if s.side=="LONG":
            if a.bias_1h=="BEARISH": adverse.append("1H bias flipped bearish")
            if a.setup_15m.startswith("BEARISH"): adverse.append("15M structure turned bearish")
            if a.side=="SHORT" and a.score>=76: adverse.append(f"opposite SHORT setup {a.score:.0f}/100")
            if a.btc_context=="BEARISH": adverse.append("BTC context is bearish")
        else:
            if a.bias_1h=="BULLISH": adverse.append("1H bias flipped bullish")
            if a.setup_15m.startswith("BULLISH"): adverse.append("15M structure turned bullish")
            if a.side=="LONG" and a.score>=76: adverse.append(f"opposite LONG setup {a.score:.0f}/100")
            if a.btc_context=="BULLISH": adverse.append("BTC context is bullish")

        giveback=max(0.0,max_r-current_r)
        if (s.tp1_hit and len(adverse)>=2 and giveback>=0.55) or (not s.tp1_hit and len(adverse)>=3):
            return "CLOSE EARLY", "; ".join(adverse[:3]) + f" · giveback {giveback:.2f}R"
        if s.tp2_hit or current_r>=1.8:
            return "TRAIL", f"Trade reached {current_r:.2f}R. Lock profit and trail behind confirmed 5M structure."
        if s.tp1_hit or current_r>=0.95:
            extra=(" Weakness: "+"; ".join(adverse[:2])) if adverse else ""
            return "PROTECT", f"Trade reached {current_r:.2f}R. Protect profit; do not widen the original stop.{extra}"
        return "HOLD", f"Current progress {current_r:.2f}R; 1H/15M invalidation threshold not met."

    async def maybe_manage(self,a):
        s=self.active.get(a.inst_id)
        if not s:return
        if not self._management_data_fresh(s):
            log.warning('Management frozen for %s: stale data price=%.1fs context=%.1fs',
                        a.inst_id,self._active_price_age(s),self._active_context_age(s));return
        action,note=self._management_decision(s,a)
        cur=self.management_for(a.inst_id)
        rank={"HOLD":0,"PROTECT":1,"TRAIL":2,"CLOSE EARLY":3}
        if action!="CLOSE EARLY" and rank.get(action,0)<=rank.get(cur.get("action","HOLD"),0):
            cur["note"]=note;self.management[a.inst_id]=cur;return
        if action=="CLOSE EARLY":
            await self._close_active(s,"CLOSE_EARLY",a.price,
                f"🔴 CLOSE EARLY — {s.inst_id}",
                f"**Recommended action: close the remaining position.**\n{note}\n\nThis closes the bot signal lifecycle only; no exchange order is placed.")
            return
        self.management[a.inst_id]={"action":action,"note":note,"updated_at":time.time()}
        delivered=await management_alert(self.session,self.cfg,s,action,note,a.price)
        self._record_delivery(delivered,f"MANAGEMENT {action} {s.inst_id}")

        if self.demo_bridge and action in {"PROTECT","TRAIL"}:
            self._spawn_demo(
                self._demo_management_retry(
                    s.inst_id,
                    "PROTECT",
                    f"{action}: {note}",
                    a.price,
                    signal_id=s.id,
                ),
                f"demo-manage-{s.inst_id}-{action}"
            )

    def _demo_env(self,key):
        """Read bridge config from process env or local .env."""
        import os

        value=(os.getenv(key) or "").strip()
        if value:
            return value

        try:
            env_path=Path(__file__).with_name(".env")

            for raw in env_path.read_text().splitlines():
                line=raw.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                k,v=line.split("=",1)

                if k.strip()==key:
                    return v.strip().strip('"').strip("'")
        except Exception:
            pass

        return ""

    def _init_demo_bridge(self):
        url=self._demo_env("DEMO_BRIDGE_URL")
        secret=self._demo_env("DEMO_BRIDGE_SECRET")

        if not url or not secret:
            self.demo_bridge=None
            log.warning(
                "DEMO bridge disabled: DEMO_BRIDGE_URL/SECRET missing"
            )
            return

        self.demo_bridge=DemoBridgeClient(
            url,
            secret,
            timeout_sec=3.0
        )

        log.info(
            "DEMO bridge enabled -> %s",
            url
        )

    def _spawn_demo(self,coro,name):
        task=asyncio.create_task(coro,name=name)
        self.demo_tasks.add(task)
        task.add_done_callback(self.demo_tasks.discard)
        return task

    async def _demo_execute_retry(self,s):
        if not self.demo_bridge:
            return

        for attempt in range(1,4):
            try:
                result=await self.demo_bridge.execute(
                    signal_id=s.id,
                    symbol=s.inst_id,
                    side=s.side,
                    entry=s.entry,
                    entry_low=s.entry_low,
                    entry_high=s.entry_high,
                    sl=s.sl,
                    tp1=s.tp1,
                    tp2=s.tp2,
                    tp3=s.tp3,
                    quality=s.quality,
                    score=s.score,
                    setup_type=s.setup_type,
                    shadow_status=getattr(s,"shadow_status","") or "",
                    shadow_note=getattr(s,"shadow_note","") or "",
                    expires_at=getattr(s,"expires_at",0) or 0,
                )

                if result.get("ok"):
                    log.warning(
                        "DEMO EXECUTE accepted %s %s signal_id=%s response=%s",
                        s.side,
                        s.inst_id,
                        s.id,
                        result,
                    )
                else:
                    log.warning(
                        "DEMO EXECUTE not opened %s %s signal_id=%s response=%s",
                        s.side,
                        s.inst_id,
                        s.id,
                        result,
                    )

                return

            except asyncio.CancelledError:
                raise

            except Exception as e:
                log.warning(
                    "DEMO EXECUTE bridge attempt %s/3 failed %s: %s",
                    attempt,
                    s.inst_id,
                    e,
                )

                if attempt<3:
                    await asyncio.sleep(attempt*2)

        log.error(
            "DEMO EXECUTE bridge FAILED after retries %s signal_id=%s",
            s.inst_id,
            s.id,
        )

    async def _demo_management_retry(
        self,
        symbol,
        action,
        reason="",
        price=None,
        new_sl=None,
        signal_id=None
    ):
        if not self.demo_bridge:
            return

        if signal_id is None:
            log.error(
                "DEMO MANAGEMENT refused: missing source signal_id for %s %s",
                action,
                symbol,
            )
            return

        action_id = "".join(
            ch for ch in str(action).upper() if ch.isalnum()
        ) or "EVENT"
        event_id = f"V26M{signal_id}{action_id}{time.time_ns()}"

        for attempt in range(1,3):
            try:
                result=await self.demo_bridge.management(
                    signal_id=signal_id,
                    event_id=event_id,
                    symbol=symbol,
                    action=action,
                    reason=reason,
                    price=price,
                    new_sl=new_sl,
                )

                log.info(
                    "DEMO MANAGEMENT %s %s response=%s",
                    action,
                    symbol,
                    result,
                )

                return

            except asyncio.CancelledError:
                raise

            except Exception as e:
                log.warning(
                    "DEMO MANAGEMENT bridge attempt %s/2 failed %s %s: %s",
                    attempt,
                    action,
                    symbol,
                    e,
                )

                if attempt<2:
                    await asyncio.sleep(2)

    async def _attach_historical_edge(self,a):
        since=time.time()-max(1,self.cfg.edge_lookback_days)*86400
        fractions=(self.cfg.edge_tp1_fraction,self.cfg.edge_tp2_fraction,self.cfg.edge_tp3_fraction)
        r=await self.storage.setup_edge(
            since,a.trigger_5m,a.side,self.estimated_roundtrip_cost_pct(),fractions,a.core_version
        )
        a.edge_sample=int(r.get("n") or 0)
        a.edge_net_r=float(r.get("avg_net_r") or 0.0)
        a.edge_tp2_rate=float(r.get("tp2_rate") or 0.0)
        if a.edge_sample<self.cfg.edge_min_sample:
            a.edge_label="COLLECTING"
        elif a.edge_net_r>0.10:
            a.edge_label="POSITIVE"
        elif a.edge_net_r<-0.10:
            a.edge_label="NEGATIVE"
        else:
            a.edge_label="NEUTRAL"

    async def maybe_new_signal(self,a):
        if a.status!="EXECUTE" or a.inst_id in self.active:return
        last_ts,last_candle=await self.storage.last_confirmed(a.inst_id)
        now=time.time()
        if now-last_ts<self.cfg.signal_cooldown_sec:return
        if last_candle==a.trigger_candle_ts and now-last_ts<self.cfg.same_candle_cooldown_sec:return

        await self._attach_historical_edge(a)
        expires=now+self.cfg.signal_validity_sec
        sid=await self.storage.create_signal(a,expires)
        s=ActiveSignal(sid,a.inst_id,a.base,a.side,a.quality,a.score,now,a.price,a.entry_low,a.entry_high,
                       a.sl,a.tp1,a.tp2,a.tp3,expires,last_price=a.price,setup_type=a.trigger_5m,last_checked_at=now,
                       last_price_at=now,last_context_at=now)
        if self.cfg.dynamic_validity_enabled:
            dyn_exp,state,vscore,vnote=dynamic_validity(s,a,[],self.cfg,now)
            s.expires_at=dyn_exp;s.validity_state=state;s.validity_score=vscore;s.validity_note=vnote
            await self.storage.update_entry_window(s.id,dyn_exp)
        self.active[a.inst_id]=s
        self.management[a.inst_id]={"action":"HOLD","note":"Fresh EXECUTE; original setup intact.","updated_at":time.time()}
        # Compute SHADOW first so its observational verdict is embedded in the
        # same EXECUTE card instead of appearing as separate Discord noise.
        sh=await self._shadow_for_execute(s,a)

        # Relay ONLY the already-confirmed/persisted EXECUTE signal.
        # This is a sidecar: bridge failure never changes scanner strategy.
        if self.demo_bridge:
            self._spawn_demo(
                self._demo_execute_retry(s),
                f"demo-execute-{s.id}"
            )
        delivered=await execute_alert(self.session,self.cfg,a,s.expires_at,sh)
        self._record_delivery(delivered,f"EXECUTE {a.inst_id} signal #{s.id}",critical=True)
        log.warning("EXECUTE %s %s score=%.0f entry=%.8g SL=%.8g TP2=%.8g",
                    a.side,a.inst_id,a.score,a.price,a.sl,a.tp2)

    async def maybe_invalidate(self,a):
        s=self.active.get(a.inst_id)
        if not s:return
        if not self._management_data_fresh(s):
            log.warning('Invalidation frozen for %s: stale data price=%.1fs context=%.1fs',
                        a.inst_id,self._active_price_age(s),self._active_context_age(s));return
        opposite=(a.side!=s.side and a.score>=78)
        structural=(s.side=="LONG" and a.bias_1h=="BEARISH" and a.setup_15m.startswith("BEARISH")) or \
                   (s.side=="SHORT" and a.bias_1h=="BULLISH" and a.setup_15m.startswith("BULLISH"))
        if opposite or structural:
            reason="Fresh opposite setup confirmed." if opposite else "1H/15M structure no longer supports the original setup."
            action=("Close the remaining position; partial target profit is already recorded."
                    if s.tp1_hit else "Do not use the previous EXECUTE as a new entry; close/avoid the setup.")
            await self._close_active(s,"INVALIDATED",a.price,
                f"🔴 EXECUTE INVALIDATED — {s.inst_id}",
                f"**{action}**\n{reason}")

    async def scan_once(self,force=False):
        if self.scan_lock.locked() and not force:return self.last_scan_results
        async with self.scan_lock:
            start=time.time()
            try:
                if time.time()-self.last_universe_refresh>=self.cfg.universe_refresh_sec:
                    await self.refresh_universe()
                tickers=await self.bybit.tickers()
                self._update_ticker_history(tickers)
                btc,eth=await self.context()
                candidates,eligible_count=self.choose_candidates(tickers)
                deep_ids=[iid for iid in candidates if iid in tickers]
                tasks=[self.deep(iid,tickers[iid],btc,eth) for iid in deep_ids]
                analysed=await asyncio.gather(*tasks)
                completed=time.time()
                # Coverage counts only successful full analyses. Failed/short
                # candle sets stay least-recently-scanned and retry next cycle.
                for iid,row in zip(deep_ids,analysed):
                    if row:self.last_deep_scan_by_iid[iid]=completed
                rows=[x for x in analysed if x]
                rows.sort(key=lambda x:x.score,reverse=True)
                self.last_scan_results=rows
                self.last_scan_at=time.time()
                self.last_scan_duration=self.last_scan_at-start
                for a in rows:self.last_results[a.inst_id]=a
                await self._refresh_hotlist(rows,tickers,btc,eth)

                for a in rows:
                    if a.inst_id in self.active:
                        s=self.active[a.inst_id];tk=tickers.get(a.inst_id);now=time.time()
                        if tk and self._ticker_fresh(tk):
                            s.last_price=tk.last;s.last_price_at=now;s.last_context_at=now
                            s.last_checked_at=now;self.last_active_context_at=now
                            await self.maybe_invalidate(a)
                            if a.inst_id in self.active:await self.maybe_manage(a)
                        else:
                            log.warning('Scan management skipped stale ticker %s',a.inst_id)
                    if a.status=="EXECUTE":await self.maybe_new_signal(a)

                best=[{"symbol":x.inst_id,"side":x.side,"status":x.status,"score":round(x.score,1)} for x in rows[:8]]
                await self.storage.save_scan(len(tickers),len(rows),best)
                log.info("Scan: all=%s eligible=%s deep=%s best=%s",
                         len(tickers),eligible_count,len(rows),
                         ", ".join(f"{x.inst_id}:{x.side}:{x.status}:{x.score:.0f}" for x in rows[:5]))
                return rows
            except Exception as e:
                self.last_error=f"{type(e).__name__}: {e}"
                log.exception("Scan failed")
                return self.last_scan_results

    async def scan_loop(self):
        await asyncio.sleep(2)
        while True:
            await self.scan_once()
            try:
                await asyncio.wait_for(self.scan_requested.wait(),timeout=self.cfg.scan_interval_sec)
                self.scan_requested.clear()
            except asyncio.TimeoutError:
                pass

    async def _close_active(self,s,reason,price,title=None,text=None):
        if s.inst_id not in self.active or s.inst_id in self.closing:return

        # Exchange SL/TP are already real Bybit Demo orders.
        # Only lifecycle closes that require an active decision are relayed.
        if self.demo_bridge:
            demo_action = reason if reason in {"INVALIDATED","CLOSE_EARLY"} else "SIGNAL_CLOSED"
            self._spawn_demo(
                self._demo_management_retry(
                    symbol=s.inst_id,
                    action=demo_action,
                    reason=f"{reason}: {text or reason}",
                    price=price,
                    signal_id=s.id,
                ),
                f"demo-close-{s.inst_id}-{reason}"
            )
        self.closing.add(s.inst_id);s.status="CLOSED"
        try:await self.storage.close_signal(s.id,reason,price)
        finally:
            self.active.pop(s.inst_id,None);self.management.pop(s.inst_id,None);self.closing.discard(s.inst_id)
        title=title or f"✅ SIGNAL CLOSED — {s.inst_id}"
        text=text or f"Reason: **{reason}**\nClose `{price:.10g}`"
        color=0x2ECC71 if reason=="TP3" else 0xE74C3C if reason in {"SL","INVALIDATED","CLOSE_EARLY"} else 0x95A5A6
        delivered=await update_alert(self.session,self.cfg,s,title,text,color)
        self._record_delivery(delivered,f"CLOSE {reason} {s.inst_id}",critical=True)

    async def _hit_tp(self,s,n,price):
        attr=f"tp{n}_hit"
        if getattr(s,attr):return
        setattr(s,attr,True);await self.storage.mark_tp(s.id,n)
        target=getattr(s,f"tp{n}")
        action="PROTECT" if n==1 else "TRAIL" if n>=2 else "HOLD"
        if n==1:
            mg="Take partial profit if that is your plan; protect the remainder and consider SL → breakeven only if structure allows."
        elif n==2:
            mg="Lock meaningful profit and trail the remainder behind confirmed 5M structure."
        else:
            mg="Full target reached."
        if n<=2:self.management[s.inst_id]={"action":action,"note":mg,"updated_at":time.time()}
        delivered=await update_alert(self.session,self.cfg,s,f"✅ TP{n} HIT — {s.inst_id}",
                                     f"Target `{target:.10g}` reached.\nCurrent `{price:.10g}`\n\n**Management: {action}**\n{mg}",
                                     0x2ECC71)
        self._record_delivery(delivered,f"TP{n} {s.inst_id}",critical=True)

    async def active_monitor_loop(self):
        """REST wick safety net; accelerates when an ACTIVE WS symbol is stale."""
        while True:
            sleep_for=self.cfg.active_monitor_sec
            try:
                if not self.active:
                    self.last_active_monitor_at=time.time();await asyncio.sleep(sleep_for);continue
                if self._ws_degraded():sleep_for=self.cfg.active_rest_fallback_sec
                tickers=await self.bybit.tickers()
                now=time.time();self.last_active_monitor_at=now
                if self._ws_degraded():self.last_rest_fallback_at=now
                for iid,s in list(self.active.items()):
                    t=tickers.get(iid)
                    if not t or not self._ticker_fresh(t):
                        log.warning('REST active monitor skipped stale/missing ticker %s',iid);continue
                    now=time.time();s.last_price=t.last;s.last_price_at=now;s.last_checked_at=now
                    move=dir_move(s.side,t.last,s.entry)
                    s.max_gain_pct=max(s.max_gain_pct,move);s.max_drawdown_pct=min(s.max_drawdown_pct,move)
                    await self.storage.update_excursion(s.id,move,move)

                    # Latest confirmed 1m candle catches brief TP/SL wicks better than last-price only.
                    try:
                        c=await self.bybit.candles(iid,"1m",3)
                        bar=c[-1] if c else None
                    except:
                        bar=None
                    hi=max(t.last,bar.h if bar else t.last);lo=min(t.last,bar.l if bar else t.last)

                    if s.side=="LONG":
                        stop=lo<=s.sl
                        tp1=hi>=s.tp1;tp2=hi>=s.tp2;tp3=hi>=s.tp3
                    else:
                        stop=hi>=s.sl
                        tp1=lo<=s.tp1;tp2=lo<=s.tp2;tp3=lo<=s.tp3

                    # Conservative ambiguity rule: if an unprotected signal touches SL and TP in
                    # the same unseen 1m bar, count SL first rather than flattering statistics.
                    if stop and not s.tp1_hit:
                        await self._close_active(s,"SL",s.sl,f"❌ SL HIT — {iid}",
                                                 f"Stop `{s.sl:.10g}` reached.\nMax favorable move `{s.max_gain_pct:+.2f}%`")
                        continue
                    if tp1:await self._hit_tp(s,1,t.last)
                    if tp2:await self._hit_tp(s,2,t.last)
                    if tp3:
                        await self._hit_tp(s,3,t.last)
                        await self._close_active(s,"TP3",s.tp3,f"🏆 TP3 HIT — {iid}",
                                                 f"Full target reached.\nMax favorable move `{s.max_gain_pct:+.2f}%`")
                        continue
                    if stop:
                        await self._close_active(s,"SL",s.sl,f"❌ SL HIT — {iid}",
                                                 f"Stop `{s.sl:.10g}` reached after partial target(s).")
                        continue

                    now=time.time()
                    if s.expires_at and now>=s.expires_at and not s.entry_window_notified:
                        s.entry_window_notified=True
                        if not s.tp1_hit:
                            delivered=await entry_window_closed_alert(self.session,self.cfg,s,t.last,self.management_for(iid)["action"])
                            self._record_delivery(delivered,f"ENTRY WINDOW CLOSED {s.inst_id}")
                        log.info("ENTRY WINDOW CLOSED %s; ACTIVE management continues",iid)
                        if self.demo_bridge:
                            self._spawn_demo(
                                self._demo_management_retry(
                                    s.inst_id, "ENTRY_WINDOW_CLOSED",
                                    "Scanner entry validity expired", t.last,
                                    signal_id=s.id,
                                ),
                                f"demo-entry-expired-{s.id}"
                            )
            except Exception as e:
                self.last_error=f"monitor {type(e).__name__}: {e}"
                log.exception("Active monitor failed")
            await asyncio.sleep(max(1.0,sleep_for))

    async def performance_loop(self):
        while True:
            try:
                rows=await self.storage.recent(150)
                if rows:
                    tickers=await self.bybit.tickers();now=time.time()
                    for r in rows:
                        ct=r["confirmed_at"];entry=r["entry"];t=tickers.get(r["inst_id"])
                        if not self._ticker_fresh(t) or not ct or now-ct>self.cfg.performance_track_sec+300:continue
                        mv=dir_move(r["side"],t.last,entry)
                        done=await self.storage.snapshot_done(r["id"])
                        for h in (5,15,30,60):
                            if h not in done and now>=ct+h*60:
                                await self.storage.snapshot(r["id"],h,t.last,mv)
            except Exception as e:
                self.last_error=f"performance {type(e).__name__}: {e}"
                log.exception("Performance loop failed")
            await asyncio.sleep(15)

    def coverage_health(self,now=None):
        now=now or time.time();eligible=self.last_eligible_symbols
        if not eligible:
            return {"ok":False,"eligible":0,"unscanned":0,"oldest_age":999999.0}
        unscanned=sum(1 for iid in eligible if iid not in self.last_deep_scan_by_iid)
        ages=[now-self.last_deep_scan_by_iid[iid] for iid in eligible if iid in self.last_deep_scan_by_iid]
        oldest=max(ages,default=999999.0)
        return {"ok":unscanned==0 and oldest<=self.cfg.max_deep_scan_age_sec,
                "eligible":len(eligible),"unscanned":unscanned,"oldest_age":oldest}

    def system_safety(self):
        now=time.time();active=list(self.active.values())
        scan_limit=max(90.0,self.cfg.scan_interval_sec+self.last_scan_duration+35.0)
        rest_age=now-self.bybit.last_success_at if self.bybit and self.bybit.last_success_at else 999999.0
        rest_ok=rest_age<=max(45.0,self.cfg.scan_interval_sec*2.0)
        scan_age=now-self.last_scan_at if self.last_scan_at else 999999.0
        scan_ok=scan_age<=scan_limit
        coverage=self.coverage_health(now)
        worst_price=max((self._active_price_age(x,now) for x in active),default=0.0)
        worst_context=max((self._active_context_age(x,now) for x in active),default=0.0)
        data_fresh=(not active) or worst_price<=self.cfg.market_data_stale_sec
        context_fresh=(not active) or worst_context<=self.cfg.active_context_stale_sec
        worst_ws=self._worst_ws_tick_age(now) if active else 0.0
        ws_ok=(not active) or (self.ws_connected and worst_ws<=self.cfg.ws_watchdog_sec)
        monitor_age=now-self.last_active_monitor_at if self.last_active_monitor_at else 999999.0
        monitor_ok=(not active) or monitor_age<=max(30.0,self.cfg.active_monitor_sec*2.5)
        recent_rl=bool(self.bybit and self.bybit.last_rate_limit_at and now-self.bybit.last_rate_limit_at<300)
        ip_cooldown=max(0.0,(self.bybit.ip_blocked_until-now) if self.bybit else 0.0)
        discord_recent_failure=bool(self.last_discord_failure_at and now-self.last_discord_failure_at<600)
        if not data_fresh or not context_fresh or not rest_ok or not scan_ok or not coverage['ok'] or ip_cooldown>0:
            state='UNSAFE';icon='🔴'
        elif not ws_ok or not monitor_ok or recent_rl or discord_recent_failure:
            state='DEGRADED';icon='🟡'
        else:
            state='HEALTHY';icon='🟢'
        return {'state':state,'icon':icon,'rest_ok':rest_ok,'rest_age':rest_age,
                'scan_ok':scan_ok,'scan_age':scan_age,'coverage':coverage,
                'ws_ok':ws_ok,'worst_ws_age':worst_ws,'data_fresh':data_fresh,
                'worst_price_age':worst_price,'context_fresh':context_fresh,
                'worst_context_age':worst_context,'monitor_ok':monitor_ok,'monitor_age':monitor_age,
                'recent_rate_limit':recent_rl,'rate_limit_count':self.bybit.rate_limit_count if self.bybit else 0,
                'ip_cooldown':ip_cooldown,'discord_recent_failure':discord_recent_failure}

    async def safety_watch_loop(self):
        """Notify once on ACTIVE data freeze and once after recovery."""
        await asyncio.sleep(3)
        while True:
            try:
                sf=self.system_safety();now=time.time()
                stale=bool(self.active) and (not sf['data_fresh'] or not sf['context_fresh'])
                if stale:
                    if not self.data_stale_since:self.data_stale_since=now
                    if not self.data_stale and now-self.data_stale_since>=self.cfg.safety_alert_grace_sec:
                        self.data_stale=True
                        delivered=await system_safety_alert(self.session,self.cfg,False,
                            f"ACTIVE management is frozen. Worst price age {sf['worst_price_age']:.1f}s; context age {sf['worst_context_age']:.1f}s. REST fallback/reconnect continues automatically.")
                        self._record_delivery(delivered,"DATA STALE",critical=True)
                        log.error('DATA STALE: ACTIVE management frozen')
                else:
                    self.data_stale_since=0.0
                    if self.data_stale:
                        self.data_stale=False
                        delivered=await system_safety_alert(self.session,self.cfg,True,
                            'Fresh Bybit price/context restored. ACTIVE management resumed automatically.')
                        self._record_delivery(delivered,"DATA RECOVERED",critical=True)
                        log.info('DATA RECOVERED: ACTIVE management resumed')
                self.last_safety_state=sf['state']
            except Exception as e:
                self.last_error=f'safety watch {type(e).__name__}: {e}';log.exception('Safety watch failed')
            await asyncio.sleep(2)

    def request_scan(self):
        self.scan_requested.set()

    def potentials(self,n=10):
        rows=[x for x in self.last_results.values() if x.status in {"EXECUTE","POTENTIAL"}]
        return sorted(rows,key=lambda x:x.score,reverse=True)[:n]

    def bias_rows(self,n=5):
        rows=sorted(self.last_results.values(),key=lambda x:x.score,reverse=True)
        longs=[x for x in rows if x.side=="LONG"][:n]
        shorts=[x for x in rows if x.side=="SHORT"][:n]
        return longs,shorts

    def health(self):
        sf=self.system_safety() if self.bybit else {'state':'STARTING','icon':'🟡'}
        return {
            "uptime":time.time()-self.started_at,
            "markets":len(self.live),"active":len(self.active),
            "last_scan_age":time.time()-self.last_scan_at if self.last_scan_at else 999999,
            "last_scan_duration":self.last_scan_duration,
            "hotlist":len(self.hotlist),
            "ws_connected":self.ws_connected,
            "last_ws_tick_age":time.time()-self.last_ws_tick_at if self.last_ws_tick_at else 999999,
            "ws_reconnects":self.ws_reconnects,
            "rest_latency":self.bybit.last_latency_sec if self.bybit else 0.0,
            "discord_delivery_failures":self.discord_delivery_failures,
            "discord_command_repairs":self.discord_command_repairs,
            "last_discord_command_audit_age":time.time()-self.last_discord_command_audit_at if self.last_discord_command_audit_at else 999999,
            "safety":sf,
            "last_error":self.last_error,
        }

    async def run(self):
        await self.init()
        tasks=[
            asyncio.create_task(self.scan_loop(),name="scan"),
            asyncio.create_task(self.hot_monitor_loop(),name="early-hot-monitor"),
            asyncio.create_task(self.active_ws_loop(),name="active-ws"),
            asyncio.create_task(self.active_context_loop(),name="active-context"),
            asyncio.create_task(self.active_monitor_loop(),name="active-rest-wick-monitor"),
            asyncio.create_task(self.performance_loop(),name="performance"),
            asyncio.create_task(self.safety_watch_loop(),name="safety-watch"),
        ]
        try:await asyncio.gather(*tasks)
        finally:
            for t in tasks:t.cancel()
            await self.close()
