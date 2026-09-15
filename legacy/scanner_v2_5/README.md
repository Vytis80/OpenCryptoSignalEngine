# Bybit Scanner V2.5.1 — Reference baseline + safety hotfix

V2.5.1 remains the historical comparison family for regression and replay. It is not the primary development target.

The strategy is treated as frozen **except for explicit safety defects**. A 2026-09-11 LIVE audit found one such defect in obstacle-aware TP capping, so V2.5 received a narrow target-ladder validity hard gate.

## Current safety invariant

Final targets must be strictly monotonic:

- LONG: `entry < TP1 < TP2 < TP3`
- SHORT: `entry > TP1 > TP2 > TP3`

If that invariant fails, the setup must not become `EXECUTE`. The root cause was independent capping of TP1/TP2/TP3 near an obstacle, which could collapse target ordering.

Malformed legacy bridge retries found during deployment cleanup were classified as invalid payloads rather than retried indefinitely. Runtime outbox rows and account-specific databases are intentionally not committed.

## Highlights

- Bybit USDT Linear Perpetual market data
- 1H / 15M / confirmed 5M strategy baseline
- EARLY and POTENTIAL lifecycle
- Dynamic entry validity
- Observation-only SMART research
- Diagnostic anti-SL shadow research
- Durable bridge outbox for downstream demo execution
- SQLite signal/research state
- Discord control and monitoring

## AI Judge research status

The public repository first imported the V1 GPT-OSS AI sidecar. LIVE research later moved to **AI Judge V2 Blind SHADOW** with prompt contract `ai-judge-v2-blind-v25`.

V2 Blind records separate `edge_score`, `risk_score`, confidence and structured reason codes, while V2.5 also keeps provider token-usage accounting. AI research remains separate from V2.6 data.

AI cannot suppress an `EXECUTE`, rewrite Entry/SL/TP, change size/management or control the AutoTrader bridge. The bridge path remains authoritative and precedes any AI wait.

The 2026-09-14 audit did not justify a hard AI gate, so AI remains SHADOW-only. See `AI_JUDGE_V2_BLIND.md` and `../../docs/research-status-2026-09-14.md`.

**Source-parity note:** exact latest V2 Blind LIVE source still requires a fresh sanitized deployment import. The current repository keeps the earlier V1 implementation/history instead of pretending parity.

## Install

```bash
cp .env.example .env
# Fill only your own local values. Never commit the resulting .env.
./install.sh
.venv/bin/python self_test.py
```

## Security

Never commit `.env`, tokens, webhooks, IDs, API credentials, Groq/provider keys, bridge secrets, runtime DBs, backups or logs. Public CI remains credential-free and network-free for AI-provider checks.

## Status

**Reference baseline with explicit safety hotfix.** New strategy development belongs in `apps/scanner_v2_6`. Observation-only research may be measured here, but it must stay separate from deterministic trading decisions.

See `AI_JUDGE_V25.md` for the historical public V1 contract, `AI_JUDGE_V2_BLIND.md` for the current LIVE research contract, and `VALIDATION_SMART_SHADOW_35D.md` for earlier research notes.
