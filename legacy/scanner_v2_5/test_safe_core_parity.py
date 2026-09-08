
from pathlib import Path
from config import Config

root=Path(__file__).resolve().parent
strategy=(root/'strategy.py').read_text(encoding='utf-8')
c=Config()
assert c.execute_score==82
assert c.potential_score==70
assert c.min_rr_tp2==1.8
assert c.volume_ratio_trigger==1.15
assert c.max_spread_pct==0.20
assert c.max_chase_atr==1.30
assert c.signal_cooldown_sec==1800
assert c.same_candle_cooldown_sec==600
assert 'shadow_max_estimated_cost_r' not in strategy
assert 'trigger_close=c5[-1].c' in strategy
print('OK: confirmed-candle strategy thresholds remain explicit; cost gate stays outside strategy.py')
