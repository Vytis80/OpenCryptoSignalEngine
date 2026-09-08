from __future__ import annotations

import json
import time

import aiohttp

from open_crypto_signal_engine.protocol import (
    bridge_headers,
    build_execute_payload,
    build_management_payload,
    canonical_json_bytes,
)


class DemoBridgeClient:
    def __init__(self, url: str, secret: str, timeout_sec: float = 3.0):
        self.url = url.rstrip("/") + "/signal"
        self.secret = secret
        self.timeout_sec = timeout_sec

    @staticmethod
    def _v26_signal_id(signal_id) -> str:
        text = str(signal_id).strip()
        if text.startswith("V26S"):
            return text
        return f"V26S{text}"

    async def send(self, payload: dict):
        body = canonical_json_bytes(payload)
        ts = str(int(time.time()))
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.url,
                data=body,
                headers=bridge_headers(self.secret, ts, body),
            ) as response:
                text = await response.text()

                if response.status >= 300:
                    raise RuntimeError(
                        f"Demo bridge HTTP {response.status}: {text}"
                    )

                return json.loads(text)

    async def execute(
        self,
        *,
        signal_id,
        symbol,
        side,
        entry,
        entry_low,
        entry_high,
        sl,
        tp1,
        tp2,
        tp3,
        quality="",
        score=0,
        setup_type="",
        shadow_status="",
        shadow_note="",
        expires_at=0,
    ):
        source_ts = time.time()
        payload = build_execute_payload(
            signal_id=self._v26_signal_id(signal_id),
            symbol=symbol,
            side=side,
            entry=entry,
            entry_low=entry_low,
            entry_high=entry_high,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            quality=quality,
            score=score,
            setup_type=setup_type,
            shadow_status=shadow_status,
            shadow_note=shadow_note,
            expires_at=expires_at,
            source_ts=source_ts,
            now=source_ts,
        )
        return await self.send(payload)

    async def management(
        self,
        *,
        signal_id,
        event_id,
        symbol,
        action,
        reason="",
        price=None,
        new_sl=None,
    ):
        source_ts = time.time()
        payload = build_management_payload(
            event_id=event_id,
            signal_id=self._v26_signal_id(signal_id),
            symbol=symbol,
            action=action,
            reason=reason,
            price=price,
            new_sl=new_sl,
            source_ts=source_ts,
            now=source_ts,
        )
        return await self.send(payload)
