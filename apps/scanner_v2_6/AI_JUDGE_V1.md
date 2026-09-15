# V2.6 AI Judge V1 — historical public contract

This file documents the first public observational AI Judge contract imported on 2026-09-09. LIVE research later moved to **AI Judge V2 Blind SHADOW** under `ai-judge-v2-blind-v26`; see `AI_JUDGE_V2_BLIND.md`.

The V1 source is retained for auditability and longitudinal comparison. It must not be mistaken for the latest LIVE research contract.

## Safety contract

The AI Judge is **shadow-only**. It cannot create, veto, delay, resize or modify an AutoTrader trade. Scanner strategy, Entry, SL, TP, leverage, size and management remain deterministic and authoritative.

For a new EXECUTE signal the scanner persists the signal and spawns the signed Demo AutoTrader bridge task **before** awaiting the AI request. AI latency or failure therefore cannot block the execution path.

The V1 module has no Bybit order or bridge access. Its output is limited to `APPROVE`/`REJECT`, verdict confidence, setup-quality grade, risk label, concise summary, strengths and risks. Confidence means confidence in the review verdict, not probability of profit.

## Configuration

Public examples are opt-in and contain placeholders only. Never commit a real provider credential.

## Storage and Discord

V1 judgements are stored in local runtime SQLite for comparison with later outcomes. Runtime DB contents are not part of the repository.

Historical V1 inspection commands:

- `/byscan_ai_last`
- `/byscan_ai_stats`

V2.6 research must remain separate from V2.5 because their scanner evidence and prompt contracts differ.

## CI boundary

Repository CI tests credential-free contract/persistence/non-blocking behavior without contacting the external provider. Live API checks belong on the deployment host with operator-owned credentials.
