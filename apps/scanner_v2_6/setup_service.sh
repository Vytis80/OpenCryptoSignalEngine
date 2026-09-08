#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="bybit-crypto-scanner.service"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

cd "$PROJECT_DIR"
.venv/bin/python preflight.py --live

UNIT_TMP="$(mktemp)"
trap 'rm -f -- "$UNIT_TMP"' EXIT
sed -e "s|@@USER@@|$RUN_USER|g" -e "s|@@GROUP@@|$RUN_GROUP|g" \
  -e "s|@@PROJECT_DIR@@|$PROJECT_DIR|g" systemd_service.txt >"$UNIT_TMP"

sudo install -m 644 "$UNIT_TMP" "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sleep 3
sudo systemctl status "$SERVICE_NAME" --no-pager -l
echo "Service installed. Verify Discord with /bybit_health before stopping the old Bybit VM."
