from __future__ import annotations

import json
import logging

from aiohttp import web
from open_crypto_signal_engine.protocol import (
    BRIDGE_PROTOCOL_VERSION,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    VERSION_HEADER,
    validate_event_payload,
    verify_bridge_signature,
)

log = logging.getLogger(__name__)


class BridgeServer:
    def __init__(self, cfg, executor):
        self.cfg = cfg
        self.executor = executor
        self.runner = None

    def _verify(self, body: bytes, request: web.Request) -> bool:
        return verify_bridge_signature(
            self.cfg.bridge_secret,
            request.headers.get(TIMESTAMP_HEADER, ""),
            request.headers.get(SIGNATURE_HEADER, ""),
            body,
        )

    async def health(self, request):
        return web.json_response({
            "ok": True,
            "service": "BYBIT_Demo_AutoTrader_V1.5.4",
            "demo": True,
            "bridge_protocol": BRIDGE_PROTOCOL_VERSION,
            "smart_position_shadow": bool(self.cfg.smart_position_shadow_enabled),
            "tp2_lock_sl_to_tp1": bool(self.cfg.tp2_lock_sl_to_tp1_enabled),
            "leverage_target": self.cfg.leverage,
            "leverage_fallback": "instrument_max",
        })

    async def signal(self, request):
        body = await request.read()
        if not self._verify(body, request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        requested_version = request.headers.get(VERSION_HEADER, "")
        if requested_version and requested_version != BRIDGE_PROTOCOL_VERSION:
            return web.json_response(
                {"ok": False, "error": "unsupported bridge protocol"},
                status=400,
            )

        try:
            payload = validate_event_payload(json.loads(body.decode("utf-8")))
            if payload["event"] == "EXECUTE":
                result = await self.executor.execute(payload)
            else:
                result = await self.executor.management(payload)
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
