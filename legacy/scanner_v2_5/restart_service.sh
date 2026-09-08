#!/usr/bin/env bash
set -e
sudo systemctl restart bybit-crypto-scanner
sleep 2
sudo systemctl status bybit-crypto-scanner --no-pager -l
