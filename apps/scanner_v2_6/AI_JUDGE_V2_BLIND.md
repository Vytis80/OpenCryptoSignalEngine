# Scanner V2.6 — AI Judge V2 Blind SHADOW

LIVE research contract introduced after the original V1 AI Judge evaluation.

## Status

- prompt contract: `ai-judge-v2-blind-v26`
- provider/model family: Groq OpenAI-compatible API with `openai/gpt-oss-120b`
- mode: **SHADOW only**
- execution authority: **none**

The V2.6 scanner remains the deterministic source of signal intent. AI cannot create, veto, delay, resize or mutate an `EXECUTE`, Entry, SL, TP, management action, leverage or AutoTrader order.

## Blind research outputs

V2 Blind records research features separately from scanner decisions:

- `edge_score` — 0–100 research score;
- `risk_score` — 0–100 research score;
- confidence;
- structured reason codes;
- eventual signal outcome for calibration/analysis.

V1 history is retained rather than overwritten so V1 and V2 research can be compared longitudinally.

## Non-blocking invariant

The scanner/bridge execution path remains authoritative and must be queued before any AI wait. Provider latency, timeout, malformed output or missing credentials must not suppress or alter the confirmed trade path.

## 2026-09-14 audit decision

The first V2 Blind LIVE audit did not show enough predictive separation to justify a gate. V2.6 had 23 evaluations with 23 closed signals in that snapshot; rank correlations between the AI scores and realized R were close to zero. AI therefore remains SHADOW-only.

See [`../../docs/research-status-2026-09-14.md`](../../docs/research-status-2026-09-14.md) for the point-in-time research numbers and the decision record.

## Public-source parity

This document records the confirmed LIVE contract. The exact latest V2 Blind implementation must still be imported from a fresh sanitized deployment source snapshot before the public repository can claim exact source parity with LIVE. The original V1 source remains in Git history and should not be rewritten to pretend parity.

## Security

Do not commit Groq/API keys, `.env`, runtime AI responses, account databases, Discord credentials, bridge secrets or deployment-specific state. Public CI must remain credential-free and network-free for AI-provider tests.
