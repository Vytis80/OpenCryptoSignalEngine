# V2.6.0-rc2 release notes

## Signal core

- V2.5 remains frozen as the comparison baseline; production `analyze` uses the V2.6 signal core.
- 4H regime and at least two closed 1M confirmations are hard gates.
- 5M triggers require a confirmed breakout/breakdown retest, EMA reaction, or liquidity sweep/reclaim.
- 4H/1H/15M direction, spread, ATR range, last-5M candle size, anti-chase and rejection gates are non-bypassable.
- Structural SL is checked in both ATR and percentage terms; impractically wide setups are rejected instead of being emitted with poor levels.
- The nearest 15M/1H support or resistance is used as the obstacle; safe room must satisfy the configured R threshold.
- Targets remain exact 1R / 2R / 3R and EXECUTE/POTENTIAL thresholds remain 82 / 70.
- `Setup Score` and `Historical edge` are separate concepts. Historical edge is evaluated for the same setup family, direction and core version using the configured TP fractions and costs.
- Bybit 1M replay is no-lookahead, V2.5/V2.6 A/B comparison is preserved, and promotion is fail-closed.
- SHADOW remains observational and does not mutate V2.6 EXECUTE, Entry, SL or TP decisions.

## Runtime and reliability

- 42 deep-analysis slots per cycle, with 20 reserved for least-recently-scanned fair rotation.
- Coverage advances only after a successful full analysis; failures remain eligible for fast retry.
- ACTIVE freshness guard prevents stale price/context data from triggering invalidation or management decisions.
- Bybit WebSocket watchdog, per-symbol freshness tracking and accelerated REST fallback.
- Bybit HTTP 403 uses a 10-minute fail-fast cooldown; 429/5xx and webhook delivery have retry/telemetry handling.
- One-shot `DATA STALE` and `DATA RECOVERED` notifications.
- Post-TP structural invalidation closes the remaining signal lifecycle instead of leaving a permanent protect state.
- Discord Gateway reconnect delay is capped at 60 seconds and long command responses are chunked safely.
- Webhook alert delivery retries and failure counters are exposed through health/status reporting.
- `Confidence` wording was replaced with `Setup Score`; the scanner does not present the score as a probability.

## RC2 delta

- V2.6 Discord commands use the dedicated `byscan_*` namespace instead of the older `bybit_*` namespace, avoiding collisions with the frozen V2.5 integration.
- Shared Discord command merge/audit restores only missing `byscan_*` commands and does not bulk-delete unrelated commands owned by the same application.
- Replay validation skips symbols that are no longer valid/available in the current Bybit instrument universe instead of treating those markets as strategy failures.
- Runtime version reporting is aligned to `2.6.0-rc2`.

## 2026-09-09 AI research sidecar sync

- Optional `openai/gpt-oss-120b` AI Judge support was synced from the LIVE scanner through a Groq-compatible endpoint.
- AI Judge is disabled by default in public configuration and requires a user-owned local provider credential when enabled.
- The sidecar is EXECUTE-only and observational: verdicts never change the scanner decision, Entry, SL, TP, size or management.
- The confirmed signal is persisted and the optional Demo AutoTrader bridge task is queued before awaiting AI, preventing provider latency/failure from becoming an execution gate.
- AI judgement/latency research is stored separately in SQLite and can be inspected through `/byscan_ai_last` and `/byscan_ai_stats`.
- Public CI uses network-free contract, persistence and non-blocking checks; live provider calls are intentionally excluded.

See `AI_JUDGE_V1.md` for the external-provider/privacy boundary.

## Release gate

- Component offline tests plus credential-free AI sidecar checks.
- Python compile checks.
- Shell syntax checks where applicable.
- V2.6 strategy hash, frozen V2.5 baseline integrity checks and secret scanning.
- Public Bybit/live-AI preflight is intentionally executed only on deployment hosts; public CI remains credential-free.
- Promotion remains fail-closed until replay validation returns PASS with a sufficient sample.
