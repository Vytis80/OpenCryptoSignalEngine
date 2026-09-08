#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

cd "$DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -c constraints.txt -r requirements.txt

# The runtime uses the repository's exchange-independent risk lifecycle.
# Install the monorepo package into this component venv so the systemd service
# has the same tested TP1/TP2 protection contract as replay/backtesting.
if [[ ! -f "$ROOT/pyproject.toml" ]]; then
  echo "ERROR: repository root not found at $ROOT" >&2
  echo "Install AutoTrader from a full OpenCryptoSignalEngine clone." >&2
  exit 1
fi
.venv/bin/pip install -e "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created $DIR/.env - fill API/Discord/bridge secrets before starting."
fi

sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" bybit-demo-autotrader.service.template \
  | sudo tee /etc/systemd/system/bybit-demo-autotrader.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable bybit-demo-autotrader.service

echo
echo "Installed. Next: nano $DIR/.env"
echo "Then: sudo systemctl start bybit-demo-autotrader"
echo "Status: systemctl status bybit-demo-autotrader --no-pager -l"
