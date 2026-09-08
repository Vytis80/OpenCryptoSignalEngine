
import ast
import hashlib
import inspect
from config import Config
from strategy import analyze_v25

# V2.6 intentionally replaces the production core, but the exact V2.5
# baseline remains frozen in the same module for replay/A-B comparison.
node=ast.parse(inspect.getsource(analyze_v25)).body[0]
node.name='analyze'
baseline_hash=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
EXPECTED='1458d94812ff37f2ee1b6279553c15f26bda57f29ae959c792174b4c2198a11b'
assert baseline_hash==EXPECTED, f'frozen V2.5 comparison core changed: {baseline_hash}'
c=Config()
assert c.execute_score==82
assert c.potential_score==70
assert c.min_rr_tp2==1.8
assert c.volume_ratio_trigger==1.15
assert c.max_spread_pct==0.20
assert c.max_chase_atr==1.30
assert c.signal_cooldown_sec==1800
assert c.same_candle_cooldown_sec==600
print('OK: frozen V2.5 baseline is intact; common thresholds remain explicit')
