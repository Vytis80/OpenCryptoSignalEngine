from discord.backoff import ExponentialBackoff
from discord_reconnect import install_discord_reconnect_cap

install_discord_reconnect_cap(0.01)
backoff=ExponentialBackoff()
assert all(0<=backoff.delay()<=0.01 for _ in range(20))
install_discord_reconnect_cap(0.02)
assert ExponentialBackoff._bybit_v26_cap_seconds==0.02
try:
    install_discord_reconnect_cap(0)
    raise AssertionError("zero cap accepted")
except ValueError:
    pass
print("OK: discord.py jitter preserved with idempotent reconnect cap")
