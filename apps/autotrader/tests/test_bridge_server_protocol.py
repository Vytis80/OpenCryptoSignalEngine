from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bridge_server import BridgeServer
from open_crypto_signal_engine.protocol import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    VERSION_HEADER,
    sign_bridge_body,
)


class RequestStub:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    async def read(self) -> bytes:
        return self._body


def signed_request(
    body: bytes,
    *,
    secret: str = "bridge-test-secret",
    version: str | None = None,
) -> RequestStub:
    ts = str(int(time.time()))
    headers = {
        TIMESTAMP_HEADER: ts,
        SIGNATURE_HEADER: sign_bridge_body(secret, ts, body),
    }
    if version is not None:
        headers[VERSION_HEADER] = version
    return RequestStub(body, headers)


def server(executor=None) -> BridgeServer:
    cfg = SimpleNamespace(
        bridge_secret="bridge-test-secret",
        smart_position_shadow_enabled=True,
        tp2_lock_sl_to_tp1_enabled=True,
        leverage=10,
    )
    return BridgeServer(cfg, executor)


def test_verify_accepts_existing_unsorted_v1_body() -> None:
    body = b'{"signal_id":"legacy","event":"EXECUTE"}'
    request = signed_request(body)

    assert server()._verify(body, request)


@pytest.mark.asyncio
async def test_signal_normalizes_management_alias_before_executor() -> None:
    executor = SimpleNamespace(
        execute=AsyncMock(return_value={"ok": True}),
        management=AsyncMock(return_value={"ok": True}),
    )
    body = json.dumps(
        {
            "event": "PROTECT",
            "event_id": "event-1",
            "signal_id": "sig-1",
            "symbol": "btc-usdt",
            "new_sl": 101,
            "source_ts": time.time(),
        },
        separators=(",", ":"),
    ).encode()

    response = await server(executor).signal(signed_request(body, version="1"))

    assert response.status == 200
    executor.execute.assert_not_awaited()
    executor.management.assert_awaited_once()
    payload = executor.management.await_args.args[0]
    assert payload["event"] == "MANAGEMENT"
    assert payload["action"] == "PROTECT"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["new_sl"] == 101.0


@pytest.mark.asyncio
async def test_signal_rejects_unknown_protocol_version() -> None:
    executor = SimpleNamespace(
        execute=AsyncMock(return_value={"ok": True}),
        management=AsyncMock(return_value={"ok": True}),
    )
    body = b'{}'

    response = await server(executor).signal(signed_request(body, version="999"))

    assert response.status == 400
    executor.execute.assert_not_awaited()
    executor.management.assert_not_awaited()
