from discord.backoff import ExponentialBackoff

_CAP_SECONDS = 60

if not getattr(ExponentialBackoff, "_crypto_bot_reconnect_capped", False):
    _original_delay = ExponentialBackoff.delay

    def _capped_delay(self):
        return min(_original_delay(self), _CAP_SECONDS)

    ExponentialBackoff.delay = _capped_delay
    ExponentialBackoff._crypto_bot_reconnect_capped = True
    ExponentialBackoff._crypto_bot_reconnect_cap_seconds = _CAP_SECONDS
