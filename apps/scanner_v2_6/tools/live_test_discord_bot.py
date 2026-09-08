#!/usr/bin/env python3
"""Explicit live probe: logs the shared Discord bot in once, then exits."""

import asyncio
import sys
from pathlib import Path

import discord

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import Config


async def main():
    cfg=Config()
    if not cfg.discord_bot_token:raise SystemExit("DISCORD_BOT_TOKEN is empty")
    client=discord.Client(intents=discord.Intents.none())
    @client.event
    async def on_ready():
        print("Bot login OK:",client.user)
        await client.close()
    await client.start(cfg.discord_bot_token,reconnect=False)


asyncio.run(main())
