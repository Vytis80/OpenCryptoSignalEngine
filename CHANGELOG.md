# Changelog

All notable repository-level changes are documented here.

## [Unreleased]

### Added

- Bybit Scanner V2.6 (`2.6.0-rc2`) as the active scanner and signal core
- Bybit Demo AutoTrader (`1.5.3`) as the active demo-execution component
- Bybit Scanner V2.5.1 as a frozen regression/replay baseline
- component-specific example environment files containing placeholders only
- component test coverage in GitHub Actions
- dedicated credential-safety documentation
- automated secret scanning for pushes and pull requests

### Security

- excluded all discovered operational `.env` backups and bridge-secret files from the public import
- excluded source backup trees, runtime SQLite data and deployment-specific configuration
- removed account-specific Discord IDs from committed examples
- removed private deployment paths and setup-specific references from public documentation
- hardened `.gitignore` for secret backups, bridge secrets and database backups

### Changed

- root README now documents the actual V2.6 / AutoTrader / V2.5 component model
- CI isolates repository-level linting from preserved component source style and runs component tests separately

## [0.1.0-dev] - 2026-09-08

Initial public repository foundation, documentation, contribution policy and CI setup.
