# OpenCryptoSignalEngine

[![CI](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml/badge.svg)](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml)
[![Secret scan](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/secret-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Open-source Bybit-focused crypto market analysis, signal generation, risk management, backtesting and demo-execution project.

## Components

| Component | Version | Status | Purpose |
| --- | --- | --- | --- |
| [Bybit Scanner V2.6](apps/scanner_v2_6/) | `2.6.0-rc2` | **Active** | Current multi-timeframe signal core and scanner |
| [Bybit Demo AutoTrader](apps/autotrader/) | `1.5.4` | **Active / Demo only** | Executes scanner `EXECUTE` events in Bybit Demo Trading |
| [Bybit Scanner V2.5](legacy/scanner_v2_5/) | `2.5.1` | **Frozen reference** | Preserved strategy baseline for regression comparison and replay |

V2.5 is intentionally retained as a frozen strategy reference rather than silently overwritten by V2.6. Observation-only research sidecars may be measured against it, but must not change the preserved signal behavior.

## What the system does

```text
Bybit REST / WebSocket market data
        ↓
Multi-timeframe market structure
        ↓
Signal quality + execution gates
        ↓
Entry / Stop / TP1 / TP2 / TP3
        ↓
Confirmed EXECUTE persistence
        ├──────────────→ optional GPT-OSS AI Judge (shadow research only)
        ↓
Signed bridge protocol v1
        ↓
Bybit Demo AutoTrader
        ↓
Shared TP protection lifecycle
        ↓
TP fills + dynamic stop protection + statistics
```

The current project is deliberately **Bybit-only**. The public repository does not contain exchange-account credentials, Discord credentials, Groq credentials, cloud/server details, or private runtime databases.

## Highlights

### Scanner V2.6

- Bybit USDT Linear Perpetual market universe
- 4H / 1H / 15M / 5M / 1M context
- fair whole-market rotation
- confirmed-candle signal core
- micro-confirmation and market-structure execution gates
- dynamic entry-window validity
- stale-data freeze and REST/WebSocket failover
- stop-distance and obstacle-aware checks
- signal lifecycle, replay comparison and edge statistics
- Discord monitoring
- optional signed bridge to the Demo AutoTrader
- optional EXECUTE-only GPT-OSS 120B AI Judge as a non-blocking research sidecar

### Optional GPT-OSS AI Judge

- uses `openai/gpt-oss-120b` through a Groq-compatible API by default when explicitly enabled
- disabled by default in committed example configuration
- runs only after the scanner has already confirmed and persisted an `EXECUTE`
- V2.6 queues the optional AutoTrader bridge before awaiting the AI provider
- AI verdicts cannot veto the signal or change Entry, SL, TP levels, size or management
- V2.6 stores verdict/latency research and exposes `/byscan_ai_last` plus `/byscan_ai_stats`
- frozen V2.5 uses the same observation-only boundary while keeping its strategy unchanged
- V2.5 stores separate AI research and prompt/completion/total-token usage, exposed through `/bybit_ai_last`, `/bybit_ai_stats` and `/bybit_ai_usage`
- live provider probes are intentionally excluded from public CI; offline contract, persistence, migration and non-blocking checks are used instead

Enabling the AI sidecar sends structured setup/signal evidence to the configured external provider. Provider credentials and runtime AI responses belong only in local ignored configuration/state. See [apps/scanner_v2_6/AI_JUDGE_V1.md](apps/scanner_v2_6/AI_JUDGE_V1.md) and [legacy/scanner_v2_5/AI_JUDGE_V25.md](legacy/scanner_v2_5/AI_JUDGE_V25.md).

### Demo AutoTrader

- hard-wired to Bybit Demo Trading
- idempotent signal handling
- isolated-margin enforcement
- risk-based sizing with explicit caps
- leverage target with instrument-limit fallback
- initial protective SL attached before TP setup
- real reduce-only TP1 / TP2 / TP3 orders
- TP1 full fill → remaining SL can move to breakeven
- TP2 full fill → remaining SL can move to TP1
- automatic TP protection targets are derived from the shared exchange-independent risk lifecycle
- monotonic stop guard prevents loosening protection
- bounded Smart Margin assistance using the real liquidation price
- durable SQLite state and restart recovery
- signed bridge and fail-closed Discord mutations

### Shared bridge protocol

- deterministic compact JSON for new bridge clients
- HMAC-SHA256 authentication over the exact request body
- 30-second timestamp freshness window
- explicit protocol v1 header for new clients while retaining old v1 compatibility
- shared `EXECUTE` and `MANAGEMENT` payload normalization
- extension fields preserved for scanner research/SMART metadata
- transport validation kept independent from strategy and exchange execution

See [docs/bridge-protocol.md](docs/bridge-protocol.md).

### Deterministic replay/backtesting

- normalized OHLCV timestamps and validated candle models
- deterministic LONG/SHORT setup replay
- explicit same-candle stop/target collision policy
- configurable fees and slippage
- shared TP1 → breakeven → TP2 → TP1 protection lifecycle
- R-based outcomes, profit factor, MFE/MAE and maximum drawdown
- per-setup summaries
- synthetic public fixture and runnable example with no private trading data

See [docs/backtesting.md](docs/backtesting.md).

### Frozen V2.5 baseline

- preserved strategy behavior for regression comparison
- observation-only SMART / anti-SL shadow / GPT-OSS AI research layers
- separate baseline for replay against V2.6
- AI usage and outcomes stored independently from V2.6 research

## Repository layout

```text
.
├── apps/
│   ├── scanner_v2_6/       # active scanner / signal core + optional AI sidecar
│   └── autotrader/         # active Bybit Demo executor
├── legacy/
│   └── scanner_v2_5/       # frozen strategy reference + observation-only research
├── src/
│   └── open_crypto_signal_engine/  # shared risk + backtesting + protocol package
├── tests/                  # repository-level deterministic tests
├── examples/
│   └── replay/             # synthetic replay fixture/example
├── docs/
│   ├── architecture.md
│   ├── backtesting.md
│   ├── bridge-protocol.md
│   ├── credential-safety.md
│   └── releasing.md
├── .github/
│   ├── workflows/
│   └── ISSUE_TEMPLATE/
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
├── LICENSE
└── pyproject.toml
```

## Quick start

Clone the repository:

```bash
git clone https://github.com/Vytis80/OpenCryptoSignalEngine.git
cd OpenCryptoSignalEngine
```

Each runnable component has its own dependencies and `.env.example`.

Scanner V2.6:

```bash
cd apps/scanner_v2_6
cp .env.example .env
# Fill only your own local Discord / optional bridge values.
# AI Judge stays disabled unless you explicitly enable it and add your own GROQ_API_KEY.
./install.sh
.venv/bin/python self_test.py
```

Demo AutoTrader:

```bash
cd apps/autotrader
cp .env.example .env
# Fill your own Bybit Demo, Discord and bridge values locally.
./install.sh
```

The active Scanner and AutoTrader installers expect a **full repository clone** because both runtimes install shared repository packages. The AutoTrader is designed for **Bybit Demo Trading**. Do not put a production exchange API key into example configuration or Git history.

Synthetic replay example:

```bash
cd OpenCryptoSignalEngine
pip install -e ".[dev]"
python examples/replay/run_replay.py
```

## Credential safety

Operational secrets are intentionally excluded from the public source import. In particular, the repository must never contain:

- Bybit API keys or API secrets
- Discord bot tokens or webhook URLs
- Groq/API-provider credentials
- bridge/HMAC secrets
- `.env` runtime files or backup copies
- SSH/private keys
- cloud/server credentials or private infrastructure paths
- account-specific SQLite databases, AI response databases, order history, logs or runtime state

Only placeholder `.env.example` files are committed. The repository `.gitignore` blocks common secret/backup artifacts and GitHub Actions runs a dedicated secret scan on pushes and pull requests.

See [docs/credential-safety.md](docs/credential-safety.md) and [SECURITY.md](SECURITY.md).

> If a credential has ever existed in an archive, backup file, terminal history, chat, or commit, rotate it at the provider. Deleting the old copy is not equivalent to rotating the credential.

## Testing

Repository/shared package:

```bash
pip install -e ".[dev]"
pytest tests
ruff check src tests
ruff format --check src tests
```

Component dependencies are intentionally isolated. CI installs and tests V2.6 plus the shared protocol package, the Demo AutoTrader plus shared repository packages, and the frozen V2.5 baseline independently.

Live connectivity and live AI-provider checks are not run in CI because they require user credentials or public-network access. Unit/offline tests must not require real credentials.

## Release readiness

Before a development tag is published, CI verifies package/component version consistency, rejects forbidden tracked runtime/secret artifacts, builds both wheel and source distributions, and smoke-installs the wheel in a clean virtual environment.

Run the metadata/artifact gate locally with:

```bash
python tools/check_release_readiness.py
```

See [docs/releasing.md](docs/releasing.md) for the complete release checklist and packaging boundary.

## Risk management

Signal generation, AI research, pure risk policy, exchange execution and replay are separate layers. The shared lifecycle defines deterministic protection intent: initial SL, TP1 → breakeven, TP2 → TP1, explicit invalidation, and a monotonic rule that never loosens an already stricter stop.

AutoTrader 1.5.4 uses that shared post-TP contract for automatic TP protection while retaining exchange verification, retry, persistence and recovery logic in the execution layer. AI observations are not allowed to mutate this contract.

Risk behavior is software behavior, not a guarantee of profitable trading. Crypto derivatives can result in rapid losses.

## Project status

The repository is under active development. Current priorities are:

1. keep Scanner V2.6, AutoTrader and the frozen V2.5 strategy baseline covered by deterministic CI;
2. expand reproducible replay datasets and strategy-level regression coverage without private account data;
3. keep optional AI research non-blocking, separately measurable and credential-safe;
4. evolve shared risk/protocol interfaces only where they reduce duplicated safety logic without coupling strategy to execution;
5. publish tagged development releases only after the reproducible release-readiness gate passes;
6. keep credential scanning and the V2.5 frozen baseline as permanent safety gates.

See [CHANGELOG.md](CHANGELOG.md) and the open GitHub issues for tracked work.

## Contributing

Contributions, bug reports and focused improvement proposals are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request.

Do not include credentials, private logs, account data, AI-provider keys/responses, or copied `.env` files in issues or PRs.

## Disclaimer

This project is provided for educational, research and software-development purposes only. It is not financial or investment advice. Cryptocurrency and derivatives trading involve substantial risk and may result in loss of capital.

Use paper/demo environments before considering any live deployment.

## License

Licensed under the [MIT License](LICENSE).
