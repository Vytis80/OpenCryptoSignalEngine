# Bybit Scanner V2.6 — Signal Core

Current active scanner and signal engine for Bybit USDT Linear Perpetuals.

## Core pipeline

```text
Bybit market data
  -> fair whole-market rotation
  -> multi-timeframe structure
  -> setup scoring
  -> execution gates
  -> Entry / SL / TP1 / TP2 / TP3
  -> active signal management
  -> Discord + optional Demo AutoTrader bridge
```

## Main capabilities

- Bybit V5 REST and public WebSocket market data
- 4H / 1H / 15M / 5M / 1M context
- Fair rotation across liquid USDT perpetuals
- Confirmed-candle strategy core with micro-confirmation gates
- Dynamic entry-window validity
- Stop-distance and obstacle-aware execution checks
- Market-data freshness watchdog and REST fallback
- Signal lifecycle tracking and cost-adjusted research statistics
- Diagnostic shadow analysis
- Discord monitoring and command interface
- Optional signed bridge to `apps/autotrader`
- Replay comparison against the frozen V2.5 baseline

## Install

```bash
cp .env.example .env
# Fill only your own local Discord/bridge values in .env
./install.sh
.venv/bin/python self_test.py
```

For a service installation, review `systemd_service.txt` and then run `./setup_service.sh`.

## Security

The repository contains no operational credentials. Keep real Discord tokens/webhooks, account IDs and bridge secrets only in the local `.env`. The root CI also runs a secret scan.

## Version

See `VERSION` and `RELEASE_NOTES.md`.
