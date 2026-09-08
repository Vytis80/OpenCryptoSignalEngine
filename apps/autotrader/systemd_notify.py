from __future__ import annotations

import asyncio
import os
import socket


def notify(message: str) -> bool:
    """Send an sd_notify datagram without adding a runtime dependency."""
    address = os.getenv("NOTIFY_SOCKET", "")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(message.encode())
        return True
    finally:
        sock.close()


async def watchdog_loop():
    usec = int(os.getenv("WATCHDOG_USEC", "0") or 0)
    if usec <= 0:
        return
    interval = max(1.0, usec / 2_000_000)
    while True:
        await asyncio.sleep(interval)
        if not notify("WATCHDOG=1"):
            raise RuntimeError("systemd watchdog notification failed")
