from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from aiohttp import web

log = logging.getLogger(__name__)


class BridgeServer:
    def __init__(self, cfg, executor):
        self.cfg = cfg
        self.executor = executor
        self.runner = None

    def _verify(self, body: bytes, request: web.Request) -> bool:
        ts = request.headers.get("X-Bridge-Timestamp", "")
        sig = request.headers.get("X-Bridge-Signature", "")
        try:
            t = int(ts)
        except ValueError:
            return False
        if abs(int(time.time()) - t) > 30:
            return False
        expected = hmac.new(
            self.cfg.bridge_secret.encode(),
            ts.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    async def health(self, request):
        return web.json_response({
            "ok": True,
            "service": "BYBIT_Demo_AutoTrader_V1.5.3",
            "demo": True,
            "smart_position_shadow": bool(self.cfg.smart_position_shadow_enabled),
            "tp2_lock_sl_to_tp1": bool(self.cfg.tp2_lock_sl_to_tp1_enabled),
            "leverage_target": self.cfg.leverage,
            "leverage_fallback": "instrument_max",
        })

    async def signal(self, request):
        body = await request.read()
        if not self._verify(body, request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            payload = json.loads(body.decode())
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            event = str(payload.get("event", "EXECUTE")).upper()
            if event == "EXECUTE":
                result = await self.executor.execute(payload)
            elif event in {"MANAGEMENT", "PROTECT", "MOVE_SL", "CLOSE", "INVALIDATED", "CLOSE_EARLY"}:
                if event != "MANAGEMENT" and "action" not in payload:
                    payload["action"] = event
                result = await self.executor.management(payload)
            else:
                return web.json_response({"ok": False, "error": f"unknown event {event}"}, status=400)
            return web.json_response(result)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        except (KeyError, TypeError, ValueError) as e:
            log.info("Bridge payload rejected: %s", e)
            return web.json_response({"ok": False, "error": "invalid payload"}, status=422)
        except Exception:
            log.exception("Bridge event failed")
            return web.json_response(
                {"ok": False, "error": "internal execution failure"}, status=500
            )

    async def start(self):
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_get("/health", self.health)
        app.router.add_post("/signal", self.signal)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.cfg.bridge_host, self.cfg.bridge_port)
        await site.start()
        log.info("Signal bridge listening on %s:%s", self.cfg.bridge_host, self.cfg.bridge_port)

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
