#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
.venv/bin/python preflight.py
sudo systemctl restart bybit-crypto-scanner.service
sleep 3
sudo systemctl status bybit-crypto-scanner.service --no-pager -l
