# BYBIT Demo Auto-Trader V1.5.4 — shared risk + bridge contract

Purpose: execute **only** `EXECUTE` signals produced by the already-running Bybit 5m Crypto Scanner. This package does not scan markets and does not generate a second strategy.

## Safety architecture

- Bybit connector is hard-wired to `demo=True`, which resolves to `https://api-demo.bybit.com`.
- Startup refuses an unexpected Bybit endpoint.
- Duplicate `signal_id` is idempotent.
- One bot-managed position per symbol.
- Maximum concurrent positions.
- Position size starts from account equity + scanner SL distance, but the explicit minimum-size policy can override the percentage risk target.
- **Margin mode is enforced as ISOLATED_MARGIN.**
- Bybit's exchange-side **Auto Add Margin remains OFF** so it cannot pull an unlimited amount from the wallet.
- **Smart Margin Assist is ON by default:** the bot reads Bybit's real isolated `liqPrice` and may manually add bounded margin if liquidation would be too close to, or before, the scanner SL.
- Default liquidation safety buffer: liquidation must sit at least **20% of the entry→SL distance beyond SL**.
- Default per-trade Smart Margin cap: up to **+100% of the position's initial isolated margin**, additionally bounded by available wallet/caps. If that still cannot make the SL liquidation-safe, the failsafe closes the trade.
- **Leverage target is 10x.** If an instrument cannot support 10x, the bot selects that instrument's highest valid leverage at or below 10x instead of skipping the signal.
- The selected leverage is aligned to Bybit's `minLeverage`, `maxLeverage` and `leverageStep`, submitted before entry and stored with the trade.
- **Minimum isolated margin per opened trade is 100 USDT**, therefore the minimum position notional is **100 USDT × selected leverage** (1000 USDT at 10x, 500 USDT at 5x).
- Margin/notional caps still prevent one trade from consuming the whole demo account; if the configured caps cannot support the 100 USDT minimum margin, the signal is skipped.
- Entry-window validation prevents chasing a signal that has already moved away.
- In `ALL_EXECUTE` mode every final scanner `EXECUTE` is eligible regardless of SHADOW. SHADOW remains recorded for analysis; it no longer acts as an execution gate.
- Scanner SMART metadata is stored with each trade but never blocks an `EXECUTE`.
- A real-time SMART position observer measures actual Bybit Demo entry/mark progress, maximum/minimum R and giveback. Its `HOLD / WEAKENING / PROTECT_CANDIDATE / TRAIL_CANDIDATE / EXIT_CANDIDATE` output is diagnostic only: it cannot submit, amend or cancel an order and cannot move SL/TP or close a position.
- An eligible `EXECUTE` outside its exact scanner entry zone is persisted and retried automatically until it enters the zone or expires.
- The initial protective SL is attached to the entry request, then verified from the live position before TP setup. If protection/margin/TP setup fails, the bot confirms the failsafe flatten and retains a recoverable DB state until fills are complete.
- TP1/TP2/TP3 are real reduce-only conditional orders.
- TP1 full fill moves the verified full-position SL to the actual average entry.
- TP2 full fill moves the verified full-position SL to TP1. A partial TP2 fill cannot trigger it, and the monotonic guard never permits a stricter SL to be loosened.
- Automatic TP1/TP2 protection targets are derived from the shared exchange-independent risk lifecycle.
- TP1/TP2 protection state and retries are stored in SQLite, so a failed update is retried after restart.
- Source management can move SL or force an invalidation/close.
- HMAC-signed source bridge uses the shared protocol-v1 transport/validation contract from `open_crypto_signal_engine.protocol`.
- Existing v1 clients without `X-Bridge-Version` remain accepted; new clients send `X-Bridge-Version: 1`.
- State-changing Discord commands/buttons are fail-closed and require an explicit `DISCORD_ADMIN_USER_IDS` allow-list. Read-only commands remain available.
- Management events require both the exact `signal_id` and a durable unique `event_id`; delayed symbol-only events are rejected.

## Default execution

- Risk target: 1% of demo equity per signal.
- Margin mode: **Isolated, enforced account-wide for Bybit UTA 2.0**.
- Leverage: **10x target; instrument maximum fallback when 10x is unavailable**.
- Minimum isolated margin: **100 USDT**.
- Minimum notional: **100 USDT × selected leverage**.
- Smart Margin: **bounded manual top-up only when liquidation safety requires it**; it does not widen the scanner SL or rescue an invalid trade.
- If the selected-leverage minimum notional produces more than the configured 1% SL risk, the minimum-position rule takes priority and the actual risk is shown in Discord.
- Execution mode: **ALL_EXECUTE** when configured with `EXECUTION_MODE=ALL_EXECUTE`; SHADOW is audit-only.
- Max positions: **20** when configured with `EXECUTION_MODE=ALL_EXECUTE`.
- TP sizing: 40% / 30% / 30%.
- TP2 protection: move the remaining 30% position SL to TP1 after the complete planned TP2 slice fills.
- SL trigger: MarkPrice.
- TP trigger: LastPrice.

These are execution/risk settings only. The trade direction, entry, SL, TP1, TP2, TP3, quality and setup are taken from the existing signal bot.

## Install on the host

Use a **full OpenCryptoSignalEngine repository clone** because the AutoTrader venv installs the shared risk/protocol package from the repository root.

```bash
sudo apt update
sudo apt install -y python3 python3-venv unzip
cd apps/autotrader
./install.sh
nano .env
```

Create a Demo Trading API key in Bybit while switched to **Demo Trading**. Do not paste a production key into this project.

Generate the bridge secret:

```bash
openssl rand -hex 32
```

Then start:

```bash
sudo systemctl start bybit-demo-autotrader
systemctl status bybit-demo-autotrader --no-pager -l
journalctl -u bybit-demo-autotrader -n 50 --no-pager
```

Health check on the host:

```bash
curl http://127.0.0.1:8787/health
```

Expected fields include:

```json
{"ok":true,"service":"BYBIT_Demo_AutoTrader_V1.5.4","demo":true,"bridge_protocol":"1","smart_position_shadow":true,"tp2_lock_sl_to_tp1":true,"leverage_target":10,"leverage_fallback":"instrument_max"}
```

See `../../docs/bridge-protocol.md` for the signed wire contract and compatibility rules.

## Firewall

Allow the bridge port only from the scanner host/network that needs it. Do **not** open port 8787 to the whole internet.

## Scanner integration

The active repository Scanner V2.6 already uses the shared protocol package in `apps/scanner_v2_6/bridge_client.py`.

`source_bridge/bridge_client.py` remains a standalone v1 compatibility helper for integrating an external/older scanner that does not install the repository package. See `source_bridge/INTEGRATION.md` before using that path.

## Discord commands

- `/demo_status`
- `/demo_positions`
- `/demo_stats days:7`
- `/demo_recent`
- `/demo_smart`
- `/demo_smart_stats`
- `/demo_pause`
- `/demo_resume`
- `/demo_close SYMBOL`
- `/demo_help`

`/demo_stats` uses actual Bybit demo fills stored locally, so it reports net USDT PnL and R rather than the signal scanner's old `final-leg R` approximation.

Before enabling Discord mutations, set `DISCORD_ADMIN_USER_IDS` to the comma-separated numeric Discord user IDs allowed to approve, pause/resume, add margin, close, or use the emergency stop. If it is empty, those actions remain disabled by design.
