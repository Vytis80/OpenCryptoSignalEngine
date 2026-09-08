# Changelog

All notable repository-level changes are documented here.

## [Unreleased]

## [0.1.0.dev0] - 2026-09-08

First public development release of OpenCryptoSignalEngine.

### Added

- initial public repository foundation, documentation, contribution policy and CI setup
- Bybit Scanner V2.6 (`2.6.0-rc2`) as the active scanner and signal core
- Bybit Demo AutoTrader (`1.5.4`) as the active demo-execution component
- Bybit Scanner V2.5.1 as a frozen regression/replay baseline
- exchange-independent dynamic risk lifecycle with deterministic LONG/SHORT tests
- deterministic OHLCV replay/backtesting with fees, slippage, explicit intrabar collision policy, R-based metrics and synthetic fixtures
- shared scanner-to-AutoTrader bridge protocol v1 with deterministic JSON, HMAC signing/verification, timestamp freshness checks and common event validation
- component-specific example environment files containing placeholders only
- component test coverage in GitHub Actions
- dedicated credential-safety documentation
- automated secret scanning for pushes and pull requests
- reproducible release-readiness validation for package/component versions and forbidden tracked runtime artifacts
- clean wheel/sdist build plus fresh-venv smoke imports for shared risk, protocol and backtesting packages

### Security

- excluded all discovered operational `.env` backups and bridge-secret files from the public import
- excluded source backup trees, runtime SQLite data and deployment-specific configuration
- removed account-specific Discord IDs from committed examples
- removed private deployment paths and setup-specific references from public documentation
- hardened `.gitignore` for secret backups, bridge secrets and database backups
- bridge authentication uses one shared raw-body verifier while retaining compatibility with existing signed v1 requests
- release readiness fails closed when forbidden runtime/secret artifact names are tracked

### Changed

- root README documents the actual V2.6 / AutoTrader / V2.5 component model
- CI isolates repository-level linting from preserved component source style and runs component tests separately
- risk milestone intent is formalized independently from exchange order execution
- AutoTrader automatic TP1/TP2 protection is routed through the shared post-TP risk contract while Bybit verification/retry/persistence remain in the execution layer
- Scanner V2.6 and AutoTrader bridge adapters share transport serialization/authentication and common event validation
- active Scanner and AutoTrader installation require the full repository clone so shared packages are installed into component venvs
- development releases have a documented, reproducible metadata/package validation checklist before tagging
