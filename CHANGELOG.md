# Changelog

All notable repository-level changes are documented here.

## [Unreleased]

### Added

- public research-status snapshot for the confirmed 2026-09-10 through 2026-09-14 LIVE validation work
- AI Judge V2 Blind SHADOW contract documentation for Scanner V2.5 and Scanner V2.6
- explicit prompt-contract identifiers `ai-judge-v2-blind-v25` and `ai-judge-v2-blind-v26`
- documented V2 Blind research outputs: `edge_score`, `risk_score`, confidence and structured reason codes
- point-in-time 2026-09-14 AI calibration audit with sample sizes, rank correlations and reason-code cohort observations
- documented Historical Pattern V1 walk-forward result and the decision not to promote raw candle-shape matching into LIVE decision logic

### Fixed

- documented and synchronized the V2.5 TP-ladder safety invariant discovered after LIVE obstacle-cap analysis: LONG requires `entry < TP1 < TP2 < TP3`, SHORT requires `entry > TP1 > TP2 > TP3`; malformed ladders must not become `EXECUTE`
- deployment cleanup treats known malformed legacy bridge payloads as invalid rather than retrying them indefinitely; runtime outbox/database contents remain outside Git

### Changed

- V2.5 is now described as a reference baseline with an explicit safety hotfix rather than an absolutely immutable strategy snapshot
- AI Judge V2 Blind remains SHADOW-only after the 2026-09-14 audit showed weak score-to-realized-R separation
- V1 AI history is retained for longitudinal comparison instead of being overwritten by V2 research
- V2.5 and V2.6 AI datasets remain separate
- V2.6 remains unchanged as the benchmark for the rejected Historical Pattern V1 gating experiment
- repository documentation now distinguishes confirmed LIVE research state from exact public-source parity; the latest V2 Blind source still requires a fresh sanitized deployment import before claiming byte-for-byte parity

### Security

- research updates contain aggregate findings only; no LIVE database rows, `.env`, provider keys, Discord/Bybit credentials, bridge secrets, server paths or account-specific runtime state are committed

## [0.1.0.dev0] - 2026-09-09

Prepared first public development snapshot of OpenCryptoSignalEngine. The GitHub Release has not yet been published.

### Added

- initial public repository foundation, documentation, contribution policy and CI setup
- Bybit Scanner V2.6 (`2.6.0-rc2`) as the active scanner and signal core
- Bybit Demo AutoTrader (`1.5.4`) as the active demo-execution component
- Bybit Scanner V2.5.1 as the strategy regression/replay baseline
- exchange-independent dynamic risk lifecycle with deterministic LONG/SHORT tests
- deterministic OHLCV replay/backtesting with fees, slippage, explicit intrabar collision policy, R-based metrics and synthetic fixtures
- shared scanner-to-AutoTrader bridge protocol v1 with deterministic JSON, HMAC signing/verification, timestamp freshness checks and common event validation
- optional EXECUTE-only GPT-OSS 120B AI Judge V1 sidecar for Scanner V2.6 through a Groq-compatible API
- observation-only GPT-OSS AI Judge V1 sidecar for the V2.5 strategy baseline
- separate SQLite AI judgement/outcome research for V2.5 and V2.6
- V2.5 provider prompt/completion/total-token usage tracking plus `/bybit_ai_last`, `/bybit_ai_stats` and `/bybit_ai_usage`
- V2.6 AI inspection commands `/byscan_ai_last` and `/byscan_ai_stats`
- credential-free AI contract, persistence, schema-migration and non-blocking checks; live provider probes are excluded from CI
- component-specific example environment files containing placeholders only
- component test coverage in GitHub Actions
- dedicated credential-safety documentation
- automated secret scanning for pushes and pull requests
- reproducible release-readiness validation for package/component versions and forbidden tracked runtime artifacts
- clean wheel/sdist build plus fresh-venv smoke imports for shared risk, protocol and backtesting packages

### Security

- excluded discovered operational `.env` backups and bridge-secret files from the public import
- excluded source backup trees, runtime SQLite data and deployment-specific configuration
- removed account-specific Discord IDs from committed examples
- removed private deployment paths and setup-specific references from public documentation
- hardened `.gitignore` for secret backups, bridge secrets and database backups
- bridge authentication uses one shared raw-body verifier while retaining compatibility with existing signed v1 requests
- release readiness fails closed when forbidden runtime/secret artifact names are tracked
- external AI access is disabled by default in committed examples and requires a user-owned local provider key
- no live AI response database, private signal history or AI-provider credential is included in the public sync

### Changed

- root README documents the V2.6 / AutoTrader / V2.5 component model
- CI isolates repository-level linting from preserved component source style and runs component tests separately
- risk milestone intent is formalized independently from exchange order execution
- AutoTrader automatic TP1/TP2 protection is routed through the shared post-TP risk contract while Bybit verification/retry/persistence remain in the execution layer
- Scanner V2.6 and AutoTrader bridge adapters share transport serialization/authentication and common event validation
- V2.6 queues the Demo AutoTrader bridge before awaiting the optional AI Judge, so provider latency/failure cannot veto the already-confirmed execution event
- V2.5 and V2.6 AI samples remain separate to avoid mixing baseline and current-core research
- active Scanner and AutoTrader installation require the full repository clone so shared packages are installed into component venvs
- development releases have a documented, reproducible metadata/package validation checklist before tagging
