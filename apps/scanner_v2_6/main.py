import asyncio,logging
from config import Config
from scanner import TradeScanner

async def discord_runner(scanner,cfg):
    if not cfg.discord_bot_enabled:
        logging.warning("DISCORD_BOT_ENABLED=false — slash commands disabled; webhook alerts remain active.")
        return
    if not cfg.discord_bot_token:
        logging.warning("DISCORD_BOT_TOKEN empty — scanner works, slash commands disabled.")
        return
    try:
        from discord_reconnect import install_discord_reconnect_cap
        from discord_control import TradeDiscord
        cap=install_discord_reconnect_cap(cfg.discord_reconnect_cap_sec)
        logging.info("Discord Gateway reconnect delay capped at %.0fs",cap)
        bot=TradeDiscord(scanner,cfg)
        await bot.start(cfg.discord_bot_token,reconnect=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Discord control failed; trade scanner continues.")

async def main():
    cfg=Config()
    logging.basicConfig(level=getattr(logging,cfg.log_level,logging.INFO),
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    if cfg.require_discord_webhook and not cfg.discord_webhook_url:
        raise RuntimeError("REQUIRE_DISCORD_WEBHOOK=true but DISCORD_WEBHOOK_URL is empty")
    if cfg.discord_bot_enabled and cfg.discord_bot_token:
        if not cfg.discord_guild_id or not cfg.discord_control_channel_id:
            raise RuntimeError("Discord bot enabled but DISCORD_GUILD_ID or DISCORD_CONTROL_CHANNEL_ID is empty")
        if cfg.discord_command_sync_mode not in {"merge","replace","off"}:
            raise RuntimeError("DISCORD_COMMAND_SYNC_MODE must be merge, replace or off")
    scanner=TradeScanner(cfg)
    run=asyncio.create_task(scanner.run(),name="scanner")
    await asyncio.sleep(2)
    discord=asyncio.create_task(discord_runner(scanner,cfg),name="discord")
    try:
        await run
    finally:
        discord.cancel()
        await asyncio.gather(discord,return_exceptions=True)

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:pass
