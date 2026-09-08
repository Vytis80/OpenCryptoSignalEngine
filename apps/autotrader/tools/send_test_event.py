from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_bridge"))
from bridge_client import DemoBridgeClient


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("DEMO_BRIDGE_URL", "http://127.0.0.1:8787"))
    p.add_argument("--secret", default=os.getenv("BRIDGE_SECRET", ""))
    p.add_argument("--symbol", default="BTCUSDT")
    args = p.parse_args()
    if not args.secret:
        raise SystemExit("Set --secret or BRIDGE_SECRET")
    c = DemoBridgeClient(args.url, args.secret)
    # Deliberately impossible prices by default so this should be rejected by level/entry validation rather than traded.
    smoke_id = f"SMOKE-{uuid.uuid4()}"
    print(await c.send({
        "event": "MANAGEMENT",
        "event_id": smoke_id,
        "signal_id": smoke_id,
        "symbol": args.symbol,
        "action": "PROTECT",
        "reason": "bridge smoke test - no active position",
        "source_ts": time.time(),
    }))


if __name__ == "__main__":
    asyncio.run(main())
