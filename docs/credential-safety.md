# Credential safety

This repository is designed so operational secrets remain outside Git.

Never commit:

- `.env` or `.env.*` runtime files
- Bybit API keys or API secrets
- Discord bot tokens or webhook URLs
- bridge/HMAC shared secrets
- SSH keys or cloud credentials
- account-specific databases, logs, order history, or runtime state

Only `.env.example` files with empty/placeholder values are versioned. CI runs a secret scan in addition to the repository `.gitignore`.

If a credential has ever been copied into an archive, backup file, shell history, chat, or Git commit, rotate it at the provider. Removing the file later is not sufficient to make the old credential safe.
