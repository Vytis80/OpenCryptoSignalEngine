#!/usr/bin/env python3
"""Network-free contract check for Scanner V2.6 bridge payloads."""

from __future__ import annotations

import asyncio

from bridge_client import DemoBridgeClient
from open_crypto_signal_engine.protocol import canonical_json_bytes


async def main() -> int:
    client = DemoBridgeClient("http://127.0.0.1:8787", "placeholder-secret")
    captured: list[dict] = []

    async def capture(payload: dict):
        captured.append(payload)
        return {"ok": True}

    client.send = capture  # type: ignore[method-assign]

    result = await client.execute(
        signal_id="123",
        symbol="btc-usdt",
        side="long",
        entry=100,
        entry_low=99,
        entry_high=101,
        sl=95,
        tp1=105,
        tp2=110,
        tp3=115,
        quality="A",
        score=88,
        setup_type="BREAKOUT",
    )
    assert result == {"ok": True}
    execute = captured[-1]
    assert execute["event"] == "EXECUTE"
    assert execute["signal_id"] == "V26S123"
    assert execute["symbol"] == "BTCUSDT"
    assert execute["side"] == "LONG"
    assert canonical_json_bytes(execute).startswith(b'{"entry":')

    await client.management(
        signal_id="123",
        event_id="event-1",
        symbol="btc/usdt",
        action="move_sl",
        new_sl=101,
    )
    management = captured[-1]
    assert management["event"] == "MANAGEMENT"
    assert management["event_id"] == "event-1"
    assert management["signal_id"] == "V26S123"
    assert management["symbol"] == "BTCUSDT"
    assert management["action"] == "MOVE_SL"
    assert management["new_sl"] == 101.0

    print("PASS: Scanner V2.6 bridge uses shared protocol payload contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
