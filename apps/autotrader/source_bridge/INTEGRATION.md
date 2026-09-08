# External/older Bybit scanner → Demo AutoTrader bridge

The active repository Scanner V2.6 already uses the shared bridge protocol package and does **not** need this compatibility helper.

Use this directory only when integrating a separate/older Bybit scanner that does not install the full `OpenCryptoSignalEngine` package. The Demo AutoTrader still does **not** calculate signals; the scanner remains the source of truth.

The helper speaks bridge protocol v1 and sends `X-Bridge-Version: 1`. See `../../../docs/bridge-protocol.md` for the signed wire contract and compatibility rules.

## 1) Copy `bridge_client.py` into the external scanner directory

Set these environment values on that scanner host:

```bash
DEMO_BRIDGE_URL=http://DEMO_AUTOTRADER_HOST:8787
DEMO_BRIDGE_SECRET=the_same_long_secret_as_the_autotrader
```

## 2) Create one client at scanner startup

```python
import os
from bridge_client import DemoBridgeClient

self.demo_bridge = DemoBridgeClient(
    os.environ["DEMO_BRIDGE_URL"],
    os.environ["DEMO_BRIDGE_SECRET"],
)
```

## 3) Relay only an already-confirmed/persisted `EXECUTE`

Use the exact values already produced by the scanner. Do not recalculate entry, stop or targets in the Demo AutoTrader.

```python
await self.demo_bridge.execute(
    signal_id=s.id,
    symbol=s.inst_id,
    side=s.side,
    entry=s.entry,
    entry_low=s.entry_low,
    entry_high=s.entry_high,
    sl=s.sl,
    tp1=s.tp1,
    tp2=s.tp2,
    tp3=s.tp3,
    quality=s.quality,
    score=s.score,
    setup_type=s.setup_type,
    source_ts=s.created_at,
    expires_at=s.expires_at,
    shadow_status=s.shadow_status,
    shadow_note=s.shadow_note,
)
```

The exact variable names may differ. Patch this at the same point where the source scanner already confirms and persists its final execution signal.

## 4) Relay management changes with durable IDs

```python
await self.demo_bridge.management(
    event_id=management_event.id,
    signal_id=s.id,
    symbol=s.inst_id,
    action="PROTECT",
    reason="scanner management note",
    new_sl=new_sl,
)
```

For invalidation / forced close:

```python
await self.demo_bridge.management(
    event_id=invalidation_event.id,
    signal_id=s.id,
    symbol=s.inst_id,
    action="INVALIDATED",
    reason="scanner invalidation reason",
)
```

`event_id` must be a durable unique ID created once when the scanner persists the management event. Reuse that same ID on retries. `signal_id` must identify the exact signal/trade being managed; symbol-only management is deliberately rejected so a delayed event cannot affect a newer trade in the same symbol.

## Network safety

Allow TCP 8787 only from the scanner host/network that needs it. Timestamped HMAC signatures are required, but network-level filtering should still be used where practical.
