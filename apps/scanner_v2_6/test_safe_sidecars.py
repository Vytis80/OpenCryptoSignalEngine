
from pathlib import Path
root=Path(__file__).resolve().parent
scanner=(root/'scanner.py').read_text()
assert 'hot_monitor_loop' in scanner and 'analyze_early' in scanner
assert 'active_ws_loop' in scanner and 'ACTIVE WS connected' in scanner
assert 'active_context_loop' in scanner
assert 'dynamic_validity' in scanner
assert 'shadow_assess' in scanner
assert 'apply_entry_guard' not in scanner, 'legacy SHADOW must not become a second hidden gate'
assert 'RE-ENTRY BLOCKED' not in scanner, 'SHADOW must not suppress V2.6 hard-gate EXECUTEs'
assert '_close_active(s,"EXPIRED"' not in scanner
assert '_close_active(s,"TIMEOUT"' not in scanner
print('OK: EARLY/dynamic/ACTIVE/SHADOW remain sidecars; V2.6 hard gates stay in strategy core')
