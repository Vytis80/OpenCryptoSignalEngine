# Bybit Scanner V2.6 — Signal Core

Current active scanner and signal engine for Bybit USDT Linear Perpetuals. Current release candidate: `2.6.0-rc2`.

## Core pipeline

```text
Bybit market data
  -> fair whole-market rotation
  -> multi-timeframe structure
  -> setup scoring
  -> execution gates
  -> Entry / SL / TP1 / TP2 / TP3
  -> persist confirmed EXECUTE
  -> queue optional Demo AutoTrader bridge
  -> optional AI Judge research (SHADOW only)
  -> Discord + research statistics
  -> active signal management
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
- Diagnostic shadow analysis that does not mutate core decisions
- Optional signed protocol-v1 bridge to `apps/autotrader`
- Shared deterministic bridge payload/signature contract from `open_crypto_signal_engine.protocol`
- Replay comparison against the V2.5 comparison baseline
- Replay handling for currently unavailable/unsupported Bybit symbols

## AI Judge research status

The first public AI sidecar snapshot used the V1 contract. LIVE research later moved to **AI Judge V2 Blind SHADOW** under prompt contract `ai-judge-v2-blind-v26`.

V2 Blind records separate `edge_score`, `risk_score`, confidence and structured reason codes for later calibration. It remains observation-only: it cannot veto, delay, resize or modify an `EXECUTE`, Entry, SL, TP, management action or AutoTrader order.

The bridge/execution path remains ahead of the AI wait, so provider latency/failure does not gate confirmed execution delivery.

The 2026-09-14 audit did not justify a hard AI gate, so V2 Blind remains SHADOW-only. See `AI_JUDGE_V2_BLIND.md` and the repository-level `docs/research-status-2026-09-14.md`.

**Source-parity note:** the exact latest V2 Blind LIVE implementation still requires a fresh sanitized deployment source import. The repository documentation records the confirmed LIVE contract and research decision without pretending that the older public V1 source is already byte-for-byte identical to LIVE.

## Install

Run the component from a **full OpenCryptoSignalEngine repository clone** because the scanner venv installs shared repository packages.

```bash
cp .env.example .env
# Fill only your own local Discord/bridge values in .env.
# AI is disabled by default; if explicitly enabled, add your own provider key locally.
./install.sh
.venv/bin/python self_test.py
```

For a service installation, review `systemd_service.txt` and then run `./setup_service.sh`.

Public CI stays credential-free and network-free for the AI-provider path. Live provider checks belong on the deployment host with operator-owned credentials.

## Security

Keep real Discord tokens/webhooks, account IDs, bridge secrets, Groq/API-provider keys, runtime DBs and logs outside Git. The root CI runs a dedicated secret scan.

## Version and docs

See `VERSION`, `RELEASE_NOTES.md`, `RC2_UPDATE.md`, `AI_JUDGE_V1.md` (historical public V1 contract) and `AI_JUDGE_V2_BLIND.md` (current LIVE research contract).
