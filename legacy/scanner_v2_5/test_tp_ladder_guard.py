from pathlib import Path

from strategy import _valid_target_ladder


assert _valid_target_ladder("LONG", 100.0, 101.0, 102.0, 103.0)
assert not _valid_target_ladder("LONG", 100.0, 101.0, 101.0, 103.0)
assert not _valid_target_ladder("LONG", 100.0, 99.0, 102.0, 103.0)
assert not _valid_target_ladder("LONG", 100.0, 101.0, 103.0, 102.0)

assert _valid_target_ladder("SHORT", 100.0, 99.0, 98.0, 97.0)
assert not _valid_target_ladder("SHORT", 100.0, 99.0, 99.0, 97.0)
assert not _valid_target_ladder("SHORT", 100.0, 101.0, 98.0, 97.0)
assert not _valid_target_ladder("SHORT", 100.0, 99.0, 97.0, 98.0)

assert not _valid_target_ladder("WAIT", 100.0, 101.0, 102.0, 103.0)

strategy = (Path(__file__).resolve().parent / "strategy.py").read_text(encoding="utf-8")
assert "target_ladder_ok=_valid_target_ladder(side,price,tp1,tp2,tp3)" in strategy
assert "and fresh and target_ladder_ok and" in strategy
assert 'blocks.append("invalid TP ladder ordering")' in strategy

print("OK: malformed V2.5 TP ladders cannot pass the EXECUTE hard gate")
