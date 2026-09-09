from dataclasses import dataclass
import os
from dotenv import load_dotenv
load_dotenv()

def _i(n,d):
    try:return int(os.getenv(n,d))
    except:return d
def _f(n,d):
    try:return float(os.getenv(n,d))
    except:return d
def _b(n,d):
    v=os.getenv(n)
    return d if v is None else v.strip().lower() in {"1","true","yes","on"}

@dataclass(frozen=True)
class Config:
    rest_url:str=os.getenv("BYBIT_REST_URL","https://api.bybit.com").rstrip("/")
    quote:str=os.getenv("QUOTE","USDT").upper()
    bybit_min_request_interval_sec:float=_f("BYBIT_MIN_REQUEST_INTERVAL_SEC",0.05)
    bybit_retry_429_base_sec:float=_f("BYBIT_RETRY_429_BASE_SEC",1.0)

    # Scanning
    scan_interval_sec:int=_i("SCAN_INTERVAL_SEC",30)
    universe_refresh_sec:int=_i("UNIVERSE_REFRESH_SEC",1800)
    deep_candidates_per_scan:int=_i("DEEP_CANDIDATES_PER_SCAN",24)
    deep_concurrency:int=_i("DEEP_CONCURRENCY",6)
    min_24h_quote_volume:float=_f("MIN_24H_QUOTE_VOLUME",3_000_000)
    core_symbols:str=os.getenv("CORE_SYMBOLS","BTC,ETH,SOL,XRP,DOGE,HYPE,LINK,SUI,AAVE,AVAX,ADA,BNB,PEPE")
    rotating_candidates:int=_i("ROTATING_CANDIDATES",8)

    # SAFE EARLY layer — alerts earlier, never lowers EXECUTE requirements.
    early_enabled:bool=_b("EARLY_ENABLED",True)
    # Discord noise control: keep EARLY engine running, but only push stages you actually want.
    early_discord_alerts:bool=_b("EARLY_DISCORD_ALERTS",False)
    potential_discord_alerts:bool=_b("POTENTIAL_DISCORD_ALERTS",True)
    early_cancelled_discord_alerts:bool=_b("EARLY_CANCELLED_DISCORD_ALERTS",False)
    hotlist_size:int=_i("HOTLIST_SIZE",8)
    hot_monitor_sec:float=_f("HOT_MONITOR_SEC",7.0)
    hot_concurrency:int=_i("HOT_CONCURRENCY",4)
    early_velocity_seeds:int=_i("EARLY_VELOCITY_SEEDS",4)
    early_min_base_score:float=_f("EARLY_MIN_BASE_SCORE",52)
    early_alert_score:float=_f("EARLY_ALERT_SCORE",62)
    early_potential_score:float=_f("EARLY_POTENTIAL_SCORE",72)
    early_trigger_distance_atr:float=_f("EARLY_TRIGGER_DISTANCE_ATR",0.90)
    early_potential_distance_atr:float=_f("EARLY_POTENTIAL_DISTANCE_ATR",0.45)
    early_min_projected_volume:float=_f("EARLY_MIN_PROJECTED_VOLUME",0.75)
    early_potential_projected_volume:float=_f("EARLY_POTENTIAL_PROJECTED_VOLUME",0.95)
    early_potential_max_sec_to_close:int=_i("EARLY_POTENTIAL_MAX_SEC_TO_CLOSE",210)
    early_cancel_misses:int=_i("EARLY_CANCEL_MISSES",2)
    early_realert_sec:int=_i("EARLY_REALERT_SEC",300)

    # Strategy
    execute_score:float=_f("EXECUTE_SCORE",82)
    potential_score:float=_f("POTENTIAL_SCORE",70)
    min_rr_tp2:float=_f("MIN_RR_TP2",1.8)
    volume_ratio_trigger:float=_f("VOLUME_RATIO_TRIGGER",1.15)
    max_spread_pct:float=_f("MAX_SPREAD_PCT",0.20)
    max_chase_atr:float=_f("MAX_CHASE_ATR",1.30)
    signal_validity_sec:int=_i("SIGNAL_VALIDITY_SEC",900)
    signal_cooldown_sec:int=_i("SIGNAL_COOLDOWN_SEC",1800)
    same_candle_cooldown_sec:int=_i("SAME_CANDLE_COOLDOWN_SEC",600)
    context_hard_block:bool=_b("CONTEXT_HARD_BLOCK",True)
    result_ttl_sec:int=_i("RESULT_TTL_SEC",180)

    # Dynamic entry validity. This changes only NEW-entry validity, never closes an entered trade.
    dynamic_validity_enabled:bool=_b("DYNAMIC_VALIDITY_ENABLED",True)
    dynamic_validity_min_sec:int=_i("DYNAMIC_VALIDITY_MIN_SEC",180)
    dynamic_validity_max_sec:int=_i("DYNAMIC_VALIDITY_MAX_SEC",1800)

    # ACTIVE monitoring: Bybit public linear WebSocket price + frequent full-context refresh.
    bybit_ws_public_url:str=os.getenv("BYBIT_WS_PUBLIC_URL","wss://stream.bybit.com/v5/public/linear").strip()
    active_monitor_sec:int=_i("ACTIVE_MONITOR_SEC",12)  # REST wick safety net
    active_context_sec:float=_f("ACTIVE_CONTEXT_SEC",10.0)
    active_context_concurrency:int=_i("ACTIVE_CONTEXT_CONCURRENCY",2)
    realtime_excursion_write_sec:float=_f("REALTIME_EXCURSION_WRITE_SEC",5.0)

    # Legacy SHADOW never mutates the scanner strategy and is diagnostic while
    # the downstream AutoTrader is in ALL_EXECUTE mode.
    shadow_anti_sl_enabled:bool=_b("SHADOW_ANTI_SL_ENABLED",True)
    shadow_swing_lookback:int=_i("SHADOW_SWING_LOOKBACK",7)
    shadow_buffer_atr:float=_f("SHADOW_BUFFER_ATR",0.20)
    shadow_min_stop_atr:float=_f("SHADOW_MIN_STOP_ATR",0.65)
    shadow_max_stop_atr:float=_f("SHADOW_MAX_STOP_ATR",1.60)
    shadow_max_5m_spike_atr:float=_f("SHADOW_MAX_5M_SPIKE_ATR",2.20)
    shadow_max_1m_spike_atr:float=_f("SHADOW_MAX_1M_SPIKE_ATR",0.65)
    shadow_min_aligned_1m:int=_i("SHADOW_MIN_ALIGNED_1M",2)
    # Estimated fee + slippage on one fill, expressed in price-percent units.
    # 0.075 means 0.075%, not a 7.5% decimal fraction.
    shadow_estimated_one_way_cost_pct:float=_f("SHADOW_ESTIMATED_ONE_WAY_COST_PCT",0.075)
    shadow_max_estimated_cost_r:float=_f("SHADOW_MAX_ESTIMATED_COST_R",0.12)
    # Retained for compatibility with SHADOW_MANUAL deployments. ALL_EXECUTE
    # ignores this legacy gate and forwards every final EXECUTE.
    shadow_manual_gate_all_shorts:bool=_b("SHADOW_MANUAL_GATE_ALL_SHORTS",True)

    # SMART V2.5.1 is observation-only. It labels every normal EXECUTE and
    # records live management counterfactuals, but never gates an entry or
    # sends an order-changing instruction to AutoTrader.
    smart_shadow_enabled:bool=_b("SMART_SHADOW_ENABLED",True)
    smart_pass_score:float=_f("SMART_PASS_SCORE",70.0)
    smart_caution_score:float=_f("SMART_CAUTION_SCORE",52.0)
    smart_pass_max_cost_r:float=_f("SMART_PASS_MAX_COST_R",0.12)
    smart_block_min_cost_r:float=_f("SMART_BLOCK_MIN_COST_R",0.18)
    smart_funding_crowded_abs:float=_f("SMART_FUNDING_CROWDED_ABS",0.0005)
    smart_oi_participation_pct:float=_f("SMART_OI_PARTICIPATION_PCT",0.30)
    smart_management_history_sec:int=_i("SMART_MANAGEMENT_HISTORY_SEC",60)

    # Optional GPT-OSS AI Judge — observational second opinion only.
    # Public default is opt-in: enabling sends structured signal evidence to the configured provider.
    ai_judge_enabled:bool=_b("AI_JUDGE_ENABLED",False)
    groq_api_key:str=os.getenv("GROQ_API_KEY","").strip()
    ai_judge_model:str=os.getenv("AI_JUDGE_MODEL","openai/gpt-oss-120b").strip()
    ai_judge_base_url:str=os.getenv("AI_JUDGE_BASE_URL","https://api.groq.com/openai/v1").strip()
    ai_judge_timeout_sec:float=_f("AI_JUDGE_TIMEOUT_SEC",5.0)
    ai_judge_reasoning_effort:str=os.getenv("AI_JUDGE_REASONING_EFFORT","low").strip().lower()

    # Tracking
    performance_track_sec:int=_i("PERFORMANCE_TRACK_SEC",3600)
    sqlite_busy_timeout_ms:int=_i("SQLITE_BUSY_TIMEOUT_MS",5000)
    db_path:str=os.getenv("DB_PATH","data/bybit_crypto_scanner_v2.db")

    # Discord
    discord_webhook_url:str=os.getenv("DISCORD_WEBHOOK_URL","").strip()
    discord_username:str=os.getenv("DISCORD_USERNAME","Bybit Trade Scanner").strip()
    discord_bot_token:str=os.getenv("DISCORD_BOT_TOKEN","").strip()
    discord_guild_id:int=_i("DISCORD_GUILD_ID",0)
    discord_control_channel_id:int=_i("DISCORD_CONTROL_CHANNEL_ID",0)
    discord_allowed_user_id:int=_i("DISCORD_ALLOWED_USER_ID",0)


    log_level:str=os.getenv("LOG_LEVEL","INFO").upper()

    @property
    def core(self):
        return {x.strip().upper() for x in self.core_symbols.split(",") if x.strip()}
