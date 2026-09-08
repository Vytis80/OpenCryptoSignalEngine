import ast
import hashlib
from pathlib import Path

from config import Config


ROOT = Path(__file__).resolve().parents[2]
CURRENT_STRATEGY = Path(__file__).resolve().parent / "strategy.py"
LEGACY_STRATEGY = ROOT / "legacy" / "scanner_v2_5" / "strategy.py"


def function_hash(path: Path, function_name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            node.name = "analyze"
            payload = ast.dump(node, include_attributes=False).encode()
            return hashlib.sha256(payload).hexdigest()
    raise AssertionError(f"{function_name!r} not found in {path}")


current_hash = function_hash(CURRENT_STRATEGY, "analyze_v25")
legacy_hash = function_hash(LEGACY_STRATEGY, "analyze")
assert current_hash == legacy_hash, (
    "frozen V2.5 comparison core diverged from the public V2.5 baseline: "
    f"current={current_hash}, legacy={legacy_hash}"
)

c = Config()
assert c.execute_score == 82
assert c.potential_score == 70
assert c.min_rr_tp2 == 1.8
assert c.volume_ratio_trigger == 1.15
assert c.max_spread_pct == 0.20
assert c.max_chase_atr == 1.30
assert c.signal_cooldown_sec == 1800
assert c.same_candle_cooldown_sec == 600

print("OK: frozen V2.5 comparison core matches the public baseline")
