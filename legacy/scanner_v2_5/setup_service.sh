#!/usr/bin/env bash
set -e
D="$(cd "$(dirname "$0")" && pwd)"
U="$(whoami)"
T="$(mktemp --suffix=.service)"
trap 'rm -f "$T"' EXIT
sed -e "s|@@USER@@|$U|g" -e "s|@@DIR@@|$D|g" \
  "$D/bybit-crypto-scanner.service.template" > "$T"
systemd-analyze verify "$T"
sudo install -m 0644 "$T" /etc/systemd/system/bybit-crypto-scanner.service
sudo mkdir -p /etc/systemd/system/bybit-crypto-scanner.service.d
printf '[Service]\nRestart=on-failure\nRestartSec=5\n' | \
  sudo tee /etc/systemd/system/bybit-crypto-scanner.service.d/99-audited-recovery.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable bybit-crypto-scanner
sudo systemctl restart bybit-crypto-scanner
sudo systemctl status bybit-crypto-scanner --no-pager -l
