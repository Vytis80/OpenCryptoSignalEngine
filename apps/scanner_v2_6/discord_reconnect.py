"""Bound discord.py Gateway reconnect delays without replacing its retry loop."""


def install_discord_reconnect_cap(cap_seconds=60.0):
    from discord.backoff import ExponentialBackoff

    cap=float(cap_seconds)
    if cap<=0:
        raise ValueError("DISCORD_RECONNECT_CAP_SEC must be greater than zero")

    # Keep the original discord.py jitter/backoff calculation and only cap the
    # final delay. Class attributes make repeated installation idempotent and
    # allow a changed config value to take effect.
    if not hasattr(ExponentialBackoff,"_bybit_v26_original_delay"):
        ExponentialBackoff._bybit_v26_original_delay=ExponentialBackoff.delay

        def capped_delay(self):
            delay=ExponentialBackoff._bybit_v26_original_delay(self)
            return min(delay,float(ExponentialBackoff._bybit_v26_cap_seconds))

        ExponentialBackoff.delay=capped_delay

    ExponentialBackoff._bybit_v26_cap_seconds=cap
    return cap
