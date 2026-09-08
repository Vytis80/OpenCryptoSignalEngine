"""Copy this file into the EXISTING Bybit signal scanner VM/project.

It does not change strategy. It only relays already-confirmed events to the Demo Auto-Trader VM.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import aiohttp


class DemoBridgeClient:
    def __init__(self, url: str, secret: str, timeout_sec: float = 60.0):
        self.url = url.rstrip("/") + "/signal"
        self.secret = secret
        self.timeout_sec = timeout_sec

    async def send(self, payload: dict):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        ts = str(int(time.time()))
        sig = hmac.new(self.secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                self.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bridge-Timestamp": ts,
                    "X-Bridge-Signature": sig,
                },
            ) as r:
                text = await r.text()
                if r.status >= 300:
                    raise RuntimeError(f"Demo bridge HTTP {r.status}: {text}")
                return json.loads(text)

    async def execute(
        self, *, signal_id, symbol, side, entry, entry_low, entry_high, sl,
        tp1, tp2, tp3, quality="", score=0, setup_type="",
        source_ts=None, expires_at=0, shadow_status="", shadow_note="",
    ):
        payload = {
            "event": "EXECUTE",
            "signal_id": str(signal_id),
            "symbol": symbol,
            "side": side,
            "entry": float(entry),
            "entry_low": float(entry_low),
            "entry_high": float(entry_high),
            "sl": float(sl),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "tp3": float(tp3),
            "quality": quality,
            "score": float(score),
            "setup_type": setup_type,
            "source_ts": float(source_ts if source_ts is not None else time.time()),
            "expires_at": float(expires_at or 0),
            "shadow_status": shadow_status,
            "shadow_note": shadow_note,
        }
        return await self.send(payload)

    async def management(
        self,
        *,
        event_id,
        signal_id,
        symbol,
        action,
        reason="",
        price=None,
        new_sl=None,
    ):
        p = {
            "event": "MANAGEMENT",
            "event_id": str(event_id),
            "signal_id": str(signal_id),
            "symbol": symbol,
            "action": action,
            "reason": reason,
            "source_ts": time.time(),
        }
        if price is not None: p["price"] = float(price)
        if new_sl is not None: p["new_sl"] = float(new_sl)
        return await self.send(p)
