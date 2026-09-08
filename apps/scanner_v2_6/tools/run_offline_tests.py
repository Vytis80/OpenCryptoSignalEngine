#!/usr/bin/env python3
"""Run the network-free V2.6 release gate. Live Bybit/Discord probes are excluded."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "self_test.py",
    "test_bybit_adapter_unit.py",
    "test_bybit_rate_limit_safety.py",
    "test_bridge_protocol_contract.py",
    "test_dynamic_validity.py",
    "test_entry_window_lifecycle.py",
    "test_safe_core_parity.py",
    "test_safe_sidecars.py",
    "test_shadow_in_execute_alert.py",
    "test_shadow_nonblocking.py",
    "test_setup_score_label.py",
    "test_storage_safe_schema.py",
    "test_edge_stats.py",
    "test_discord_reconnect_cap.py",
    "test_discord_shared_merge.py",
    "test_discord_webhook_retry.py",
    "test_v26_reliability.py",
    "test_v26_signal_core.py",
    "test_v26_historical_edge.py",
    "test_replay_compare.py",
    "test_replay_gate.py",
)


def main() -> int:
    missing = [test for test in TESTS if not (ROOT / test).is_file()]
    if missing:
        print("FAIL: offline release gate references missing tests:")
        for test in missing:
            print(f"  - {test}")
        return 2

    for test in TESTS:
        print(f"\n=== {test} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / test)], cwd=ROOT)
        if result.returncode:
            print(f"FAIL: {test}")
            return result.returncode

    print(f"\nRELEASE GATE PASSED: {len(TESTS)} offline tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
