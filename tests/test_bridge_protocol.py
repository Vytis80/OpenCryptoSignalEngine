import json

import pytest

from open_crypto_signal_engine.protocol import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    VERSION_HEADER,
    bridge_headers,
    build_execute_payload,
    build_management_payload,
    canonical_json_bytes,
    sign_bridge_body,
    validate_event_payload,
    verify_bridge_signature,
)


def test_canonical_json_is_stable_across_mapping_order() -> None:
    first = {"signal_id": "abc", "event": "EXECUTE"}
    second = {"event": "EXECUTE", "signal_id": "abc"}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first) == b'{"event":"EXECUTE","signal_id":"abc"}'


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})


def test_signature_matches_known_v1_vector() -> None:
    body = b'{"event":"EXECUTE","signal_id":"abc"}'

    assert sign_bridge_body("test-secret", 1_700_000_000, body) == (
        "ada3a9ed68198f01a5a88e0687b613d69c49e68ee7006d6b09354e39d631e89e"
    )


def test_headers_and_verifier_round_trip() -> None:
    body = canonical_json_bytes({"event": "EXECUTE", "signal_id": "abc"})
    headers = bridge_headers("secret", 1_700_000_000, body)

    assert headers[TIMESTAMP_HEADER] == "1700000000"
    assert headers[VERSION_HEADER] == "1"
    assert verify_bridge_signature(
        "secret",
        headers[TIMESTAMP_HEADER],
        headers[SIGNATURE_HEADER],
        body,
        now=1_700_000_030,
    )


def test_verifier_rejects_stale_malformed_and_tampered_requests() -> None:
    body = canonical_json_bytes({"event": "EXECUTE", "signal_id": "abc"})
    signature = sign_bridge_body("secret", 1_700_000_000, body)

    assert not verify_bridge_signature(
        "secret", "1700000000", signature, body, now=1_700_000_031
    )
    assert not verify_bridge_signature(
        "secret", "not-a-time", signature, body, now=1_700_000_000
    )
    assert not verify_bridge_signature(
        "secret", "1700000000", "0" * 64, body, now=1_700_000_000
    )
    assert not verify_bridge_signature(
        "secret", "1700000000", signature, body + b" ", now=1_700_000_000
    )


def test_execute_builder_normalizes_and_preserves_extensions() -> None:
    payload = build_execute_payload(
        signal_id="sig-1",
        symbol="btc-usdt",
        side="long",
        entry=100,
        entry_low=99,
        entry_high=101,
        sl=95,
        tp1=105,
        tp2=110,
        tp3=115,
        score=82,
        source_ts=1_700_000_000,
        expires_at=1_700_000_600,
        extra={"smart_status": "PASS", "smart_score": 77.0},
        now=1_700_000_000,
    )

    assert payload["event"] == "EXECUTE"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["side"] == "LONG"
    assert payload["smart_status"] == "PASS"
    assert payload["smart_score"] == 77.0


def test_execute_builder_fails_closed_on_invalid_levels() -> None:
    with pytest.raises(ValueError, match="invalid LONG"):
        build_execute_payload(
            signal_id="sig-1",
            symbol="BTCUSDT",
            side="LONG",
            entry=100,
            entry_low=99,
            entry_high=101,
            sl=101,
            tp1=105,
            tp2=110,
            tp3=115,
        )


def test_management_builder_is_idempotency_aware() -> None:
    payload = build_management_payload(
        event_id="event-1",
        signal_id="sig-1",
        symbol="btc/usdt",
        action="move_sl",
        new_sl=101,
        source_ts=1_700_000_000,
        now=1_700_000_000,
    )

    assert payload == {
        "event": "MANAGEMENT",
        "event_id": "event-1",
        "signal_id": "sig-1",
        "symbol": "BTCUSDT",
        "action": "MOVE_SL",
        "reason": "",
        "source_ts": 1_700_000_000.0,
        "new_sl": 101.0,
    }


def test_incoming_shorthand_management_event_is_normalized() -> None:
    payload = validate_event_payload(
        {
            "event": "PROTECT",
            "event_id": "event-2",
            "signal_id": "sig-2",
            "symbol": "ETHUSDT",
            "new_sl": 2000,
            "source_ts": 1_700_000_000,
            "extension": {"source": "scanner"},
        },
        now=1_700_000_000,
    )

    assert payload["event"] == "MANAGEMENT"
    assert payload["action"] == "PROTECT"
    assert payload["extension"] == {"source": "scanner"}


def test_incoming_execute_alias_and_json_round_trip() -> None:
    normalized = validate_event_payload(
        {
            "id": "legacy-id",
            "symbol": "BTC_USDT",
            "side": "SHORT",
            "entry": 100,
            "sl": 105,
            "tp1": 95,
            "tp2": 90,
            "tp3": 85,
            "source_ts": 1_700_000_000,
        },
        now=1_700_000_000,
    )
    decoded = json.loads(canonical_json_bytes(normalized))

    assert decoded["signal_id"] == "legacy-id"
    assert decoded["symbol"] == "BTCUSDT"
    assert decoded["entry_low"] == 100.0
    assert decoded["entry_high"] == 100.0
