#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

cd "$DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -c constraints.txt -r requirements.txt

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
