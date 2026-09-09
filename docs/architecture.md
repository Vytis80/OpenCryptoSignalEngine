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
                       └──────┬───────────┬───────┘
                              │           │ optional, EXECUTE-only
                              │           ▼
                              │   ┌────────────────────────┐
                              │   │ GPT-OSS AI Judge       │
                              │   │ observation / research │
                              │   └────────────────────────┘
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
        │ Scanner V2.5.1 (frozen strategy / replay baseline) │
        │ + optional observation-only AI research sidecar    │
        └────────────────────────────────────────────────────┘
```

## Scanner boundary

The scanner owns market-data ingestion, multi-timeframe context, signal generation, entry validity and signal lifecycle. It does not need exchange-account credentials for public market scanning.

The public V2.6 tree keeps Discord, bridge and optional AI-provider configuration in environment variables. Account-specific IDs and credentials are intentionally absent from committed defaults.

## AI Judge boundary

The GPT-OSS AI Judge is an optional outbound research sidecar, not part of the deterministic execution gate. Public examples keep it disabled until the operator explicitly enables it and supplies a local provider credential.

For V2.6, a confirmed EXECUTE is persisted and the optional Demo AutoTrader bridge task is queued **before** awaiting the AI provider. AI timeout, network failure, APPROVE/REJECT/CAUTION verdicts or model availability therefore cannot veto the already-confirmed signal, change Entry/SL/TP/size/management, or become a prerequisite for bridge delivery.

V2.5 keeps the same observation-only contract. Its strategy remains frozen while its AI research data is stored separately from V2.6. V2.5 additionally tracks provider token usage for cost/usage analysis.

Enabling the sidecar sends structured setup/signal evidence to the configured external AI endpoint. Provider keys and returned runtime research data belong in local configuration/databases, not Git history. Live provider probes are intentionally outside public CI.

## Bridge boundary

The scanner-to-AutoTrader bridge is optional and uses a shared HMAC secret. The secret belongs only in local `.env` files on the participating hosts. It is not a repository constant.

The downstream executor should reject malformed, stale, duplicated, or unauthenticated events.

## Risk lifecycle boundary

`src/open_crypto_signal_engine/risk/lifecycle.py` defines the deterministic protection state machine without importing Bybit, Discord, storage, AI-provider or network code. A validated risk plan must contain the entry, initial stop and ordered TP1/TP2/TP3 levels before execution begins.

The shared lifecycle has four explicit states:

```text
INITIAL
  │ TP1 confirmed
  ▼
BREAKEVEN          desired SL = actual entry
  │ TP2 confirmed
  ▼
TP1_LOCKED         desired SL = TP1

Any state ── explicit invalidation ──▶ INVALIDATED / close required
```

The evaluator is monotonic: if a caller already has a stricter stop than the milestone target, that stop is preserved rather than loosened. LONG and SHORT behavior is symmetric and covered by deterministic unit tests.

This module describes **what protection is required**. Exchange adapters and executors remain responsible for price quantization, order submission, fill verification, retries, persistence, and proving that the requested stop actually exists on the exchange.

## Execution boundary

The AutoTrader is intended for Bybit Demo Trading. It owns order placement, position reconciliation, TP fill tracking, stop protection, margin-safety checks, and durable execution state.

The scanner owns signal intent; the executor owns safe interaction with the demo exchange. The shared risk lifecycle is deliberately exchange-independent so its state transitions can be tested without credentials or network access.

## Versioning boundary

V2.5.1 is frozen under `legacy/scanner_v2_5`. V2.6 evolves independently under `apps/scanner_v2_6`. Keeping both trees allows deterministic replay/regression comparisons without rewriting historical strategy behavior. Observation-only research sidecars must remain separately measurable and must not silently change the frozen signal core.

## Data and secret boundary

Runtime databases, AI responses, provider token-usage state, logs, `.env` files, secret backups, account history and cloud/server configuration are not source artifacts. See `credential-safety.md`.
