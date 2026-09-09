# V2.6 AI Judge V1

Optional observational second-opinion layer for confirmed Scanner V2.6 `EXECUTE` signals using Groq's OpenAI-compatible API and `openai/gpt-oss-120b` by default.

## Safety contract

The AI Judge is **shadow-only**. It cannot create, veto, delay, resize or modify an AutoTrader trade. Scanner strategy, Entry, SL, TP, leverage, size and management remain deterministic and authoritative.

For a new EXECUTE signal the scanner persists the signal and spawns the signed Demo AutoTrader bridge task **before** awaiting the AI request. AI latency or failure therefore cannot block the execution path. Discord delivery may wait up to the configured AI timeout so the observational verdict can be shown on the same EXECUTE card.

The AI module has no Bybit order or bridge access. Its output is limited to `APPROVE`/`REJECT`, verdict confidence, setup-quality grade, risk label, concise summary, strengths and risks. Confidence means confidence in the review verdict, not probability of profit.

## Configuration

Public examples are opt-in and contain placeholders only:

```text
AI_JUDGE_ENABLED=false
GROQ_API_KEY=your_groq_api_key
AI_JUDGE_MODEL=openai/gpt-oss-120b
AI_JUDGE_BASE_URL=https://api.groq.com/openai/v1
AI_JUDGE_TIMEOUT_SEC=5
AI_JUDGE_REASONING_EFFORT=low
```

Enabling this feature sends structured signal evidence to the configured external AI provider. Never commit a real API key.

## Storage and Discord

Judgements are stored in the scanner SQLite `ai_judgements` table for later comparison with real signal outcomes. Runtime DB contents are not part of the repository.

Discord inspection commands:

- `/byscan_ai_last`
- `/byscan_ai_stats`

V2.6 AI samples must be evaluated separately from V2.5 because their scanner evidence and prompt contracts differ.

## CI boundary

Repository CI tests the structured contract, missing-key path, persistence and the non-blocking bridge invariant without contacting Groq. Live API checks belong on the deployment host with the operator's own local credentials.
