from __future__ import annotations

import os
import socket


def notify(message: str) -> bool:
    address=os.getenv("NOTIFY_SOCKET","")
    if not address:return False
    if address.startswith("@"):address="\0"+address[1:]
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    try:
        sock.connect(address);sock.sendall(message.encode());return True
    except OSError:
        return False
    finally:
        sock.close()
