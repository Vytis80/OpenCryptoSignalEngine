#!/usr/bin/env python3
"""Secret-safe configuration and optional live Bybit readiness check."""

import argparse
import asyncio
import hashlib
import os
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_STRATEGY_SHA256="3301f5195f4b6b5b3faead34710c23f81103d67a7b224238ed064959811ea3c6"
ROOT=Path(__file__).resolve().parent


def fail(message):
    print(f"FAIL: {message}")
    return False


def config_checks():
    env_path=ROOT/".env"
    if not env_path.is_file():
        fail(".env missing; run ./install.sh and import the Discord settings")
        return False,None

    os.chdir(ROOT)
    from config import Config
    cfg=Config()
    ok=True

    digest=hashlib.sha256((ROOT/"strategy.py").read_bytes()).hexdigest()
    if digest!=EXPECTED_STRATEGY_SHA256:
        ok=fail(f"strategy.py hash changed: {digest}") and ok
    if cfg.execute_score!=82 or cfg.potential_score!=70:
        ok=fail("EXECUTE_SCORE/POTENTIAL_SCORE must remain 82/70") and ok
    if cfg.min_micro_confirmations<2:
        ok=fail("MIN_MICRO_CONFIRMATIONS must be at least 2") and ok
    if not 0<cfg.min_atr5_pct<cfg.max_atr5_pct:
        ok=fail("5m ATR percentage range is invalid") and ok
    if not 0<cfg.min_stop_atr<cfg.max_stop_atr:
        ok=fail("structural SL ATR range is invalid") and ok
    if not 0<cfg.min_stop_pct<cfg.max_stop_pct:
        ok=fail("structural SL percentage range is invalid") and ok
    if abs(cfg.edge_tp1_fraction+cfg.edge_tp2_fraction+cfg.edge_tp3_fraction-1.0)>1e-6:
        ok=fail("EDGE TP fractions must total 1.00") and ok
    if cfg.deep_candidates_per_scan<=0:
        ok=fail("DEEP_CANDIDATES_PER_SCAN must be positive") and ok
    if not 0<cfg.rotating_candidates<=cfg.deep_candidates_per_scan:
        ok=fail("ROTATING_CANDIDATES must be between 1 and DEEP_CANDIDATES_PER_SCAN") and ok
    if cfg.max_deep_scan_age_sec<=cfg.scan_interval_sec:
        ok=fail("MAX_DEEP_SCAN_AGE_SEC must exceed SCAN_INTERVAL_SEC") and ok
    if cfg.market_data_stale_sec<=0 or cfg.active_context_stale_sec<=0:
        ok=fail("stale-data limits must be positive") and ok
    if cfg.active_rest_fallback_sec<=0 or cfg.discord_reconnect_cap_sec<=0:
        ok=fail("fallback/reconnect delays must be positive") and ok
    if cfg.discord_command_audit_sec<30:
        ok=fail("DISCORD_COMMAND_AUDIT_SEC must be at least 30 seconds") and ok

    rest=urlparse(cfg.rest_url);ws=urlparse(cfg.bybit_ws_public_url)
    if rest.scheme!="https" or not rest.netloc:
        ok=fail("BYBIT_REST_URL must be a valid HTTPS URL") and ok
    if ws.scheme!="wss" or not ws.netloc:
        ok=fail("BYBIT_WS_PUBLIC_URL must be a valid WSS URL") and ok

    if cfg.require_discord_webhook and not cfg.discord_webhook_url:
        ok=fail("DISCORD_WEBHOOK_URL is required") and ok
    if cfg.discord_bot_enabled:
        if not cfg.discord_bot_token:
            ok=fail("DISCORD_BOT_TOKEN is required while DISCORD_BOT_ENABLED=true") and ok
        if not cfg.discord_guild_id:
            ok=fail("DISCORD_GUILD_ID is required") and ok
        if not cfg.discord_control_channel_id:
            ok=fail("DISCORD_CONTROL_CHANNEL_ID is required") and ok
    if cfg.discord_command_sync_mode not in {"merge","replace","off"}:
        ok=fail("DISCORD_COMMAND_SYNC_MODE must be merge, replace or off") and ok
    if cfg.discord_command_sync_mode=="replace":
        ok=fail("replace mode is unsafe for the shared Discord application; use merge") and ok

    bridge_url=(os.getenv("DEMO_BRIDGE_URL") or "").strip()
    bridge_secret=(os.getenv("DEMO_BRIDGE_SECRET") or "").strip()
    if bool(bridge_url)!=bool(bridge_secret):
        ok=fail("DEMO_BRIDGE_URL and DEMO_BRIDGE_SECRET must be set together") and ok
    if bridge_url and urlparse(bridge_url).scheme not in {"https","http"}:
        ok=fail("DEMO_BRIDGE_URL must be HTTP(S)") and ok

    mode=stat.S_IMODE(env_path.stat().st_mode)
    if mode&0o077:
        print(f"WARN: .env permissions are {mode:o}; run chmod 600 .env")

    if ok:
        print("OK: V2.6 signal core hash, hard gates, Discord targets and safety limits")
        print(f"OK: guild={cfg.discord_guild_id} channel={cfg.discord_control_channel_id} sync={cfg.discord_command_sync_mode}")
        print(f"OK: deep={cfg.deep_candidates_per_scan}/cycle fair={cfg.rotating_candidates}/cycle max_age={cfg.max_deep_scan_age_sec:.0f}s")
        print("OK: secrets present but intentionally not displayed")
    return ok,cfg


async def live_check(cfg):
    import aiohttp
    from bybit import Bybit

    async with aiohttp.ClientSession(headers={"User-Agent":"Bybit-V2.6-Preflight/1.0"}) as session:
        api=Bybit(cfg,session)
        result=await api.get("/v5/market/time",retries=1)
        if not result:
            raise RuntimeError("empty Bybit market-time response")
        server_time=float(result.get("timeSecond") or 0)
        if not server_time:
            raise RuntimeError("Bybit market-time response has no timeSecond")
        clock_drift=abs(time.time()-server_time)
        if clock_drift>5:
            raise RuntimeError(f"VM clock differs from Bybit by {clock_drift:.1f}s; fix NTP first")
        live=await api.live_perpetuals()
        if not live:
            raise RuntimeError("no live Bybit USDT linear perpetuals returned")
        print(f"OK: live Bybit REST reachable; clock drift {clock_drift:.2f}s; {len(live)} USDT linear perpetual markets")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--live",action="store_true",help="also call public Bybit REST; sends nothing to Discord")
    args=parser.parse_args()
    ok,cfg=config_checks()
    if not ok:return 1
    if args.live:
        try:asyncio.run(live_check(cfg))
        except Exception as exc:
            print(f"FAIL: live Bybit check: {type(exc).__name__}: {exc}")
            return 1
    print("READY: preflight passed")
    return 0


if __name__=="__main__":
    sys.exit(main())
