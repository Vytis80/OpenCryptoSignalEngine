# Release readiness and packaging

OpenCryptoSignalEngine uses a fail-closed release-readiness gate before development tags or package artifacts are published.

## What the gate checks

`python tools/check_release_readiness.py` verifies:

- the root package version in `pyproject.toml` matches `open_crypto_signal_engine.__version__`;
- the README component table matches the `VERSION` files for Scanner V2.6, Demo AutoTrader and the frozen V2.5 baseline;
- tracked files do not contain forbidden runtime/secret artifact names such as `.env`, private-key files, SQLite databases, logs, private data directories or bridge-secret files.

GitHub Actions then builds both a wheel and source distribution and installs the wheel into a fresh virtual environment. The clean environment must successfully import the shared risk, protocol and backtesting packages.

## Tag convention

The development release tag is derived directly from the root Python package version:

```text
package version 0.1.0.dev0 -> Git tag v0.1.0.dev0
```

The manual release workflow refuses a tag that does not exactly match `v` plus the version in `pyproject.toml`.

## Release checklist

Before creating a development tag:

1. Confirm Scanner V2.6, Demo AutoTrader and frozen V2.5 `VERSION` files describe the intended snapshot.
2. Update README and CHANGELOG only when the implementation actually supports the documented behavior.
3. Add release notes at `docs/releases/<tag>.md`.
4. Run `python tools/check_release_readiness.py`.
5. Run repository tests and component-specific offline gates.
6. Confirm the dedicated GitHub secret scan succeeds.
7. Build with `python -m build` and smoke-install the wheel in a clean virtual environment.
8. Review the final Git diff for credentials, account data, private infrastructure details and runtime state.
9. Merge only after the PR CI and secret scan are green.
10. Confirm the resulting `main` push CI and secret scan are green.
11. Run the **Publish development release** workflow from the `main` branch and provide the exact expected tag.

A failed metadata, package-build, component-test or secret-scan check blocks the release.

## Manual GitHub release workflow

The repository contains `.github/workflows/release.yml`. It uses `workflow_dispatch`, so publishing remains an explicit maintainer action rather than happening automatically on every merge.

In GitHub:

1. Open **Actions**.
2. Select **Publish development release**.
3. Choose **Run workflow**.
4. Select branch **main**.
5. Enter the expected tag, for example `v0.1.0.dev0`.
6. Run the workflow.

The workflow fails if it is launched from a non-main ref, if the requested tag differs from the root package version, if matching release notes are missing, if release readiness fails, or if that tag/release already exists. It rebuilds the wheel and source distribution, smoke-installs the wheel, and then uses the repository-scoped `GITHUB_TOKEN` to create a GitHub **prerelease** and attach both package artifacts.

The release workflow does not use Bybit, Discord, bridge or deployment credentials.

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
