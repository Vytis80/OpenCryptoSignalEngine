# OpenCryptoSignalEngine

[![CI](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml/badge.svg)](https://github.com/Vytis80/OpenCryptoSignalEngine/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Open-source multi-timeframe crypto market analysis, signal generation, risk management, backtesting and paper trading framework focused on Bybit.

> **Project status:** early active development. The repository currently contains the public project foundation; production trading logic will be added only after it has been reviewed for secrets, private infrastructure details and exchange-account data.

## Overview

OpenCryptoSignalEngine is a modular Python framework for cryptocurrency market analysis and systematic trading research.

The project is designed around a clear separation between market data, multi-timeframe analysis, signal generation, risk management, execution, backtesting and monitoring. The initial exchange target is **Bybit**.

## Project Scope

- Multi-timeframe cryptocurrency market analysis
- Market structure and trend evaluation
- Systematic LONG / SHORT signal generation
- Stop-loss and take-profit logic
- Dynamic risk and trade management
- Historical backtesting and signal replay
- Paper and Bybit demo trading
- Bybit API integration
- Discord-based monitoring and notifications

## Architecture

```text
Market Data (Bybit REST / WebSocket)
    ↓
Multi-Timeframe Analysis
    ↓
Market Structure Evaluation
    ↓
Signal Generation
    ↓
Risk & Trade Management
    ↓
Paper / Demo Execution
    ↓
Backtesting & Performance Analysis
    ↓
Discord Monitoring
```

The components are intended to remain modular so that analysis, strategy, execution and notification layers can evolve independently.

## Core Features

The project is being built around the following capabilities:

- Multi-timeframe market analysis
- Trend and market structure detection
- LONG / SHORT signal generation
- Configurable stop-loss and take-profit logic
- Dynamic trade management
- Risk-based position sizing
- Historical backtesting
- Paper and demo trading
- Bybit API integration
- WebSocket and REST market data handling
- Connection health and stale-data protection
- Discord alerts and monitoring
- Modular strategy and execution components

## Risk Management

OpenCryptoSignalEngine is designed to support structured trade management instead of static entry/exit logic.

Example management flow:

- Initial stop-loss is defined before entry
- TP1 reached → stop-loss can move to breakeven
- TP2 reached → stop-loss can move to the TP1 level
- Further profit protection can be applied as the trade progresses
- Position sizing can be calculated from predefined account risk
- Trades can be invalidated when market structure changes
- Risk logic remains separate from signal generation and execution

## Backtesting & Paper Trading

The framework is intended to support strategy validation before any live deployment:

- Historical strategy backtesting
- Signal replay and validation
- Paper trading without real capital
- Bybit demo execution
- Trade outcome tracking
- Performance statistics
- Strategy comparison
- Risk-management validation

## Bybit Integration

The initial exchange integration is **Bybit**. Exchange-specific code is kept separate from core analysis and strategy logic.

The integration layer is intended to handle:

- Market data retrieval
- WebSocket market-data streams
- REST API fallback
- Symbol and instrument metadata
- Paper / demo order execution
- Position and order state tracking
- Exchange-specific error handling
- Connection health and data freshness monitoring

## Discord Monitoring & Notifications

Discord notifications are intended for:

- Signal alerts
- Setup state changes
- Trade-entry notifications
- Stop-loss and take-profit updates
- Paper / demo trade results
- Bot health and status messages
- Errors and connection issues
- Performance and statistics reports

## Repository Layout

```text
.
├── .github/                 # CI, issue templates and PR template
├── docs/                    # Architecture and project documentation
├── src/
│   └── open_crypto_signal_engine/
│       └── __init__.py
├── tests/                   # Automated tests
├── .env.example             # Safe configuration example
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── LICENSE
└── pyproject.toml
```

## Development Setup

### Requirements

- Python 3.11+
- Git

### Install

```bash
git clone https://github.com/Vytis80/OpenCryptoSignalEngine.git
cd OpenCryptoSignalEngine
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### Run checks

```bash
pytest
ruff check .
ruff format --check .
```

## Configuration

Copy the example environment file and fill in your own values locally:

```bash
cp .env.example .env
```

Never commit `.env`, API credentials, Discord tokens, webhook URLs, private keys or account data.

## Project Status

OpenCryptoSignalEngine is under active development. The current focus is building and validating the core Bybit research and demo-execution pipeline before exposing more advanced trading modules publicly.

## Roadmap

- Import and sanitize the existing Bybit scanner codebase
- Formalize multi-timeframe signal interfaces
- Refine dynamic stop-loss and take-profit management
- Add risk-based position sizing
- Add historical backtesting and replay
- Add Bybit demo execution
- Add Discord monitoring and bot-health reporting
- Expand automated tests and validation
- Add reproducible examples and sample datasets
- Publish the first tagged development release

See [CHANGELOG.md](CHANGELOG.md) for repository-level changes.

## Contributing

Contributions, bug reports and improvement suggestions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

Do not report credentials or sensitive trading/account information in public issues. See [SECURITY.md](SECURITY.md) for the reporting policy.

## Disclaimer

This project is provided for educational, research and software-development purposes only. It does not constitute financial or investment advice. Cryptocurrency and derivatives trading involve substantial risk and may result in loss of capital.

Paper or demo trading should be used before considering any live environment.

## License

Licensed under the [MIT License](LICENSE).
