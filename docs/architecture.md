# Architecture

OpenCryptoSignalEngine is intended to keep market data, analysis, strategy, risk, execution and monitoring responsibilities separate.

## Target modules

```text
src/open_crypto_signal_engine/
├── market_data/      # Bybit REST/WebSocket adapters and normalized market data
├── analysis/         # Multi-timeframe structure and trend analysis
├── signals/          # Setup state and signal generation
├── risk/             # Position sizing, SL/TP and trade-management rules
├── execution/        # Paper and Bybit demo execution
├── backtesting/      # Historical replay and performance evaluation
└── notifications/    # Discord and operational status reporting
```

These directories will be introduced as real code is imported and reviewed. Empty placeholder modules are intentionally avoided so the repository does not imply functionality that has not yet been published.

## Design principles

1. **Exchange isolation** — Bybit-specific API details should not leak into core signal or risk logic.
2. **Deterministic strategy logic** — the same inputs should produce reproducible analysis and risk decisions where practical.
3. **Safety before execution** — paper/demo execution should be the default path for development and validation.
4. **Explicit state transitions** — setup, entry, management and invalidation states should be observable and testable.
5. **Data freshness** — stale or inconsistent market data should prevent execution rather than silently degrade decisions.
6. **Secrets stay external** — credentials and account-specific values belong in environment configuration, never source control.
7. **Observability** — meaningful signals, state changes, execution outcomes and failures should be reportable through logs and Discord.

## Risk-management lifecycle

A representative management progression is:

```text
ENTRY
  ↓
Initial SL + targets defined
  ↓
TP1 reached → protect remaining position / SL eligible for breakeven
  ↓
TP2 reached → SL eligible to advance to TP1
  ↓
Further management / final target / invalidation
```

The exact behavior remains strategy-configurable and should be covered by tests before release.
