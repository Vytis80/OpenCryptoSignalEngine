#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "ERROR: existing .env is required; this audited patch never creates or replaces secret configuration." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip
fi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
chmod 600 .env
echo
echo "Installed Bybit 5m Crypto Scanner V2.5 SAFE."
echo "Run: .venv/bin/python self_test.py"
echo "Run: .venv/bin/python test_bybit.py"
