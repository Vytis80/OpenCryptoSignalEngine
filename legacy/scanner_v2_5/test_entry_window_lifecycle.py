from pathlib import Path

root = Path(__file__).resolve().parent
scanner = (root / "scanner.py").read_text(encoding="utf-8")
alerts = (root / "alerts.py").read_text(encoding="utf-8")
models = (root / "models.py").read_text(encoding="utf-8")

assert '_close_active(s,"EXPIRED"' not in scanner, "Legacy EXPIRED timer-close path still exists"
assert '_close_active(s,"TIMEOUT"' not in scanner, "Legacy TIMEOUT timer-close path still exists"
assert "ENTRY WINDOW CLOSED" in scanner, "Missing entry-window close handling"
assert "entry_window_notified" in scanner and "entry_window_notified" in models, "Missing one-time entry-window state"
assert "ACTIVE management continues" in scanner, "Management continuation marker missing"
assert "This is NOT an exit signal" in alerts, "Discord alert must explicitly say this is not an exit"
print("OK: entry-window lifecycle is separated from ACTIVE management")
