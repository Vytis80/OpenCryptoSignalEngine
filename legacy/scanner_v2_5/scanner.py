import asyncio,time,logging,math,aiohttp,json
import hashlib
from collections import deque
from pathlib import Path
from config import Config
from bybit import Bybit
from strategy import analyze,tf_view
from storage import Storage
from models import ActiveSignal
from alerts import execute_alert,update_alert,management_alert,entry_window_closed_alert,early_alert,early_cancelled_alert
from enhancements import analyze_early,shadow_assess,dynamic_validity
from bridge_client import DemoBridgeClient
from ai_judge import AIJudge
from smart_engine import MODEL_VERSION as SMART_MODEL_VERSION,assess_management,assess_signal

log=logging.getLogger(__name__)

def dir_move(side,price,entry):
    if not entry:return 0.0
    raw=(price/entry-1)*100
    return raw if side=="LONG" else -raw

class TradeScanner:
    def __init__(self,cfg:Config):
        self.cfg=cfg
        self.session=None;self.bybit=None;self.storage=Storage(cfg.db_path,cfg.sqlite_busy_timeout_ms)
        self.live={}
        self.last_universe_refresh=0
        self.rotation=deque()
        self.scan_lock=asyncio.Lock()
        self.deep_sem=asyncio.Semaphore(cfg.deep_concurrency)
        self.last_results={}
        self.last_result_at={}
        self.last_scan_results=[]
        self.last_scan_at=0
        self.last_scan_duration=0
        self.last_error=""
        self.started_at=time.time()
        self.active={}
        self._context_cache=None
        self._context_cache_at=0
        self._context_lock=asyncio.Lock()
        self.scan_requested=asyncio.Event()
        self.ready_event=asyncio.Event()
        self.management={}  # inst_id -> {action,note,updated_at}
        # SAFE enhancements are sidecars around the confirmed-candle strategy core.
        self.hotlist={}
        self.hot_states={}
        self.hot_sem=asyncio.Semaphore(cfg.hot_concurrency)
        self.ticker_history={}
        self.active_context_sem=asyncio.Semaphore(cfg.active_context_concurrency)
        self.closing=set()
        self.last_excursion_write={}
        self.ws_connected=False
        self.last_ws_tick_at=0.0
        self.demo_bridge=None
        self.last_bridge_delivery_at=0.0
        self.last_bridge_error=""
        self.bridge_outbox_status={}
        self.smart_management={}
        self.ai_judge=None

    async def init(self):
        await self.storage.init()
        self._init_demo_bridge()
        self.session=aiohttp.ClientSession(headers={"User-Agent":"Bybit-5m-Trade-Scanner-V2.5-SAFE/1.0"})
        if self.cfg.ai_judge_enabled and self.cfg.groq_api_key:
            self.ai_judge=AIJudge(self.cfg,self.session)
            log.info("AI JUDGE shadow enabled: %s",self.cfg.ai_judge_model)
        elif self.cfg.ai_judge_enabled:
            log.warning("AI JUDGE enabled but GROQ_API_KEY is missing; AI verdicts unavailable")
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
                s.estimated_cost_r=sh.get("estimated_cost_r") or s.estimated_cost_r
            smart=await self.storage.smart_for_signal(s.id)
            if smart:
                s.smart_status=smart.get("verdict") or "PENDING"
                s.smart_score=float(smart.get("smart_score") or 0)
                s.smart_note=(smart.get("reasons") or "")[:500]
                s.smart_setup=smart.get("setup_family") or "UNKNOWN"
                s.smart_regime=smart.get("regime") or "TRANSITION"
            latest=await self.storage.latest_smart_management(s.id)
            if latest:self.smart_management[s.inst_id]=latest
            self.active[s.inst_id]=s
            self.management[s.inst_id]={"action":"HOLD","note":"Recovered ACTIVE signal; management recalibrating.","updated_at":now}
        log.info("Loaded %s active signals from DB",len(self.active))
        self.ready_event.set()

    async def close(self):
        if self.session:await self.session.close()

    async def refresh_universe(self):
        self.live=await self.bybit.live_perpetuals()
        self.rotation=deque(sorted(self.live))
        self.last_universe_refresh=time.time()
        log.info("Universe: %s live %s linear perpetuals",len(self.live),self.cfg.quote)

    async def context(self,force=False):
        if not force and self._context_cache and time.time()-self._context_cache_at<60:
            return self._context_cache
        async with self._context_lock:
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
        selected=[];seen=set()
        def add(iid):
            if iid in tickers and iid in self.live and iid not in seen:
                seen.add(iid);selected.append(iid)

        # Active signals are always re-analysed.
        for iid in self.active:add(iid)
        # Core liquid names.
        for base in self.cfg.core:add(f"{base}{self.cfg.quote}")
        # Market leaders + liquidity anchors.
        for t in by_move[:7]:add(t.inst_id)
        for t in by_vol[:7]:add(t.inst_id)

        # Rotate through the full liquid universe so quiet coins are not permanently ignored.
        rotation_eligible={t.inst_id for t in eligible}
        attempts=0
        while len(selected)<self.cfg.deep_candidates_per_scan and self.rotation and attempts<len(self.rotation)*2:
            iid=self.rotation[0];self.rotation.rotate(-1);attempts+=1
            if iid in rotation_eligible:add(iid)

        # If still short, fill by liquidity.
        for t in by_vol:
            if len(selected)>=self.cfg.deep_candidates_per_scan:break
            add(t.inst_id)

        # Active may make it slightly larger than configured; keep them + best others.
        active_ids=set(self.active)
        if len(selected)>self.cfg.deep_candidates_per_scan+len(active_ids):
            fixed=[x for x in selected if x in active_ids]
            rest=[x for x in selected if x not in active_ids]
            selected=fixed+rest[:self.cfg.deep_candidates_per_scan]
        return selected,len(eligible)

    async def deep(self,inst_id,ticker,btc_views,eth_views):
        async with self.deep_sem:
            try:
                c1,c15,c5=await asyncio.gather(
                    self.bybit.candles(inst_id,"1H",90),
                    self.bybit.candles(inst_id,"15m",100),
                    self.bybit.candles(inst_id,"5m",120),
                )
                if len(c1)<55 or len(c15)<30 or len(c5)<30:return None
                return analyze(inst_id,ticker,c1,c15,c5,btc_views,eth_views,self.cfg)
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
            q=self.ticker_history.setdefault(iid,deque(maxlen=24))
            q.append((now,tk.last,float(getattr(tk,"open_interest_value",0) or 0),float(getattr(tk,"funding_rate",0) or 0)))
        if len(self.ticker_history)>len(self.live)+50:
            self.ticker_history={k:v for k,v in self.ticker_history.items() if k in self.live}

    def _velocity_pct(self,iid):
        q=self.ticker_history.get(iid)
        if not q or len(q)<2:return 0.0
        newest=q[-1];older=next((x for x in q if newest[0]-x[0]>=15),q[0])
        return (newest[1]/older[1]-1)*100 if older[1]>0 else 0.0

    def _oi_delta_pct(self,iid):
        q=self.ticker_history.get(iid)
        if not q or len(q)<3:return 0.0
        newest=q[-1]
        older=next((x for x in q if newest[0]-x[0]>=240),q[0])
        if newest[0]-older[0]<60 or len(newest)<3 or len(older)<3:return 0.0
        return (newest[2]/older[2]-1)*100 if newest[2]>0 and older[2]>0 else 0.0

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
        for iid in removed:
            st=self.hot_states.pop(iid,None)
            if st and self.cfg.early_cancelled_discord_alerts:
                await early_cancelled_alert(self.session,self.cfg,iid,st.get('side','?'),'Setup dropped from the hotlist / score weakened.')

    async def _fast_early(self,a):
        async with self.hot_sem:
            try:
                c5,c1=await asyncio.gather(self.bybit.candles_live(a.inst_id,'5m',40),self.bybit.candles(a.inst_id,'1m',12))
                return analyze_early(a,c5,c1,self.cfg)
            except Exception as e:
                log.debug('EARLY fast monitor failed %s: %s',a.inst_id,e);return None

    async def _handle_early(self,a,e):
        iid=a.inst_id
        if iid in self.active:
            self.hot_states.pop(iid,None);return
        prev=self.hot_states.get(iid,{})
        if e is None:
            if prev.get('stage') in {'EARLY','POTENTIAL'}:
                prev['misses']=prev.get('misses',0)+1;self.hot_states[iid]=prev
                if prev['misses']>=self.cfg.early_cancel_misses:
                    if self.cfg.early_cancelled_discord_alerts:
                        await early_cancelled_alert(self.session,self.cfg,iid,prev.get('side','?'),'Fast 1m/5m conditions faded before normal EXECUTE confirmation.')
                    self.hot_states.pop(iid,None)
            return
        if prev.get('side') and prev.get('side')!=e.side:
            if self.cfg.early_cancelled_discord_alerts:
                await early_cancelled_alert(self.session,self.cfg,iid,prev.get('side'),'Direction changed before confirmation.')
            prev={}
        rank={'EARLY':1,'POTENTIAL':2};old=prev.get('stage');now=time.time()
        should=rank.get(e.stage,0)>rank.get(old,0)
        if not old and now-prev.get('last_alert',0)>=self.cfg.early_realert_sec:should=True
        pushed=False
        if should:
            push_allowed=(e.stage=='EARLY' and self.cfg.early_discord_alerts) or (e.stage=='POTENTIAL' and self.cfg.potential_discord_alerts)
            if push_allowed:
                await early_alert(self.session,self.cfg,e)
                pushed=True
            log.info('%s %s %s score=%.0f dist=%.2fATR vol=%.2fx discord=%s',e.stage,e.side,iid,e.score,e.distance_atr,e.projected_volume_ratio,'PUSH' if pushed else 'SILENT')
        self.hot_states[iid]={'stage':e.stage,'side':e.side,'candle_ts':e.candle_ts,'last_alert':now if pushed else prev.get('last_alert',0),'misses':0,'analysis':e}

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

        SHADOW never mutates the scanner strategy SL/TP or suppresses its
        EXECUTE event. AutoTrader ALL_EXECUTE records this verdict but does not
        gate on it. Returning it also keeps the verdict in one card.
        """
        if not self.cfg.shadow_anti_sl_enabled:return None
        try:
            c5,c1=await asyncio.gather(self.bybit.candles(a.inst_id,'5m',50),self.bybit.candles(a.inst_id,'1m',12))
            sh=shadow_assess(a,c5,c1,self.cfg)
            await self.storage.save_shadow(s.id,sh)
            if s.inst_id in self.active:
                s.shadow_status=sh.status;s.shadow_note='; '.join(sh.reasons[:3]);s.shadow_suggested_sl=sh.suggested_sl
                s.estimated_cost_r=sh.estimated_cost_r
            log.info('SHADOW %s %s · cost=%.2fR · suggestedSL=%.10g · %s',
                     a.inst_id,sh.status,sh.estimated_cost_r,sh.suggested_sl,'; '.join(sh.reasons[:2]))
            return sh
        except Exception as e:
            log.warning('Shadow assessment failed %s: %s',a.inst_id,e)
            return None

    async def _smart_for_execute(self,s,a):
        if not self.cfg.smart_shadow_enabled:return None
        try:
            c5,c1=await asyncio.gather(
                self.bybit.candles(a.inst_id,"5m",50),
                self.bybit.candles(a.inst_id,"1m",12),
                return_exceptions=True,
            )
            # Enrichment failure must not affect the already-confirmed
            # EXECUTE. SMART can still persist an auditable partial label.
            if isinstance(c5,Exception):
                log.info("SMART 5m enrichment unavailable %s: %s",a.inst_id,c5);c5=[]
            if isinstance(c1,Exception):
                log.info("SMART 1m enrichment unavailable %s: %s",a.inst_id,c1);c1=[]
            assessment=assess_signal(a,c5,c1,self.cfg)
            await self.storage.save_smart_signal(s.id,assessment)
            if s.inst_id in self.active:
                s.smart_status=assessment.verdict;s.smart_score=assessment.score
                s.smart_note="; ".join(assessment.reasons[:3])
                s.smart_setup=assessment.setup_family;s.smart_regime=assessment.regime
            log.info("SMART SIGNAL %s %s %.0f/100 setup=%s regime=%s · %s",
                     a.inst_id,assessment.verdict,assessment.score,assessment.setup_family,
                     assessment.regime,"; ".join(assessment.reasons[:3]))
            return assessment
        except Exception as e:
            log.warning("SMART signal assessment failed %s: %s",a.inst_id,e)
            return None

    async def _ai_for_execute(self,s,a,shadow=None,smart=None):
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

    async def _update_dynamic_validity(self,s,a,c1=None):
        if not self.cfg.dynamic_validity_enabled or s.entry_window_notified:return
        if c1 is None:
            try:c1=await self.bybit.candles(s.inst_id,'1m',10)
            except Exception:c1=[]
        old_exp=s.expires_at;old_state=s.validity_state
        exp,state,score,note=dynamic_validity(s,a,c1,self.cfg)
        s.validity_state=state;s.validity_score=score;s.validity_note=note
        if abs((old_exp or 0)-exp)>=20:
            s.expires_at=exp;await self.storage.update_entry_window(s.id,exp)
        if state=='CLOSED' and not s.entry_window_notified:
            s.entry_window_notified=True
            await entry_window_closed_alert(self.session,self.cfg,s,s.last_price or a.price,self.management_for(s.inst_id)['action'])
            log.info('DYNAMIC ENTRY WINDOW CLOSED %s · %s',s.inst_id,note)
            if self.demo_bridge:
                await self._queue_demo_management(
                    s.id,s.inst_id,"ENTRY_WINDOW_CLOSED",note,s.last_price or a.price,
                    event_key="ENTRY_WINDOW_CLOSED",
                )
        elif old_state!=state:
            log.info('ENTRY VALIDITY %s %s→%s score=%.0f · %s',s.inst_id,old_state,state,score,note)

    async def _update_smart_management(self,s,a,c1):
        if not self.cfg.smart_shadow_enabled:return
        try:
            assessment=assess_management(s,a,c1)
            previous=self.smart_management.get(s.inst_id,{})
            old_action=previous.get("action") if isinstance(previous,dict) else None
            await self.storage.save_smart_management(assessment)
            self.smart_management[s.inst_id]={
                "signal_id":assessment.signal_id,"inst_id":assessment.inst_id,
                "checked_at":assessment.checked_at,"candle_ts":assessment.candle_ts,
                "action":assessment.action,"health_score":assessment.health_score,
                "current_r":assessment.current_r,"max_r":assessment.max_r,
                "giveback_r":assessment.giveback_r,"regime":assessment.regime,
                "reasons":json.dumps(assessment.reasons,ensure_ascii=False),
                "model_version":assessment.model_version,
            }
            if old_action!=assessment.action:
                log.info("SMART MANAGEMENT %s %s→%s health=%.0f current=%+.2fR max=%+.2fR giveback=%.2fR · %s",
                         s.inst_id,old_action or "NEW",assessment.action,assessment.health_score,
                         assessment.current_r,assessment.max_r,assessment.giveback_r,
                         "; ".join(assessment.reasons[:3]))
        except Exception as e:
            log.warning("SMART management assessment failed %s: %s",s.inst_id,e)

    async def _active_context_one(self,iid,s):
        async with self.active_context_sem:
            try:
                tk=await self.bybit.ticker(iid)
                if not tk:return
                btc,eth=await self.context()
                a=await self.deep(iid,tk,btc,eth)
                if not a:return
                a.oi_delta_pct=self._oi_delta_pct(iid)
                s.last_checked_at=time.time()
                if iid in self.active:
                    try:c1=await self.bybit.candles(s.inst_id,'1m',10)
                    except Exception:c1=[]
                    await self._update_dynamic_validity(s,a,c1)
                    await self._update_smart_management(s,a,c1)
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

    async def _realtime_price(self,iid,price):
        if price<=0:return
        s=self.active.get(iid)
        if not s or iid in self.closing:return
        now=time.time();s.last_price=price;s.last_checked_at=now;self.last_ws_tick_at=now
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
        """Real-time Bybit last-price stream for ACTIVE signals. REST monitor remains a wick safety net."""
        while True:
            try:
                async with self.session.ws_connect(self.cfg.bybit_ws_public_url,heartbeat=20,receive_timeout=None) as ws:
                    self.ws_connected=True;subscribed=set();last_ping=time.monotonic();log.info('ACTIVE WS connected')
                    while True:
                        desired=set(self.active)
                        add=desired-subscribed;remove=subscribed-desired
                        if add:await ws.send_json({'op':'subscribe','args':[f'tickers.{x}' for x in sorted(add)]})
                        if remove:await ws.send_json({'op':'unsubscribe','args':[f'tickers.{x}' for x in sorted(remove)]})
                        subscribed=desired
                        if time.monotonic()-last_ping>=20:
                            await ws.send_json({'op':'ping'});last_ping=time.monotonic()
                        try:msg=await asyncio.wait_for(ws.receive(),timeout=2.0)
                        except asyncio.TimeoutError:continue
                        if msg.type==aiohttp.WSMsgType.TEXT:
                            d=json.loads(msg.data);topic=d.get('topic','')
                            if topic.startswith('tickers.'):
                                rows=d.get('data',[])
                                if isinstance(rows,dict):rows=[rows]
                                for x in rows:
                                    try:
                                        px=float(x.get('lastPrice') or 0)
                                        sym=x.get('symbol') or topic.split('.',1)[1]
                                        if px>0:await self._realtime_price(sym,px)
                                    except Exception as e:log.debug('WS ticker handling failed: %s',e)
                        elif msg.type in {aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR}:raise RuntimeError('Bybit active websocket closed')
            except asyncio.CancelledError:raise
            except Exception as e:
                self.ws_connected=False;self.last_error=f'active ws {type(e).__name__}: {e}';log.warning('ACTIVE WS disconnected: %s; reconnecting',e);await asyncio.sleep(2)


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
        action,note=self._management_decision(s,a)
        cur=self.management_for(a.inst_id)
        rank={"HOLD":0,"PROTECT":1,"TRAIL":2,"CLOSE EARLY":3}
        if action!="CLOSE EARLY" and rank.get(action,0)<=rank.get(cur.get("action","HOLD"),0):
            cur["note"]=note;self.management[a.inst_id]=cur;return
        if action=="CLOSE EARLY":
            await self._close_active(s,"CLOSE_EARLY",a.price,
                f"🔴 CLOSE EARLY — {s.inst_id}",
                f"**Recommended action: close the remaining position.**\n{note}\n\n"
                "In the integrated Demo system this decision is relayed to AutoTrader and may close the Demo position.")
            return
        self.management[a.inst_id]={"action":action,"note":note,"updated_at":time.time()}
        await management_alert(self.session,self.cfg,s,action,note,a.price)

        if self.demo_bridge and action in {"PROTECT","TRAIL"}:
            await self._queue_demo_management(
                s.id,s.inst_id,"PROTECT",f"{action}: {note}",a.price,
                event_key=f"MANAGEMENT_{action.replace(' ', '_')}",
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
            timeout_sec=60.0
        )

        log.info(
            "DEMO bridge enabled -> %s",
            url
        )

    def _bridge_event_id(self,signal_id,event_key):
        event_key=str(event_key).strip().upper().replace(" ","_")
        raw=f"{signal_id}:{event_key}"
        if len(raw)<=128:return raw
        return f"{str(signal_id)[:48]}:{hashlib.sha256(raw.encode()).hexdigest()}"

    async def _queue_demo_execute(self,s):
        if not self.demo_bridge:return
        expires_at=float(getattr(s,"expires_at",0) or 0)
        source_ts=float(getattr(s,"confirmed_at",0) or time.time())
        payload=self.demo_bridge.execute_payload(
            signal_id=s.id,symbol=s.inst_id,side=s.side,entry=s.entry,
            entry_low=s.entry_low,entry_high=s.entry_high,sl=s.sl,
            tp1=s.tp1,tp2=s.tp2,tp3=s.tp3,quality=s.quality,score=s.score,
            setup_type=s.setup_type,shadow_status=getattr(s,"shadow_status","") or "",
            shadow_note=getattr(s,"shadow_note","") or "",expires_at=expires_at,
            smart_status=getattr(s,"smart_status","") or "",
            smart_score=getattr(s,"smart_score",0) or 0,
            smart_note=getattr(s,"smart_note","") or "",
            smart_setup=getattr(s,"smart_setup","") or "",
            smart_regime=getattr(s,"smart_regime","") or "",
            source_ts=source_ts,
        )
        await self.storage.enqueue_bridge(f"EXECUTE:{s.id}","EXECUTE",payload)

    async def _queue_demo_management(self,signal_id,symbol,action,reason="",price=None,new_sl=None,event_key=None):
        if not self.demo_bridge:return
        event_id=self._bridge_event_id(signal_id,event_key or action)
        payload=self.demo_bridge.management_payload(
            event_id=event_id,signal_id=signal_id,symbol=symbol,action=action,
            reason=reason,price=price,new_sl=new_sl,source_ts=time.time(),
        )
        await self.storage.enqueue_bridge(event_id,"MANAGEMENT",payload)

    async def bridge_outbox_loop(self):
        """Deliver persisted bridge events and resume automatically after restart."""
        while True:
            try:
                if not self.demo_bridge:
                    await asyncio.sleep(5);continue
                rows=await self.storage.pending_bridge(25)
                for row in rows:
                    try:
                        result=await self.demo_bridge.send(json.loads(row["payload_json"]))
                        await self.storage.mark_bridge_delivered(row["event_id"])
                        self.last_bridge_delivery_at=time.time();self.last_bridge_error=""
                        log.info("DEMO OUTBOX delivered %s response=%s",row["event_id"],result)
                    except asyncio.CancelledError:raise
                    except Exception as e:
                        self.last_bridge_error=f"{type(e).__name__}: {e}"
                        await self.storage.mark_bridge_retry(row["event_id"],self.last_bridge_error)
                        log.warning("DEMO OUTBOX retry scheduled %s: %s",row["event_id"],e)
                self.bridge_outbox_status=await self.storage.bridge_outbox_counts()
                await asyncio.sleep(1 if rows else 2)
            except asyncio.CancelledError:raise
            except Exception as e:
                self.last_bridge_error=f"outbox {type(e).__name__}: {e}"
                log.exception("DEMO bridge outbox loop failed")
                await asyncio.sleep(2)

    async def maybe_new_signal(self,a):
        if a.status!="EXECUTE" or a.inst_id in self.active:return
        last_ts,last_candle=await self.storage.last_confirmed(a.inst_id)
        now=time.time()
        if now-last_ts<self.cfg.signal_cooldown_sec:return
        if last_candle==a.trigger_candle_ts and now-last_ts<self.cfg.same_candle_cooldown_sec:return

        trigger_end=a.trigger_candle_ts/1000.0+300.0
        a.analysis_delay_sec=max(0.0,now-trigger_end)
        a.stop_pct=(abs(a.price-a.sl)/a.price*100.0) if a.price>0 else 0.0
        a.estimated_cost_r=(
            2.0*self.cfg.shadow_estimated_one_way_cost_pct/a.stop_pct
            if a.stop_pct>0 else float("inf")
        )
        expires=now+self.cfg.signal_validity_sec
        sid=await self.storage.create_signal(a,expires,confirmed_at=now)
        s=ActiveSignal(sid,a.inst_id,a.base,a.side,a.quality,a.score,now,a.price,a.entry_low,a.entry_high,
                       a.sl,a.tp1,a.tp2,a.tp3,expires,last_price=a.price,setup_type=a.trigger_5m,last_checked_at=now,
                       trigger_candle_ts=a.trigger_candle_ts,trigger_close=a.trigger_close,
                       analysis_delay_sec=a.analysis_delay_sec,stop_pct=a.stop_pct,
                       volume_ratio_5m=a.volume_ratio_5m,relative_strength=a.relative_strength,
                       spread_pct=a.spread_pct,estimated_cost_r=a.estimated_cost_r)
        if self.cfg.dynamic_validity_enabled:
            dyn_exp,state,vscore,vnote=dynamic_validity(s,a,[],self.cfg,now)
            s.expires_at=dyn_exp;s.validity_state=state;s.validity_score=vscore;s.validity_note=vnote
            await self.storage.update_entry_window(s.id,dyn_exp)
        self.active[a.inst_id]=s
        self.management[a.inst_id]={"action":"HOLD","note":"Fresh EXECUTE; original setup intact.","updated_at":time.time()}
        # Compute legacy SHADOW and SMART observations first. Neither changes
        # this confirmed EXECUTE or its SL/TP in ALL_EXECUTE mode.
        sh=await self._shadow_for_execute(s,a)
        smart=await self._smart_for_execute(s,a)

        # Relay ONLY the already-confirmed/persisted EXECUTE signal.
        # This is a sidecar: bridge failure never changes scanner strategy.
        if self.demo_bridge:
            await self._queue_demo_execute(s)
        # V2.5 bridge is already queued above; AI remains observational and cannot
        # veto or change Entry/SL/TP/size/management.
        ai_judgement=await self._ai_for_execute(s,a,sh,smart)
        await execute_alert(self.session,self.cfg,a,s.expires_at,sh,smart,ai_judgement)
        log.warning("EXECUTE %s %s score=%.0f smart=%s/%.0f entry=%.8g SL=%.8g TP2=%.8g",
                    a.side,a.inst_id,a.score,getattr(s,"smart_status","PENDING"),
                    getattr(s,"smart_score",0),a.price,a.sl,a.tp2)

    async def maybe_invalidate(self,a):
        s=self.active.get(a.inst_id)
        if not s or s.tp1_hit:return
        opposite=(a.side!=s.side and a.score>=78)
        structural=(s.side=="LONG" and a.bias_1h=="BEARISH" and a.setup_15m.startswith("BEARISH")) or \
                   (s.side=="SHORT" and a.bias_1h=="BULLISH" and a.setup_15m.startswith("BULLISH"))
        if opposite or structural:
            await self._close_active(s,"INVALIDATED",a.price,
                f"❌ **SIGNAL INVALIDATED — {s.inst_id}**",
                "1h/15m structure no longer supports the original setup.")

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
                tasks=[self.deep(iid,tickers[iid],btc,eth) for iid in candidates if iid in tickers]
                rows=await asyncio.gather(*tasks)
                rows=[x for x in rows if x]
                rows.sort(key=lambda x:x.score,reverse=True)
                self.last_scan_results=rows
                self.last_scan_at=time.time()
                self.last_scan_duration=self.last_scan_at-start
                for a in rows:
                    self.last_results[a.inst_id]=a
                    self.last_result_at[a.inst_id]=self.last_scan_at
                cutoff=self.last_scan_at-self.cfg.result_ttl_sec
                stale=[iid for iid,ts in self.last_result_at.items() if ts<cutoff]
                for iid in stale:
                    self.last_result_at.pop(iid,None);self.last_results.pop(iid,None)
                await self._refresh_hotlist(rows,tickers,btc,eth)

                for a in rows:
                    a.oi_delta_pct=self._oi_delta_pct(a.inst_id)
                    if a.inst_id in self.active:
                        await self.maybe_invalidate(a)
                        if a.inst_id in self.active:
                            await self.maybe_manage(a)
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
        # Claim the close before the first await so WS/REST monitors cannot both
        # close the same signal. Persist the bridge instruction before removing
        # the ACTIVE row; a transient DB failure then remains safely retryable.
        self.closing.add(s.inst_id)
        try:
            # Exchange SL/TP are already real Bybit Demo orders. Only lifecycle
            # closes that require an active decision are relayed.
            if self.demo_bridge:
                demo_action = reason if reason in {"INVALIDATED","CLOSE_EARLY"} else "SIGNAL_CLOSED"
                await self._queue_demo_management(
                    s.id,s.inst_id,demo_action,f"{reason}: {text or reason}",price,
                    event_key=f"CLOSE_{reason}",
                )
            s.status="CLOSED"
            await self.storage.close_signal(s.id,reason,price)
        except BaseException:
            s.status="ACTIVE"
            self.closing.discard(s.inst_id)
            raise
        self.active.pop(s.inst_id,None);self.management.pop(s.inst_id,None);self.closing.discard(s.inst_id)
        getattr(self,"smart_management",{}).pop(s.inst_id,None)
        title=title or f"✅ SIGNAL CLOSED — {s.inst_id}"
        text=text or f"Reason: **{reason}**\nClose `{price:.10g}`"
        color=0x2ECC71 if reason=="TP3" else 0xE74C3C if reason in {"SL","INVALIDATED","CLOSE_EARLY"} else 0x95A5A6
        await update_alert(self.session,self.cfg,s,title,text,color)

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
        await update_alert(self.session,self.cfg,s,f"✅ TP{n} HIT — {s.inst_id}",
                           f"Target `{target:.10g}` reached.\nCurrent `{price:.10g}`\n\n**Management: {action}**\n{mg}",
                           0x2ECC71)

    async def active_monitor_loop(self):
        while True:
            try:
                if not self.active:
                    await asyncio.sleep(self.cfg.active_monitor_sec);continue
                tickers=await self.bybit.tickers()
                for iid,s in list(self.active.items()):
                    t=tickers.get(iid)
                    if not t:continue
                    s.last_price=t.last;s.last_checked_at=time.time()
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
                            await entry_window_closed_alert(self.session,self.cfg,s,t.last,self.management_for(iid)["action"])
                        log.info("ENTRY WINDOW CLOSED %s; ACTIVE management continues",iid)
                        if self.demo_bridge:
                            await self._queue_demo_management(
                                s.id,s.inst_id,"ENTRY_WINDOW_CLOSED",
                                "Scanner entry validity expired",t.last,
                                event_key="ENTRY_WINDOW_CLOSED",
                            )
            except Exception as e:
                self.last_error=f"monitor {type(e).__name__}: {e}"
                log.exception("Active monitor failed")
            await asyncio.sleep(self.cfg.active_monitor_sec)

    async def performance_loop(self):
        while True:
            try:
                rows=await self.storage.recent(150)
                if rows:
                    now=time.time()
                    for r in rows:
                        ct=r["confirmed_at"];entry=r["entry"]
                        if not ct or not entry or now-ct>self.cfg.performance_track_sec+300:continue
                        done=await self.storage.snapshot_done(r["id"])
                        due=[h for h in (5,15,30,60) if h not in done and now>=ct+h*60]
                        if not due:continue
                        # Use the candle nearest each historical horizon. The old
                        # implementation used the current ticker whenever this
                        # loop happened to run, biasing delayed/restart snapshots.
                        history=await self.bybit.candles(r["inst_id"],"1m",70)
                        for h in due:
                            target=ct+h*60
                            bar=next((c for c in history if c.ts/1000.0+60>=target),None)
                            if not bar:continue
                            sample_ts=bar.ts/1000.0+60
                            if sample_ts-target>90:continue
                            mv=dir_move(r["side"],bar.c,entry)
                            await self.storage.snapshot(r["id"],h,bar.c,mv,sample_ts=sample_ts)
            except Exception as e:
                self.last_error=f"performance {type(e).__name__}: {e}"
                log.exception("Performance loop failed")
            await asyncio.sleep(15)

    def request_scan(self):
        self.scan_requested.set()

    def potentials(self,n=10):
        cutoff=time.time()-self.cfg.result_ttl_sec
        rows=[x for iid,x in self.last_results.items()
              if self.last_result_at.get(iid,0)>=cutoff and x.status in {"EXECUTE","POTENTIAL"}]
        return sorted(rows,key=lambda x:x.score,reverse=True)[:n]

    def bias_rows(self,n=5):
        cutoff=time.time()-self.cfg.result_ttl_sec
        rows=sorted((x for iid,x in self.last_results.items() if self.last_result_at.get(iid,0)>=cutoff),
                    key=lambda x:x.score,reverse=True)
        longs=[x for x in rows if x.side=="LONG"][:n]
        shorts=[x for x in rows if x.side=="SHORT"][:n]
        return longs,shorts

    def health(self):
        return {
            "uptime":time.time()-self.started_at,
            "markets":len(self.live),"active":len(self.active),
            "last_scan_age":time.time()-self.last_scan_at if self.last_scan_at else 999999,
            "last_scan_duration":self.last_scan_duration,
            "hotlist":len(self.hotlist),
            "ws_connected":self.ws_connected,
            "last_ws_tick_age":time.time()-self.last_ws_tick_at if self.last_ws_tick_at else 999999,
            "bridge_outbox":dict(self.bridge_outbox_status),
            "last_bridge_delivery_age":time.time()-self.last_bridge_delivery_at if self.last_bridge_delivery_at else 999999,
            "last_bridge_error":self.last_bridge_error,
            "smart_shadow":bool(self.cfg.smart_shadow_enabled),
            "smart_model":SMART_MODEL_VERSION,
            "smart_managed":len(self.smart_management),
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
            asyncio.create_task(self.bridge_outbox_loop(),name="demo-bridge-outbox"),
        ]
        try:await asyncio.gather(*tasks)
        finally:
            for t in tasks:t.cancel()
            await self.close()
