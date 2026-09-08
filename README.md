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
| [Bybit Scanner V2.5](legacy/scanner_v2_5/) | `2.5.1` | **Frozen reference** | Preserved baseline for regression comparison and replay |

V2.5 is intentionally retained as a frozen reference rather than silently overwritten by V2.6. This makes strategy evolution and replay comparisons auditable.

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
Signal lifecycle + monitoring
        ↓
Signed bridge
        ↓
Bybit Demo AutoTrader
        ↓
Shared TP protection lifecycle
        ↓
TP fills + dynamic stop protection + statistics
```

The current project is deliberately **Bybit-only**. The public repository does not contain exchange-account credentials, Discord credentials, cloud/server details, or private runtime databases.

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

- preserved signal behavior for regression comparison
- observation-only SMART / shadow research layers
- separate baseline for replay against V2.6

## Repository layout

```text
.
├── apps/
│   ├── scanner_v2_6/       # active scanner / signal core
│   └── autotrader/         # active Bybit Demo executor
├── legacy/
│   └── scanner_v2_5/       # frozen reference baseline
├── src/
│   └── open_crypto_signal_engine/  # shared risk + backtesting package
├── tests/                  # repository-level deterministic tests
├── examples/
│   └── replay/             # synthetic replay fixture/example
├── docs/
│   ├── architecture.md
│   ├── backtesting.md
│   └── credential-safety.md
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

The AutoTrader is designed for **Bybit Demo Trading**. Its installer expects a full repository clone because the runtime installs and uses the shared risk package. Do not put a production exchange API key into the example configuration or Git history.

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
- bridge/HMAC secrets
- `.env` runtime files or backup copies
- SSH/private keys
- cloud/server credentials or private infrastructure paths
- account-specific SQLite databases, order history, logs or runtime state

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

Component dependencies are intentionally isolated. CI installs and tests V2.6, the Demo AutoTrader plus the shared risk package, and the frozen V2.5 baseline independently.

Live connectivity checks are not run in CI because they require user credentials or public-network access. Unit/offline tests must not require real credentials.

## Risk management

Signal generation, pure risk policy, exchange execution and replay are separate layers. The shared lifecycle defines deterministic protection intent: initial SL, TP1 → breakeven, TP2 → TP1, explicit invalidation, and a monotonic rule that never loosens an already stricter stop.

AutoTrader 1.5.4 uses that shared post-TP contract for automatic TP protection while retaining exchange verification, retry, persistence and recovery logic in the execution layer.

Risk behavior is software behavior, not a guarantee of profitable trading. Crypto derivatives can result in rapid losses.

## Project status

The repository is under active development. Current priorities are:

1. keep Scanner V2.6, AutoTrader and the frozen V2.5 baseline covered by deterministic CI;
2. expand reproducible replay datasets and strategy-level regression coverage without private account data;
3. formalize additional shared interfaces between scanner, bridge and executor only where they reduce risk rather than add coupling;
4. publish tagged development releases after validation;
5. keep credential scanning and the V2.5 frozen baseline as permanent safety gates.

See [CHANGELOG.md](CHANGELOG.md) and the open GitHub issues for tracked work.

## Contributing

Contributions, bug reports and focused improvement proposals are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request.

Do not include credentials, private logs, account data, or copied `.env` files in issues or PRs.

## Disclaimer

This project is provided for educational, research and software-development purposes only. It is not financial or investment advice. Cryptocurrency and derivatives trading involve substantial risk and may result in loss of capital.

Use paper/demo environments before considering any live deployment.

## License

Licensed under the [MIT License](LICENSE).
