# Existing Bybit scanner → Demo Auto-Trader bridge

The new VM deliberately does **not** calculate signals. Your existing Bybit scanner remains the only source of truth.

## 1) Copy `bridge_client.py` into the existing Bybit scanner directory

Set these environment values on the existing scanner VM:

```bash
DEMO_BRIDGE_URL=http://NEW_DEMO_VM_IP:8787
DEMO_BRIDGE_SECRET=the_same_long_secret_as_new_vm
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

## 3) After the scanner has **actually confirmed and persisted** a new EXECUTE signal, relay it

Use the exact values already produced by the scanner. Do not recalculate anything in the demo bot.

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

The exact variable names in your current scanner may differ. Patch this at the same point where the current Bybit bot sends its `EXECUTE` Discord alert.

## 4) Relay management changes when the signal bot makes them

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

`event_id` must be a durable unique ID created once when the scanner persists the
management event. Reuse that same ID on retries. `signal_id` must identify the
exact signal/trade being managed; symbol-only management is deliberately rejected
so a delayed event cannot affect a newer trade in the same symbol.

## Network safety

On the NEW demo VM, allow TCP 8787 **only from the existing Bybit scanner VM public IP**. The bridge also uses timestamped HMAC signatures, but IP firewalling should still be enabled.
