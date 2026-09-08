# Release readiness and packaging

OpenCryptoSignalEngine uses a fail-closed release-readiness gate before development tags or package artifacts are published.

## What the gate checks

`python tools/check_release_readiness.py` verifies:

- the root package version in `pyproject.toml` matches `open_crypto_signal_engine.__version__`;
- the README component table matches the `VERSION` files for Scanner V2.6, Demo AutoTrader and the frozen V2.5 baseline;
- tracked files do not contain forbidden runtime/secret artifact names such as `.env`, private-key files, SQLite databases, logs, private data directories or bridge-secret files.

GitHub Actions then builds both a wheel and source distribution and installs the wheel into a fresh virtual environment. The clean environment must successfully import the shared risk, protocol and backtesting packages.

## Release checklist

Before creating a development tag:

1. Confirm Scanner V2.6, Demo AutoTrader and frozen V2.5 `VERSION` files describe the intended snapshot.
2. Update README and CHANGELOG only when the implementation actually supports the documented behavior.
3. Run `python tools/check_release_readiness.py`.
4. Run repository tests and component-specific offline gates.
5. Confirm the dedicated GitHub secret scan succeeds.
6. Build with `python -m build` and smoke-install the wheel in a clean virtual environment.
7. Review the final Git diff for credentials, account data, private infrastructure details and runtime state.
8. Create a tag/release only from a green `main` commit.

A failed metadata, package-build, component-test or secret-scan check blocks the release.

## What the root Python package contains

The wheel is the reusable, exchange-independent library layer under `src/open_crypto_signal_engine/`, including shared risk lifecycle, deterministic replay/backtesting and scanner-to-executor bridge protocol helpers.

The runnable applications are intentionally maintained as repository components rather than silently bundled into the root wheel:

- `apps/scanner_v2_6/`
- `apps/autotrader/`
- `legacy/scanner_v2_5/`

A repository tag therefore identifies the full project snapshot, while the root wheel represents only the shared Python package.

## What must never be included

Release artifacts and Git history must not contain operational credentials or private runtime state, including:

- Bybit API keys/secrets;
- Discord bot tokens or webhook URLs;
- bridge/HMAC secrets;
- `.env` runtime files or backups;
- SSH/private keys;
- cloud/server credentials or private infrastructure paths;
- account-specific databases, orders, positions, trade history or logs.

`.env.example` files are allowed only when they contain placeholders.

## Network boundary

Release CI is intentionally network-free with respect to Bybit and Discord. It validates software packaging and deterministic offline behavior, not live account connectivity. Deployment-host preflight checks remain separate and require the operator's own local credentials.
