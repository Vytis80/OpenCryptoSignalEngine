# Credential safety

This repository is designed so operational secrets remain outside Git.

Never commit:

- `.env` or `.env.*` runtime files
- Bybit API keys or API secrets
- Discord bot tokens or webhook URLs
- Groq or other external AI-provider API keys
- bridge/HMAC shared secrets
- SSH keys or cloud credentials
- account-specific databases, AI judgement/response databases, logs, order history, or runtime state
- source/runtime backup files that may preserve credentials or private deployment values

Only `.env.example` files with empty/placeholder values are versioned. CI runs a secret scan in addition to the repository `.gitignore`.

The optional AI Judge is disabled by default in public examples. When enabled, it creates outbound traffic to the configured provider and sends structured signal/setup evidence. Keep provider credentials in the ignored local `.env`; keep returned AI/runtime research data in local SQLite state rather than Git.

If a credential has ever been copied into an archive, backup file, shell history, chat, or Git commit, rotate it at the provider. Removing the file later is not sufficient to make the old credential safe.
