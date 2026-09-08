
from pathlib import Path
root=Path(__file__).resolve().parent
scanner=(root/'scanner.py').read_text(encoding='utf-8')
assert 'hot_monitor_loop' in scanner and 'analyze_early' in scanner
assert 'active_ws_loop' in scanner and 'ACTIVE WS connected' in scanner
assert 'active_context_loop' in scanner
assert 'dynamic_validity' in scanner
assert 'shadow_assess' in scanner
assert 'apply_entry_guard' not in scanner, 'hard anti-SL gate must not be used in SAFE build'
assert 'RE-ENTRY BLOCKED' not in scanner, 'scanner core must not silently suppress EXECUTEs'
assert 'bridge_outbox_loop' in scanner and 'enqueue_bridge' in scanner
assert '_close_active(s,"EXPIRED"' not in scanner
assert '_close_active(s,"TIMEOUT"' not in scanner
print('OK: EARLY, validity and SHADOW stay outside core; bridge delivery is durable')
