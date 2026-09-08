"""Shared protocol primitives used by active scanner and execution components."""

from .bridge import (
    BRIDGE_PROTOCOL_VERSION,
    DEFAULT_MAX_SKEW_SEC,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    VERSION_HEADER,
    bridge_headers,
    build_execute_payload,
    build_management_payload,
    canonical_json_bytes,
    normalize_side,
    normalize_symbol,
    sign_bridge_body,
    validate_event_payload,
    verify_bridge_signature,
)

__all__ = [
    "BRIDGE_PROTOCOL_VERSION",
    "DEFAULT_MAX_SKEW_SEC",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "VERSION_HEADER",
    "bridge_headers",
    "build_execute_payload",
    "build_management_payload",
    "canonical_json_bytes",
    "normalize_side",
    "normalize_symbol",
    "sign_bridge_body",
    "validate_event_payload",
    "verify_bridge_signature",
]
