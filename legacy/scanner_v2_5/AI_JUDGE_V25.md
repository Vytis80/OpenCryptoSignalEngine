# V2.5 AI Judge V1 — historical public contract

This file documents the first public V2.5 observational GPT-OSS AI Judge contract imported on 2026-09-09. LIVE research later moved to **AI Judge V2 Blind SHADOW** under `ai-judge-v2-blind-v25`; see `AI_JUDGE_V2_BLIND.md`.

The V1 implementation/history is retained for auditability and must not be mistaken for the latest LIVE research contract.

## Invariant

V2.5 decides EXECUTE, Entry, SL, TP and management without AI. The Demo AutoTrader bridge is queued before waiting for AI, so AI latency/failure cannot veto or alter the trade. Legacy SHADOW and SMART remain research evidence only.

## Stored V1 research data

V1 stored verdict, confidence, quality, risk, summary, latency and provider token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) in the local `ai_judgements` table. Runtime databases are never committed.

Historical inspection commands:

- `/bybit_ai_last`
- `/bybit_ai_stats`
- `/bybit_ai_usage`

V2.5 and V2.6 research remains separate. A successful API call is connectivity evidence, not predictive-edge evidence.

## Privacy and cost

When explicitly enabled, structured signal evidence is sent to the configured external AI provider. Keep provider credentials local and do not send account secrets or private runtime state.

CI remains credential-free and network-free for this feature.
