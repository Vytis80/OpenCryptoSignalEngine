# Bybit Scanner V2.5.1 — Frozen Reference

V2.5.1 is the frozen reference baseline kept for regression comparison and signal replay. It is not the primary development target.

## Highlights

- Bybit USDT Linear Perpetual market data
- 1H / 15M / confirmed 5M strategy baseline
- EARLY and POTENTIAL setup lifecycle
- Dynamic entry validity
- Observation-only SMART signal and management labels
- Diagnostic anti-SL shadow layer
- Durable bridge outbox for downstream demo execution
- SQLite signal and research state
- Discord alerts and command interface

The SMART and shadow layers are research metadata only: they do not modify Entry, SL, TP1, TP2, TP3, or suppress a final EXECUTE in the preserved baseline.

## Install

```bash
cp .env.example .env
# Fill only your own local Discord values in .env
./install.sh
.venv/bin/python self_test.py
```

The committed `.env.example` contains placeholders only. Never commit `.env`, tokens, webhooks, IDs, API credentials, bridge secrets, database files, or runtime logs.

## Status

**Frozen.** New development belongs in `apps/scanner_v2_6`. This directory exists so behavior can be replayed and compared against V2.6.

See `VALIDATION_SMART_SHADOW_35D.md` and `CHANGELOG_SMART_SHADOW_20260903.md` for the preserved research notes.
