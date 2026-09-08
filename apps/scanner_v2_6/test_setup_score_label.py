from pathlib import Path

alerts=Path(__file__).with_name("alerts.py").read_text(encoding="utf-8")
assert "Setup Score" in alerts
assert "Setup Quality" in alerts
assert "Confidence" not in alerts
assert "Probability" not in alerts
print("OK: Discord labels composite rule score as Setup Score, never probability/confidence")
