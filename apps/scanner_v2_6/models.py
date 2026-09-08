from dataclasses import dataclass,field
from typing import Optional

@dataclass
class Candle:
    ts:int;o:float;h:float;l:float;c:float;vol:float;quote_vol:float;confirm:bool=True

@dataclass
class MarketTicker:
    inst_id:str;base:str;last:float;open24h:float;high24h:float;low24h:float
    quote_vol_24h:float;bid:float;ask:float;ts:float
    @property
    def change24(self):
        return (self.last/self.open24h-1)*100 if self.open24h>0 else 0
    @property
    def spread_pct(self):
        mid=(self.bid+self.ask)/2 if self.bid and self.ask else 0
        return (self.ask-self.bid)/mid*100 if mid else 0

@dataclass
class TimeframeView:
    trend:str="NEUTRAL";ema_fast:float=0;ema_slow:float=0;rsi:float=50;atr:float=0
    volume_ratio:float=1;return_pct:float=0;structure:str="MIXED"
    support:float=0;resistance:float=0

@dataclass
class TradeAnalysis:
    inst_id:str;base:str;side:str;status:str;score:float;quality:str
    price:float;entry_low:float;entry_high:float;sl:float;tp1:float;tp2:float;tp3:float
    rr_tp2:float;bias_1h:str;setup_15m:str;trigger_5m:str
    btc_context:str;eth_context:str;relative_strength:float
    spread_pct:float;volume_ratio_5m:float;atr_5m:float
    trigger_candle_ts:int;fresh:bool;too_late:bool
    reasons:list[str]=field(default_factory=list);blocks:list[str]=field(default_factory=list)
    # V2.6 signal-core evidence. Defaults keep old DB/tests/API consumers compatible.
    regime_4h:str="NEUTRAL"
    micro_1m:str="NO 1M DATA"
    micro_confirmations:int=0
    atr_5m_pct:float=0.0
    stop_atr:float=0.0
    stop_pct:float=0.0
    obstacle_rr:float=0.0
    core_version:str="2.5"
    edge_sample:int=0
    edge_net_r:float=0.0
    edge_tp2_rate:float=0.0
    edge_label:str="COLLECTING"

@dataclass
class ActiveSignal:
    id:int;inst_id:str;base:str;side:str;quality:str;score:float
    confirmed_at:float;entry:float;entry_low:float;entry_high:float
    sl:float;tp1:float;tp2:float;tp3:float;expires_at:float
    tp1_hit:bool=False;tp2_hit:bool=False;tp3_hit:bool=False
    status:str="ACTIVE";last_price:float=0;max_gain_pct:float=0;max_drawdown_pct:float=0
    entry_window_notified:bool=False
    setup_type:str="UNKNOWN"
    last_checked_at:float=0.0
    validity_state:str="NORMAL"
    validity_score:float=50.0
    validity_note:str="Initial entry window"
    shadow_status:str="PENDING"
    shadow_note:str=""
    shadow_suggested_sl:float=0.0
    # Runtime-only V2.6 freshness timestamps; no database migration required.
    last_price_at:float=0.0
    last_context_at:float=0.0


@dataclass
class EarlyAnalysis:
    inst_id:str;base:str;side:str;stage:str;score:float;price:float
    distance_atr:float;projected_volume_ratio:float;momentum_1m_pct:float
    micro_aligned:bool;seconds_to_close:int;trigger_hint:str;candle_ts:int
    reasons:list[str]=field(default_factory=list)

@dataclass
class ShadowAssessment:
    inst_id:str;would_block:bool;status:str;suggested_sl:float;suggested_sl_atr:float
    micro_momentum_pct:float;checked_at:float
    reasons:list[str]=field(default_factory=list)
