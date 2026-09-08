from __future__ import annotations
import discord_reconnect_patch

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv

from bridge_server import BridgeServer
from bybit_demo import BybitDemo
from config import Config
from discord_control import DiscordControl
from lifecycle_executor import LifecycleDemoExecutor
from notifier import Notifier
from storage import Storage
from systemd_notify import notify as systemd_notify, watchdog_loop


async def amain():
    load_dotenv()
    cfg = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("main")

    storage = Storage(cfg.db_path)
    await storage.init()
    bybit = BybitDemo(cfg.bybit_api_key, cfg.bybit_api_secret)
    await bybit.server_time()
    account = await bybit.ensure_isolated_margin()
    wallet = await bybit.wallet()
    log.info("Bybit Demo connected endpoint=%s margin_mode=%s equity=%.2f available=%.2f", bybit.endpoint, account.get("marginMode"), wallet["equity"], wallet["available"])

    # Build notifier first, then attach the Discord bot instance after DiscordControl is created.
    notifier = Notifier(None, cfg.discord_channel_id)
    executor = LifecycleDemoExecutor(cfg, bybit, storage, notifier)
    discord_control = DiscordControl(cfg, executor, bybit, storage)
    notifier.bot = discord_control.bot if cfg.discord_bot_token else None
    notifier.shadow_view_factory = discord_control.make_shadow_view

    bridge = BridgeServer(cfg, executor)
    await bridge.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(executor.reconcile_loop(), name="reconcile"),
        asyncio.create_task(executor.waiting_entry_loop(), name="wait-for-entry"),
    ]
    if cfg.discord_bot_token:
        tasks.append(asyncio.create_task(discord_control.start(), name="discord"))
    if int(os.getenv("WATCHDOG_USEC", "0") or 0) > 0:
        tasks.append(asyncio.create_task(watchdog_loop(), name="systemd-watchdog"))

    log.info("BYBIT Demo Auto-Trader V1.5.4 READY · auto=%s · execution_mode=%s · smart_position_shadow=%s · tp2_lock_sl_to_tp1=%s · risk_target=%.2f%% · leverage_target=%sx · leverage_fallback=instrument_max · min_margin=%.2f USDT · max_positions=%s", await executor.enabled(), cfg.execution_mode, cfg.smart_position_shadow_enabled, cfg.tp2_lock_sl_to_tp1_enabled, cfg.risk_pct, cfg.leverage, cfg.min_margin_usdt, cfg.max_open_positions)
    systemd_notify(f"READY=1\nSTATUS=Bybit Demo Auto-Trader V1.5.4 ready ({cfg.execution_mode}, leverage <= {cfg.leverage}x, TP2->TP1, max {cfg.max_open_positions})")
    stop_task = asyncio.create_task(stop.wait(), name="shutdown-signal")
    try:
        done, _ = await asyncio.wait(
            [stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task not in done:
            failed = next(t for t in done if t is not stop_task)
            if failed.cancelled():
                raise RuntimeError(f"Critical task {failed.get_name()} was cancelled")
            exc = failed.exception()
            if exc:
                raise RuntimeError(
                    f"Critical task {failed.get_name()} stopped"
                ) from exc
            raise RuntimeError(
                f"Critical task {failed.get_name()} exited unexpectedly"
            )
        log.info("Shutdown requested")
    finally:
        systemd_notify("STOPPING=1")
        executor._running = False
        await bridge.stop()
        await discord_control.close()
        stop_task.cancel()
        for t in tasks:
            t.cancel()
        await asyncio.gather(stop_task, *tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(amain())
