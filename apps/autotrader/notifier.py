from __future__ import annotations
import logging

log=logging.getLogger(__name__)

class Notifier:
    def __init__(self,bot,channel_id:int):
        self.bot=bot
        self.channel_id=channel_id
        self.shadow_view_factory=None

    def shadow_view(self,signal_id,symbol):
        if not self.shadow_view_factory:
            return None
        return self.shadow_view_factory(str(signal_id),symbol)

    async def send(self,text:str,view=None):
        if not self.bot or not self.channel_id:
            log.info("DISCORD: %s",text.replace("\n"," | "))
            return

        channel=self.bot.get_channel(self.channel_id)
        if channel is None:
            try:
                channel=await self.bot.fetch_channel(self.channel_id)
            except Exception:
                log.exception("Cannot resolve Discord channel %s",self.channel_id)
                return

        try:
            return await channel.send(text[:1900],view=view)
        except Exception:
            log.exception("Discord send failed")
