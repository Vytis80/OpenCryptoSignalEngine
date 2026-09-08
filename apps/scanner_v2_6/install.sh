#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$PROJECT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 missing. Install python3 and python3-venv first."
  exit 1
fi

if ! python3 -m venv .venv 2>/dev/null; then
  echo "python3-venv missing; installing it with apt."
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f "$ROOT_DIR/pyproject.toml" ]]; then
  echo "ERROR: repository root not found at $ROOT_DIR" >&2
  echo "Install Scanner V2.6 from a full OpenCryptoSignalEngine clone." >&2
  exit 1
fi
.venv/bin/python -m pip install -e "$ROOT_DIR"

install -d -m 700 data

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from the safe template. Import the another integration Discord values next."
fi
chmod 600 .env
chmod +x install.sh setup_service.sh restart_service.sh

.venv/bin/python self_test.py
echo "Install complete. Fill your own local Discord/bridge values in .env, then run: .venv/bin/python preflight.py --live"
