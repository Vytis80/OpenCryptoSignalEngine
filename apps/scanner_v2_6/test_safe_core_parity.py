import ast
import hashlib
import inspect

from config import Config
from strategy import analyze_v25


# V2.6 intentionally keeps the production V2.5 signal core embedded for
# replay/A-B comparison. The public legacy V2.5 tree also contains later
# observation/telemetry fields, so exact AST parity is pinned here instead of
# comparing the two whole functions.
node = ast.parse(inspect.getsource(analyze_v25)).body[0]
node.name = "analyze"
baseline_hash = hashlib.sha256(
    ast.dump(node, include_attributes=False).encode()
).hexdigest()
EXPECTED = "b6b651f5684740a6e72a02e7bb5dd45c0dc6cb1efb9e27142d93d36a24a17756"
assert baseline_hash == EXPECTED, f"frozen V2.5 comparison core changed: {baseline_hash}"

c = Config()
assert c.execute_score == 82
assert c.potential_score == 70
assert c.min_rr_tp2 == 1.8
assert c.volume_ratio_trigger == 1.15
assert c.max_spread_pct == 0.20
assert c.max_chase_atr == 1.30
assert c.signal_cooldown_sec == 1800
assert c.same_candle_cooldown_sec == 600

print("OK: sanitized frozen V2.5 comparison core is intact")
