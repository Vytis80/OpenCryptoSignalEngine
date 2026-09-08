# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in OpenCryptoSignalEngine, please do not disclose sensitive details publicly in a GitHub issue.

Instead, report the problem privately to the project maintainer.

When reporting a vulnerability, include:

- A clear description of the issue
- Steps to reproduce it
- Affected component or module
- Potential impact
- Suggested mitigation, if known

## Sensitive information

Never include the following in issues, pull requests, commits or logs:

- API keys
- API secrets
- Exchange credentials
- Discord bot tokens
- Webhook URLs
- Private account information
- SSH keys
- `.env` contents

## Trading and execution safety

Execution-related changes should be tested using paper or demo environments before any live deployment.

Security fixes that affect authentication, exchange connectivity, order execution or credential handling should receive additional review before release.
