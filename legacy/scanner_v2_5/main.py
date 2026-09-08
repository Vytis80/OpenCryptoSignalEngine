import discord_reconnect_patch
import asyncio,logging,os,time
from config import Config
from scanner import TradeScanner
from systemd_notify import notify

async def discord_runner(scanner,cfg):
    if not cfg.discord_bot_token:
        logging.warning("DISCORD_BOT_TOKEN empty — scanner works, slash commands disabled.")
        return
    delay=2.0
    while True:
        try:
            from discord_control import TradeDiscord
            bot=TradeDiscord(scanner,cfg)
            await bot.start(cfg.discord_bot_token)
            logging.warning("Discord control stopped; reconnecting in %.0fs",delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Discord control failed; scanner continues and will reconnect.")
        await asyncio.sleep(delay);delay=min(60.0,delay*2.0)

async def watchdog_runner(scanner,cfg):
    usec=int(os.getenv("WATCHDOG_USEC","0") or 0)
    if usec<=0:return
    interval=max(1.0,min(10.0,usec/3_000_000.0))
    while True:
        await asyncio.sleep(interval)
        h=scanner.health()
        startup_grace=time.time()-scanner.started_at<120
        healthy_scan=startup_grace or h["last_scan_age"]<=max(120,cfg.scan_interval_sec*4)
        if healthy_scan:notify("WATCHDOG=1")

async def main():
    cfg=Config()
    logging.basicConfig(level=getattr(logging,cfg.log_level,logging.INFO),
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    scanner=TradeScanner(cfg)
    run=asyncio.create_task(scanner.run(),name="scanner")
    ready=asyncio.create_task(scanner.ready_event.wait(),name="scanner-ready")
    done,_=await asyncio.wait({run,ready},timeout=120,return_when=asyncio.FIRST_COMPLETED)
    if run in done:
        ready.cancel()
        await run
    if ready not in done:
        ready.cancel()
        run.cancel()
        await asyncio.gather(ready,run,return_exceptions=True)
        raise TimeoutError("Scanner initialization did not complete within 120s")
    notify("READY=1\nSTATUS=Scanner initialized")
    discord=asyncio.create_task(discord_runner(scanner,cfg),name="discord")
    watchdog=asyncio.create_task(watchdog_runner(scanner,cfg),name="systemd-watchdog")
    try:
        await run
    finally:
        notify("STOPPING=1")
        discord.cancel();watchdog.cancel()
        await asyncio.gather(discord,watchdog,return_exceptions=True)

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:pass
