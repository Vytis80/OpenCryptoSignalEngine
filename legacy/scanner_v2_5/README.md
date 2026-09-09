# Bybit Scanner V2.5.1 — Frozen Reference

V2.5.1 is the frozen strategy reference baseline kept for regression comparison and signal replay. It is not the primary development target.

The strategy baseline remains frozen, but observation-only research sidecars may be added when they do not alter signal decisions. The 2026-09-09 GPT-OSS AI Judge sync follows that rule.

## Highlights

- Bybit USDT Linear Perpetual market data
- 1H / 15M / confirmed 5M strategy baseline
- EARLY and POTENTIAL setup lifecycle
- Dynamic entry validity
- Observation-only SMART signal and management labels
- Diagnostic anti-SL shadow layer
- Optional EXECUTE-only GPT-OSS 120B AI Judge through a Groq-compatible API
- AI verdicts do not change Entry, SL, TP1/TP2/TP3, size, management or the AutoTrader bridge decision
- AI verdict/outcome statistics are stored separately from V2.6 research data
- V2.5 records Groq prompt, completion and total-token usage for cost/usage research
- Discord AI inspection commands: `/bybit_ai_last`, `/bybit_ai_stats`, `/bybit_ai_usage`
- Durable bridge outbox for downstream demo execution
- SQLite signal and research state
- Discord alerts and command interface

SMART, anti-SL shadow and GPT-OSS AI Judge outputs are research metadata only. None of them suppresses a final EXECUTE or rewrites the preserved V2.5 trading levels.

## Install

```bash
cp .env.example .env
# Fill only your own local Discord values in .env.
# AI Judge is disabled by default; if explicitly enabled, add your own GROQ_API_KEY locally.
./install.sh
.venv/bin/python self_test.py
```

The committed `.env.example` contains placeholders only. Never commit `.env`, tokens, webhooks, IDs, API credentials, Groq keys, bridge secrets, database files, backups or runtime logs.

Live AI probes are not part of public CI. Credential-free contract, persistence, migration and non-blocking checks cover the public sidecar behavior.

## Status

**Frozen strategy baseline.** Strategy development belongs in `apps/scanner_v2_6`. Observation-only research additions in this directory must preserve V2.5 signal behavior and remain separately measurable.

See `AI_JUDGE_V25.md`, `VALIDATION_SMART_SHADOW_35D.md` and `CHANGELOG_SMART_SHADOW_20260903.md` for research notes.
