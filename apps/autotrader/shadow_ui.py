import discord

class ShadowDecisionView(discord.ui.View):
    def __init__(self,cfg,executor,signal_id,symbol):
        super().__init__(timeout=None)
        self.cfg=cfg
        self.executor=executor
        self.signal_id=str(signal_id)
        self.symbol=symbol
        self.approve.custom_id=f"shadow:approve:{self.signal_id}"
        self.wait.custom_id=f"shadow:wait:{self.signal_id}"
        self.reject.custom_id=f"shadow:reject:{self.signal_id}"

    def allowed(self,i):
        # Empty allow-list is read-only/fail-closed, never "allow everyone".
        return bool(self.cfg.discord_admin_user_ids) and i.user.id in self.cfg.discord_admin_user_ids

    def manual_mode(self):
        return getattr(self.cfg, "execution_mode", "SHADOW_MANUAL") == "SHADOW_MANUAL"

    @discord.ui.button(label="Approve now",emoji="✅",style=discord.ButtonStyle.success)
    async def approve(self,i,b):
        if not self.manual_mode():
            return await i.response.send_message("Manual SHADOW decisions are disabled in ALL_EXECUTE mode.",ephemeral=True)
        if not self.allowed(i):
            return await i.response.send_message("⛔ Not authorized.",ephemeral=True)

        await i.response.defer(ephemeral=True)

        try:
            r = await self.executor.approve_pending_signal(self.signal_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Approve button failed %s", self.symbol
            )
            await i.followup.send(
                "⚠️ NOT OPENED — internal_execution_error",
                ephemeral=True,
            )
            return

        if r.get("ok"):
            for x in self.children:
                x.disabled = True
            await i.message.edit(view=self)
            await i.followup.send(
                f"✅ APPROVED — {self.symbol}",
                ephemeral=True,
            )
            return

        skipped = str(r.get("skipped") or "not_opened")

        if skipped in {
            "contract_agreement_required",
            "expired",
            "no_pending_signal",
            "position_exists",
            "tp1_already_passed",
            "decision_already_claimed",
        }:
            for x in self.children:
                x.disabled = True
            try:
                await i.message.edit(view=self)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Failed disabling SHADOW buttons %s",
                    self.symbol,
                )

        await i.followup.send(
            f"⚠️ NOT OPENED — {skipped}",
            ephemeral=True,
        )

    @discord.ui.button(label="Wait for entry",emoji="⏳",style=discord.ButtonStyle.primary)
    async def wait(self,i,b):
        if not self.manual_mode():
            return await i.response.send_message("Entry waiting is automatic in ALL_EXECUTE mode.",ephemeral=True)
        if not self.allowed(i):
            return await i.response.send_message("⛔ Not authorized.",ephemeral=True)
        await i.response.defer(ephemeral=True)
        r=await self.executor.wait_pending_signal(self.signal_id)
        await i.followup.send(
            f"⏳ WAITING — {self.symbol}" if r.get("ok")
            else f"⚠️ CANNOT WAIT — {r.get('skipped')}",
            ephemeral=True
        )

    @discord.ui.button(label="Reject",emoji="❌",style=discord.ButtonStyle.danger)
    async def reject(self,i,b):
        if not self.manual_mode():
            return await i.response.send_message("Manual SHADOW decisions are disabled in ALL_EXECUTE mode.",ephemeral=True)
        if not self.allowed(i):
            return await i.response.send_message("⛔ Not authorized.",ephemeral=True)
        await i.response.defer(ephemeral=True)
        ok=await self.executor.skip_pending_signal(self.signal_id,"Rejected by Discord button")
        if ok:
            for x in self.children:x.disabled=True
            await i.message.edit(view=self)
        await i.followup.send(f"❌ REJECTED — {self.symbol}",ephemeral=True)
