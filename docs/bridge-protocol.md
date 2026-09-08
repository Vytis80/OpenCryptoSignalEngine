# Scanner-to-AutoTrader bridge protocol

The active Bybit Scanner V2.6 and Bybit Demo AutoTrader communicate through a small signed HTTP protocol. The shared implementation lives in `open_crypto_signal_engine.protocol` so transport behavior is tested independently from strategy and exchange execution.

## Protocol v1

The scanner sends JSON to `POST /signal` and signs the **exact request body** with HMAC-SHA256.

Required authentication headers:

- `X-Bridge-Timestamp`: integer Unix time in seconds
- `X-Bridge-Signature`: lowercase hex HMAC-SHA256 over `timestamp + "." + raw_body`

New clients also send `X-Bridge-Version: 1`. The server intentionally accepts a missing version header so existing v1 clients remain compatible. An explicitly unsupported version is rejected before execution.

The server rejects requests whose timestamp differs from its current clock by more than 30 seconds. Authentication verifies the raw bytes received over HTTP; it never parses and reserializes a body before checking the signature.

## Deterministic JSON

New repository clients use compact UTF-8 JSON with sorted object keys and reject non-finite JSON numbers. This makes generated payload bytes and signatures reproducible.

Deterministic serialization is a **client behavior**, not a server requirement. Older v1 clients that serialize keys in insertion order remain valid because the signature authenticates whatever raw body was actually sent.

## Event envelopes

### `EXECUTE`

Common required fields are:

- `signal_id`
- `symbol`
- `side` (`LONG` or `SHORT`)
- `entry`, `entry_low`, `entry_high`
- `sl`, `tp1`, `tp2`, `tp3`

Common optional fields include quality/score/setup labels, source timestamps, expiry and shadow/research metadata. Unknown JSON fields are preserved as extensions and can be validated by the receiving component. This lets Scanner V2.6 add analysis metadata without changing the transport contract.

The shared validator checks finite positive price levels, entry-window ordering and LONG/SHORT stop/target ordering before an event reaches the executor.

### `MANAGEMENT`

Common required fields are:

- `event_id` for durable idempotency
- `signal_id` for stale-signal protection
- `symbol`
- `action`

Optional fields include `reason`, `price`, `new_sl` and source timestamp.

For v1 compatibility the bridge accepts shorthand event names such as `PROTECT`, `MOVE_SL`, `CLOSE`, `INVALIDATED` and `CLOSE_EARLY`. They are normalized to a `MANAGEMENT` envelope before the AutoTrader sees them.

## Responsibility boundary

The shared protocol package is deliberately unable to:

- scan markets or generate signals;
- access Bybit or Discord;
- place, amend or close orders;
- read credentials, wallet state or SQLite runtime data;
- decide strategy thresholds.

Scanner V2.6 decides which events to emit. The shared package only normalizes/signs/validates their transport. The Demo AutoTrader remains responsible for exchange quantization, idempotency, risk/execution checks, persistence and recovery.

## Compatibility rules

Protocol v1 changes should remain additive unless a security defect requires otherwise. In particular:

1. existing signed v1 bodies without `X-Bridge-Version` remain accepted;
2. unknown JSON extension fields are preserved rather than silently discarded;
3. the signature input remains the exact raw request body;
4. breaking field or authentication changes require a new explicit protocol version;
5. protocol tests are network-free and must not contain production credentials or account data.
