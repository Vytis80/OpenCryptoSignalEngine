# V2.5 AI Judge

The frozen V2.5.1 strategy baseline can optionally run an observational GPT-OSS AI Judge after a confirmed `EXECUTE` signal. This adds research telemetry only; it does not change the preserved V2.5 strategy.

## Invariant

V2.5 still decides EXECUTE, Entry, SL, TP and management without AI. The Demo AutoTrader bridge is queued before waiting for AI, so AI latency/failure cannot veto or alter the trade. Legacy SHADOW and SMART remain additional evidence only.

The default provider configuration uses Groq's OpenAI-compatible API with `openai/gpt-oss-120b`, low reasoning effort and a five-second timeout. The public `.env.example` keeps AI disabled until the operator explicitly opts in and supplies a local API key.

## Stored research data

Each result is stored in the V2.5 scanner's local `ai_judgements` table with verdict, confidence, quality, risk, summary, latency and Groq token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`). Runtime databases are never committed.

Discord commands:

- `/bybit_ai_last`
- `/bybit_ai_stats`
- `/bybit_ai_usage`

V2.5 and V2.6 AI samples must be evaluated separately. A single successful API call is only a connectivity/smoke result, not evidence of predictive edge.

## Privacy and cost

When explicitly enabled, structured signal evidence is sent to the configured external AI provider. Keep `GROQ_API_KEY` local, review the provider's terms/costs, and do not send account secrets or private runtime state.

CI remains credential-free and network-free for this feature.
