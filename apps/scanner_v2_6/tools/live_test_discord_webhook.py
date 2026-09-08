#!/usr/bin/env python3
"""Explicit live probe: sends one clearly labelled Discord webhook message."""

import asyncio
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import Config


async def main():
    cfg=Config()
    if not cfg.discord_webhook_url:raise SystemExit("DISCORD_WEBHOOK_URL is empty")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            cfg.discord_webhook_url,
            json={"username":cfg.discord_username,"content":"✅ Bybit Scanner V2.6 webhook live test OK"},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as response:
            print("Discord webhook status:",response.status)
            if response.status>=300:raise SystemExit(1)


asyncio.run(main())
