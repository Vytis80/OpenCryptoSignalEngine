# OpenCryptoSignalEngine

[![CI](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml/badge.svg)](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml)
[![Secret scan](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/secret-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Open-source **Bybit-focused** crypto market analysis, signal generation, risk management, deterministic replay/backtesting and demo-execution project.

## Current components

| Component | Version | Status | Purpose |
| --- | --- | --- | --- |
| [Bybit Scanner V2.6](apps/scanner_v2_6/) | `2.6.0-rc2` | **Active** | Current multi-timeframe signal core and scanner |
| [Bybit Demo AutoTrader](apps/autotrader/) | `1.5.4` | **Active / Demo only** | Executes confirmed scanner events in Bybit Demo Trading |
| [Bybit Scanner V2.5](legacy/scanner_v2_5/) | `2.5.1` | **Reference + LIVE safety hotfix** | Preserved comparison baseline with a TP-ladder validity guard |

The repository is deliberately Bybit-only. Operational credentials, runtime databases, logs, cloud/server details and account-specific state are not source artifacts.

## System flow

```text
Bybit public REST / WebSocket data
        ↓
Scanner multi-timeframe analysis
        ↓
Confirmed EXECUTE + deterministic Entry / SL / TP ladder
        ↓
Persistent signal record
        ├────────────→ optional AI Judge research (SHADOW only)
        ↓
Signed scanner → AutoTrader bridge protocol v1
        ↓
Bybit Demo AutoTrader
        ↓
Shared TP1 → breakeven → TP2 → TP1 protection lifecycle
```

AI is intentionally outside the execution authority boundary. It cannot veto or mutate a confirmed trade.

## Runtime deployment

Current LIVE development/research deployments run on **Google Cloud Compute Engine virtual machines** as long-running Python services. The deployment model is intentionally separated from the public source tree: instance names, IP addresses, Google Cloud project identifiers, service-account credentials, SSH material and environment-specific runtime state are not committed.

The public repository contains portable application code, tests and safe configuration templates so the components can be reproduced on another Linux host without depending on private Google Cloud metadata.

## Scanner V2.6

- Bybit USDT Linear Perpetual universe
- 4H / 1H / 15M / 5M / 1M context
- confirmed-candle signal core
- fair market rotation and liquidity filters
- micro-confirmation, structure, spread, stop-distance and obstacle checks
- stale-data freeze plus WebSocket/REST failover
- signal lifecycle, replay comparison and research statistics
- Discord monitoring
- optional signed bridge to the Demo AutoTrader
- V2 Blind AI research is LIVE as SHADOW only; exact latest V2 Blind source parity still requires a fresh sanitized deployment import

See [apps/scanner_v2_6/README.md](apps/scanner_v2_6/README.md) and [apps/scanner_v2_6/AI_JUDGE_V2_BLIND.md](apps/scanner_v2_6/AI_JUDGE_V2_BLIND.md).

## Scanner V2.5 reference and safety hotfix

V2.5 remains the historical comparison family, but one malformed-order safety defect discovered in LIVE operation required a narrow hotfix. Obstacle-aware TP caps could independently compress targets until the ladder became non-monotonic.

The final target ladder is now required to satisfy:

- LONG: `entry < TP1 < TP2 < TP3`
- SHORT: `entry > TP1 > TP2 > TP3`

A malformed ladder must not become `EXECUTE`. This is a safety validation fix, not AI-driven strategy optimization.

V2.5 also runs AI Judge V2 Blind as observation-only research. V2.5 AI telemetry stays separate from V2.6 and keeps provider token-usage accounting.

See [legacy/scanner_v2_5/README.md](legacy/scanner_v2_5/README.md) and [legacy/scanner_v2_5/AI_JUDGE_V2_BLIND.md](legacy/scanner_v2_5/AI_JUDGE_V2_BLIND.md).

## AI Judge V2 Blind — current decision

LIVE prompt contracts:

- V2.5: `ai-judge-v2-blind-v25`
- V2.6: `ai-judge-v2-blind-v26`

V2 research records `edge_score`, `risk_score`, confidence and structured reason codes for later calibration. V1 history is retained rather than overwritten.

The 2026-09-14 audit did **not** justify promoting AI into a hard gate. Score-to-realized-R correlations were weak in both scanner samples, so AI remains SHADOW-only. Some reason-code cohorts looked meaningfully negative, but the sample was not promoted into deterministic trading rules.

See [docs/research-status-2026-09-14.md](docs/research-status-2026-09-14.md) for the measured snapshot, sample sizes and caveats.

## Historical Pattern V1 decision

A separate raw candle-shape walk-forward experiment was evaluated and rejected as a LIVE gate. The historical edge/expectancy signals had near-zero rank correlation with realized R, while the would-block cohort was profitable in the observed sample. Raw candle-shape matching therefore remains out of LIVE decision logic.

Any future historical-context model must start as a new SHADOW experiment with a new versioned contract. V2.6 remains the unchanged benchmark for that line of research.

## Demo AutoTrader

- Bybit Demo Trading only
- idempotent signal handling
- isolated-margin enforcement
- risk-based sizing with explicit caps
- leverage target with instrument-limit fallback
- protective SL before TP setup
- reduce-only TP1 / TP2 / TP3 orders
- TP1 full fill → remaining stop can move to breakeven
- TP2 full fill → remaining stop can move to TP1
- monotonic stop protection
- SQLite restart recovery
- signed bridge and fail-closed request validation

## Shared bridge protocol

The shared protocol under `src/open_crypto_signal_engine/protocol/` provides deterministic JSON, timestamped HMAC-SHA256 authentication, protocol-version handling, common `EXECUTE` / `MANAGEMENT` validation and extension-field preservation.

See [docs/bridge-protocol.md](docs/bridge-protocol.md).

## Deterministic replay/backtesting

The reusable backtesting package provides normalized OHLCV, deterministic LONG/SHORT replay, explicit same-candle stop/target collision policy, configurable fees/slippage, shared TP protection, R-based outcomes, MFE/MAE, drawdown and per-setup summaries.

See [docs/backtesting.md](docs/backtesting.md).

## Repository layout

```text
.
├── apps/
│   ├── scanner_v2_6/
│   └── autotrader/
├── legacy/
│   └── scanner_v2_5/
├── src/open_crypto_signal_engine/
│   ├── backtesting/
│   ├── protocol/
│   └── risk/
├── tests/
├── examples/replay/
├── docs/
│   ├── architecture.md
│   ├── backtesting.md
│   ├── bridge-protocol.md
│   ├── credential-safety.md
│   ├── research-status-2026-09-14.md
│   └── releasing.md
├── CHANGELOG.md
├── SECURITY.md
├── LICENSE
└── pyproject.toml
```

## Quick start

```bash
git clone https://github.com/Vytis80/OpenCryptoSignalEngine.git
cd OpenCryptoSignalEngine
pip install -e ".[dev]"
pytest tests
```

Runnable components have their own requirements and `.env.example` files. Use only your own local credentials and never commit a real `.env`.

## Testing and release readiness

CI currently covers:

- shared package on Python 3.11 / 3.12 / 3.13
- Scanner V2.6 offline gate
- Demo AutoTrader tests
- V2.5 regression tests
- public Bybit-only scope enforcement
- package/release-readiness build
- dedicated secret scan

Release metadata and forbidden tracked artifacts are checked with:

```bash
python tools/check_release_readiness.py
```

The first public development release workflow is prepared, but the GitHub release should only be published from a source snapshot whose documented LIVE parity is understood. See [docs/releasing.md](docs/releasing.md).

## Source-parity rule

Research conclusions from LIVE operation may be documented from validated chat/analysis history, but the repository must not pretend that undocumented deployment code is already present. The exact latest AI Judge V2 Blind implementation still requires a fresh sanitized source export before the public repo can claim exact LIVE source parity.

## Credential safety

Never commit:

- Bybit API keys/secrets
- Discord tokens/webhooks or account IDs
- Groq/API-provider keys
- bridge/HMAC secrets
- `.env` or backup copies
- SSH/private keys or cloud credentials
- runtime SQLite DBs, AI responses, logs, trade/order history or deployment-specific state

See [docs/credential-safety.md](docs/credential-safety.md) and [SECURITY.md](SECURITY.md).

If a credential ever existed in an archive, backup, shell history, chat or commit, rotate it at the provider; deleting a copy is not equivalent to rotation.

## Coming next: Jarvis Integration

A planned **Jarvis agent layer** will provide optional monitoring, diagnostics, research orchestration and maintainer/operator workflows across the project. Jarvis is planned as an additional control-plane layer, not a replacement for deterministic scanner, risk-management or execution logic. It must not silently bypass signal validation, risk controls or the signed AutoTrader boundary.

## Project status

Current priorities are:

1. keep V2.6, AutoTrader and the V2.5 comparison family deterministic and CI-covered;
2. preserve the V2.5 TP-ladder safety hard gate;
3. keep AI research SHADOW-only until predictive value is demonstrated on larger closed-signal samples;
4. import the exact current V2 Blind source from a fresh sanitized LIVE snapshot before claiming full source parity;
5. keep failed historical-pattern gating ideas documented instead of silently reintroducing them;
6. maintain permanent credential scanning and reproducible release gates;
7. design the future Jarvis integration without weakening deterministic execution and security boundaries.

## Disclaimer

This project is for educational, research and software-development purposes. It is not financial or investment advice. Cryptocurrency derivatives can result in rapid loss of capital. Use demo/paper environments before considering live deployment.

## License

Licensed under the [MIT License](LICENSE).
