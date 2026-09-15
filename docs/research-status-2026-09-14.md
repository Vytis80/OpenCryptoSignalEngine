# Research and LIVE safety status — 2026-09-14

This document records the latest confirmed project state from the 2026-09-10 through 2026-09-14 LIVE validation work. It is a public research summary, not a dump of runtime databases or account state.

## V2.5 target-ladder safety hotfix

A LIVE V2.5 defect was isolated to obstacle-aware TP capping: TP1, TP2 and TP3 could be capped independently against nearby structure, which could produce a non-monotonic ladder.

The safety rule is now explicit:

- LONG must satisfy `entry < TP1 < TP2 < TP3`;
- SHORT must satisfy `entry > TP1 > TP2 > TP3`.

A malformed ladder must never become an `EXECUTE` signal. Existing malformed bridge retries found during deployment cleanup were classified as invalid payloads rather than retried indefinitely. Runtime outbox rows and account-specific databases remain outside Git.

## AI Judge V2 Blind SHADOW

Both Scanner V2.5 and Scanner V2.6 were switched LIVE to the V2 Blind research contract while remaining strictly observation-only:

- V2.5 prompt contract: `ai-judge-v2-blind-v25`;
- V2.6 prompt contract: `ai-judge-v2-blind-v26`;
- V1 history is retained for longitudinal comparison;
- V2 emits separate `edge_score` (0–100), `risk_score` (0–100), confidence and structured reason codes;
- AI output is stored and analysed separately per scanner generation;
- AI cannot veto an EXECUTE, alter Entry/SL/TP, resize a trade, change management, or control the AutoTrader bridge.

The bridge/execution path remains authoritative and must be queued before any AI wait.

## 2026-09-14 V2 audit

Point-in-time LIVE audit snapshot:

- V2.5: 100 AI evaluations, 94 closed signals;
- V2.6: 23 AI evaluations, 23 closed signals;
- Spearman `edge_score` ↔ realized R: approximately `+0.043` (V2.5) and `+0.016` (V2.6);
- Spearman `risk_score` ↔ realized R: approximately `-0.086` (V2.5) and `-0.023` (V2.6);
- all 6 observed AI `REJECT` cases finished at SL in that snapshot;
- `WEAK_TRIGGER`: 39 cases, 12.8% TP3, about `-0.47R` average;
- `HTF_CONFLICT`: 4 cases, 0 TP3, about `-0.87R` average;
- confidence was concentrated around 70.

These samples were not strong enough to promote AI into a trading gate. AI therefore remains SHADOW-only. The correlations above are research observations, not expected future performance.

## Historical Pattern V1 walk-forward

A separate raw candle-shape historical-pattern experiment was evaluated with a walk-forward process:

- 492 closed signals total;
- 451 had sufficient prior history;
- Spearman historical edge score ↔ realized R: `-0.0176`;
- Spearman historical expectancy ↔ realized R: `-0.0165`;
- the would-block group earned about `+35R` in aggregate (`+0.307R` average).

Conclusion: Historical Pattern V1 was **not** promoted to LIVE and raw candle-shape matching was closed as a gating idea. A veto based on that model would have worsened the observed result. V2.5 LIVE signal logic stayed unchanged apart from the TP-ladder safety hotfix, and V2.6 stayed unchanged as the benchmark for this experiment.

A future historical-context design may be tested only as a new SHADOW experiment with a new contract/version; it must not inherit an implied production status from this document.

## Public-source parity note

The repository documents the confirmed V2 Blind LIVE contract and research results here, but the exact latest LIVE AI Judge source snapshot must be imported from a fresh sanitized deployment export before claiming byte-for-byte source parity. The public V1 AI implementation remains valid historical code until that source sync is performed.

## Security boundary

No LIVE database, order history, `.env`, Groq key, Discord credential, Bybit credential, bridge secret, server path or account-specific runtime state belongs in the public repository. Only aggregate research findings and deterministic source/tests should be committed.
