# Security Policy

## Reporting a vulnerability

Please do not disclose sensitive security details, credentials, tokens, private account data or exploitable secrets in a public GitHub issue.

Use a private security-reporting channel provided by the repository owner when available. If private reporting is not available, open a minimal issue that does **not** include exploit details or secrets and ask the maintainer for a private contact path.

## Credential policy

The repository must never contain real:

- Bybit API keys or API secrets
- Discord bot tokens or webhook URLs
- bridge/HMAC secrets
- SSH/private keys
- cloud credentials
- `.env` files or secret-bearing backup copies
- account-specific databases, order history or private logs

Only empty/placeholder `.env.example` files are allowed in Git.

If a credential has ever been present in an archive, backup, terminal history, chat, CI log, or Git commit, **rotate it at the provider**. Removing the old text alone is not sufficient.

## Execution safety

Execution-related changes must be tested in paper or Bybit Demo environments before any live deployment. Changes affecting authentication, order placement, protective stops, leverage, margin handling, bridge verification or position reconciliation deserve additional review.

## Automated checks

Pull requests and pushes run CI plus a secret-scanning workflow. These checks reduce risk but do not replace human review.
