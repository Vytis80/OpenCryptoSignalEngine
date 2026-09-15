# Scanner V2.5 — AI Judge V2 Blind SHADOW

This document records the LIVE V2 Blind research contract layered on top of the preserved V2.5 strategy family.

## Status

- prompt contract: `ai-judge-v2-blind-v25`
- provider/model family: Groq OpenAI-compatible API with `openai/gpt-oss-120b`
- mode: **SHADOW only**
- execution authority: **none**

AI must not decide whether the V2.5 strategy emits an `EXECUTE`, and must not change Entry, SL, TP, sizing, management or bridge behavior. V1 research history remains retained.

## Blind research outputs

V2 records separate research fields for later calibration:

- `edge_score` — 0–100;
- `risk_score` — 0–100;
- confidence;
- structured reason codes;
- eventual TP/SL/R outcome for analysis;
- V2.5 provider token usage remains tracked separately from V2.6 research.

The research dataset is kept separate from V2.6 because the two scanners expose different deterministic evidence and have different prompt contracts.

## Non-blocking invariant

The Demo AutoTrader bridge path remains ahead of any AI wait. AI timeout, provider failure or a `REJECT` cannot veto or mutate the trade.

## V2.5 TP-ladder safety hotfix

The preserved V2.5 strategy received one explicit LIVE safety fix after a root-cause audit found that obstacle caps could make TP1/TP2/TP3 non-monotonic. A final hard gate now requires:

- LONG: `entry < TP1 < TP2 < TP3`;
- SHORT: `entry > TP1 > TP2 > TP3`.

This is a malformed-order safety guard, not an AI-driven strategy change.

## 2026-09-14 audit decision

The first V2 Blind snapshot contained 100 V2.5 evaluations and 94 closed signals. Score-to-outcome rank correlations were weak, so AI remained SHADOW-only. Certain reason-code cohorts such as `WEAK_TRIGGER` and `HTF_CONFLICT` looked negative in that sample, but they were not promoted to hard gates.

See [`../../docs/research-status-2026-09-14.md`](../../docs/research-status-2026-09-14.md) for the measured snapshot and caveats.

## Public-source parity

This document records the confirmed LIVE contract, but the exact latest V2 Blind implementation must be imported from a fresh sanitized deployment snapshot before claiming exact source parity. Runtime DB rows, provider responses and account state must not be committed.
