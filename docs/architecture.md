# Architecture

OpenCryptoSignalEngine contains three related Bybit components plus shared exchange-independent libraries.

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
                              │           │ optional research only
                              │           ▼
                              │   ┌────────────────────────┐
                              │   │ AI Judge V2 Blind     │
                              │   │ SHADOW telemetry      │
                              │   └────────────────────────┘
                              │
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
        │ Scanner V2.5.1 reference family                    │
        │ + TP-ladder safety hotfix + SHADOW AI research     │
        └────────────────────────────────────────────────────┘
```

## Deployment boundary

Current LIVE development/research workloads run on **Google Cloud Compute Engine virtual machines** as long-running Linux/Python services. Cloud hosting is an operational concern rather than part of the trading logic.

The public repository intentionally excludes Google Cloud project identifiers, VM names, IP addresses, service-account credentials, SSH material, private network details and deployment-specific runtime state. Application code and safe templates should remain portable to another Linux host without depending on private Google Cloud metadata.

A planned Jarvis integration will sit above this deployment/application boundary as an optional monitoring, diagnostics and research-orchestration layer. It must not bypass deterministic scanner validation, risk controls or the signed AutoTrader execution boundary.

## Scanner boundary

The scanner owns public market-data ingestion, multi-timeframe context, signal generation, entry validity and signal lifecycle. Public scanning does not require exchange-account credentials.

The scanner must finish deterministic signal validation before any optional AI research call. A confirmed `EXECUTE` is persisted first; if the Demo AutoTrader bridge is enabled, the bridge path is queued before waiting for AI.

## V2.5 target-ladder safety boundary

V2.5 is retained as a historical comparison family, but safety defects are not preserved for the sake of immutability.

A 2026-09-11 audit found that obstacle-aware TP capping could compress TP1/TP2/TP3 independently and produce a non-monotonic target ladder. The final ladder safety invariant is therefore:

```text
LONG : entry < TP1 < TP2 < TP3
SHORT: entry > TP1 > TP2 > TP3
```

A malformed ladder must not become `EXECUTE`. This guard is part of deterministic signal safety and is independent of AI research.

## AI Judge boundary

LIVE research moved from the original V1 sidecar to versioned V2 Blind contracts:

- V2.5: `ai-judge-v2-blind-v25`
- V2.6: `ai-judge-v2-blind-v26`

V2 Blind records `edge_score`, `risk_score`, confidence and structured reason codes for later calibration. V1 history remains retained. V2.5 and V2.6 samples remain separate.

The AI layer is not an execution gate. It has no authority to:

- create or veto an `EXECUTE`;
- change Entry, SL, TP levels, leverage or size;
- change management actions;
- control bridge delivery or AutoTrader execution.

The 2026-09-14 audit did not show enough predictive separation to justify promotion, so AI remains SHADOW-only. See `research-status-2026-09-14.md`.

The exact latest V2 Blind LIVE source still requires a fresh sanitized deployment import. Repository documentation may record validated research conclusions, but must not claim exact source parity before that import is complete.

## Bridge boundary

The scanner-to-AutoTrader bridge is optional and uses protocol v1 from `src/open_crypto_signal_engine/protocol/`.

The protocol provides deterministic JSON, HMAC-SHA256 authentication over the raw body, timestamp freshness checks, protocol-version handling and common event validation. The HMAC secret belongs only in local ignored configuration.

The downstream executor rejects malformed, stale, duplicated or unauthenticated events. Invalid target ladders must be rejected upstream before an `EXECUTE` is emitted.

## Risk lifecycle boundary

`src/open_crypto_signal_engine/risk/lifecycle.py` defines deterministic protection intent without importing Bybit, Discord, storage, AI-provider or network code.

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

The evaluator is monotonic: a stricter existing stop is never loosened. Exchange adapters remain responsible for price quantization, order submission, fill verification, retries and persistence.

## Execution boundary

The AutoTrader is intended for Bybit Demo Trading. It owns order placement, position reconciliation, TP fill tracking, stop protection, margin-safety checks and durable execution state.

The scanner owns signal intent; the executor owns safe interaction with the demo exchange. AI research remains outside both authority boundaries.

## Research boundary

Failed experiments remain documented instead of being silently reintroduced. The Historical Pattern V1 raw candle-shape walk-forward was not promoted because its edge/expectancy signals had near-zero rank correlation with realized R and its would-block cohort was profitable in the observed sample.

Any future historical-context model must begin as a new versioned SHADOW experiment. V2.6 remains the unchanged benchmark for that research line.

## Data and secret boundary

Runtime databases, AI responses, provider token-usage state, logs, `.env` files, secret backups, account/order history and cloud/server configuration are not source artifacts. See `credential-safety.md`.
