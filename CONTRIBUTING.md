# Contributing to OpenCryptoSignalEngine

Contributions, bug reports and feature suggestions are welcome.

## Before contributing

Please make sure that:

- No API keys, tokens, credentials or other secrets are included
- Execution-related changes are tested in paper or demo environments
- Changes are focused and clearly documented
- Trading logic changes include appropriate validation or tests
- Existing functionality is not intentionally broken without explanation

## Pull requests

When opening a pull request:

1. Clearly describe what was changed
2. Explain why the change is needed
3. Mention any affected modules or trading logic
4. Include testing details where relevant
5. Keep unrelated changes in separate pull requests

## Issues

When reporting a bug, please include:

- A clear description of the problem
- Steps to reproduce it
- Expected behavior
- Actual behavior
- Relevant logs or error messages
- Python version and environment details when applicable

Do not include private API credentials or sensitive account information in issues.

## Development

OpenCryptoSignalEngine is currently focused on the Bybit trading research and execution pipeline.

New features should remain modular and avoid unnecessary coupling between:

- Market data
- Signal generation
- Risk management
- Execution
- Backtesting
- Notifications
