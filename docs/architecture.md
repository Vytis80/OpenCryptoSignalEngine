# Architecture

OpenCryptoSignalEngine currently contains three related Bybit components with explicit lifecycle boundaries.

## Component view

```text
                       ┌──────────────────────────┐
                       │    Bybit public market   │
                       │ REST + WebSocket streams │
                       └─────────────┬────────────┘
                                     │
                                     ▼
                       ┌──────────────────────────┐
                       │   Scanner V2.6 (active)  │
                       │ MTF analysis + signals   │
                       └─────────────┬────────────┘
                                     │ signed EXECUTE / management events
                                     ▼
                       ┌──────────────────────────┐
                       │ Demo AutoTrader (active) │
                       │ Bybit Demo execution     │
                       └─────────────┬────────────┘
                                     │
                                     ▼
                       ┌──────────────────────────┐
                       │ SQLite state / Discord   │
                       │ monitoring & statistics  │
                       └──────────────────────────┘

        ┌────────────────────────────────────────────────────┐
        │ Scanner V2.5.1 (frozen reference / replay baseline)│
        └────────────────────────────────────────────────────┘
```

## Scanner boundary

The scanner owns market-data ingestion, multi-timeframe context, signal generation, entry validity and signal lifecycle. It does not need exchange-account credentials for public market scanning.

The public V2.6 tree keeps Discord and bridge configuration in environment variables. Account-specific IDs and credentials are intentionally absent from committed defaults.

## Bridge boundary

The scanner-to-AutoTrader bridge is optional and uses a shared HMAC secret. The secret belongs only in local `.env` files on the participating hosts. It is not a repository constant.

The downstream executor should reject malformed, stale, duplicated, or unauthenticated events.

## Execution boundary

The AutoTrader is intended for Bybit Demo Trading. It owns order placement, position reconciliation, TP fill tracking, stop protection, margin-safety checks, and durable execution state.

The scanner owns signal intent; the executor owns safe interaction with the demo exchange.

## Versioning boundary

V2.5.1 is frozen under `legacy/scanner_v2_5`. V2.6 evolves independently under `apps/scanner_v2_6`. Keeping both trees allows deterministic replay/regression comparisons without rewriting historical behavior.

## Data and secret boundary

Runtime databases, logs, `.env` files, secret backups, account history and cloud/server configuration are not source artifacts. See `credential-safety.md`.
