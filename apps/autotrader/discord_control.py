from __future__ import annotations
import asyncio
import json

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands
from shadow_ui import ShadowDecisionView

log = logging.getLogger(__name__)

MAX_DISCORD_CHUNK = 1900  # Discord message safety margin


def _norm_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "").replace("_", "").replace("/", "")


def _chunks(text: str, limit: int = MAX_DISCORD_CHUNK):
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    out = []
    current = ""
    for line in text.splitlines(True):
        if len(line) > limit:
            if current:
                out.append(current.rstrip())
                current = ""
            while len(line) > limit:
                out.append(line[:limit])
                line = line[limit:]
        if len(current) + len(line) > limit:
            out.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        out.append(current.rstrip())
    return [x for x in out if x]


class DiscordControl:
    def __init__(self, cfg, executor, bybit, storage):
        self.cfg = cfg
        self.executor = executor
        self.bybit = bybit
        self.storage = storage
        intents = discord.Intents.none()
        intents.guilds = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.tree = self.bot.tree
        if not self.cfg.discord_admin_user_ids:
            log.critical(
                "DISCORD_ADMIN_USER_IDS is empty: every state-changing Discord command/button is disabled"
            )
        self._register()

    def make_shadow_view(self, signal_id, symbol):
        return ShadowDecisionView(self.cfg,self.executor,str(signal_id),symbol)

    def allowed(self, interaction: discord.Interaction) -> bool:
        return bool(self.cfg.discord_admin_user_ids) and interaction.user.id in self.cfg.discord_admin_user_ids

    async def send(self, i: discord.Interaction, text: str):
        parts = _chunks(text)
        if not i.response.is_done():
            await i.response.send_message(parts[0], ephemeral=True)
            parts = parts[1:]
        for part in parts:
            await i.followup.send(part, ephemeral=True)

    async def defer(self, i: discord.Interaction):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)

    async def deny(self, i: discord.Interaction):
        await self.send(i, "Not authorized.")

    def _register(self):
        @self.tree.command(name="demo_status", description="Bybit Demo Auto-Trader status")
        async def status(i: discord.Interaction):
            await self.defer(i)
            try:
                w = await self.bybit.wallet()
                account = await self.bybit.account_info()
                active = await self.storage.active()
                enabled = await self.executor.enabled()
                orphan = await self.storage.setting("orphan_positions", "")
                await self.send(
                    i,
                    f"🧪 **BYBIT DEMO AUTO-TRADER**\n"
                    f"Execution **{'ON' if enabled else 'PAUSED'}** · Demo endpoint ✅\n"
                    f"Signal mode **{self.cfg.execution_mode}** · SHADOW **{'audit only' if self.cfg.execution_mode == 'ALL_EXECUTE' else 'manual gate'}**\n"
                    f"SMART position manager **{'SHADOW / observation only' if self.cfg.smart_position_shadow_enabled else 'OFF'}**\n"
                    f"TP2 → TP1 protection **{'ON' if self.cfg.tp2_lock_sl_to_tp1_enabled else 'OFF'}**\n"
                    f"Equity **{w['equity']:.2f} USDT** · available **{w['available']:.2f} USDT**\n"
                    f"Open bot trades **{len(active)}/{self.cfg.max_open_positions}** · risk target **{self.cfg.risk_pct:.2f}%/trade**\n"
                    f"Orphan positions **{orphan if orphan else 'NONE'}**"
                    f"{' · same-symbol entries blocked' if orphan else ''}\n"
                    f"Margin **{account.get('marginMode') or 'UNKNOWN'}** · leverage target **{self.cfg.leverage}x**, fallback **instrument max**\n"
                    f"Minimum margin **{self.cfg.min_margin_usdt:.0f} USDT** · notional floor **margin × selected leverage**\n"
                    f"Smart Margin **{'ON' if self.cfg.smart_margin_enabled else 'OFF'}** · max extra **{self.cfg.smart_margin_max_extra_ratio*100:.0f}%**",
                )
            except Exception as e:
                await self.send(i, f"🔴 `{type(e).__name__}: {e}`")

        @self.tree.command(name="demo_balance", description="Demo wallet and isolated-margin balance")
        async def balance(i: discord.Interaction):
            await self.defer(i)
            try:
                w = await self.bybit.wallet()
                account = await self.bybit.account_info()
                await self.send(
                    i,
                    f"💰 **DEMO BALANCE**\n"
                    f"Equity **{w['equity']:.2f} USDT** · wallet **{w.get('wallet',0):.2f} USDT**\n"
                    f"Available **{w['available']:.2f} USDT**\n"
                    f"Position IM **{w.get('position_im',0):.2f}** · Order IM **{w.get('order_im',0):.2f}**\n"
                    f"Locked **{w.get('locked',0):.2f}** · bonus **{w.get('bonus',0):.2f} USDT**\n"
                    f"Margin mode **{account.get('marginMode') or 'UNKNOWN'}**",
                )
            except Exception as e:
                await self.send(i, f"🔴 `{type(e).__name__}: {e}`")

        @self.tree.command(name="demo_positions", description="Open demo positions managed by this bot")
        async def positions(i: discord.Interaction):
            await self.defer(i)
            rows = await self.storage.active()
            if not rows:
                await self.send(i, "No active demo trades.")
                return
            lines = ["📌 **DEMO POSITIONS**"]
            for x in rows:
                pos = await self.bybit.position(x["symbol"])
                qty = float((pos or {}).get("size") or x["last_position_qty"] or 0)
                entry = float((pos or {}).get("avgPrice") or x["avg_entry"] or x["entry_signal"])
                liq = float((pos or {}).get("liqPrice") or 0)
                leverage = float((pos or {}).get("leverage") or x.get("leverage") or self.cfg.leverage)
                lines.append(
                    f"• **{x['symbol']} {x['side']}** · qty `{qty:.10g}` · entry `{entry:.10g}` · "
                    f"lev `{leverage:g}x` · SL `{float(x['sl']):.10g}` · liq `{liq:.10g}` · "
                    f"TP1 {'✅' if x['tp1_hit'] else '—'} TP2 {'✅' if x['tp2_hit'] else '—'} TP3 {'✅' if x['tp3_hit'] else '—'} · "
                    f"TP2-lock **{x.get('tp2_lock_status') or 'NOT_DUE'}**"
                )
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_smart", description="Live SMART observations for actual Demo positions")
        async def smart_active(i: discord.Interaction):
            await self.defer(i)
            rows = await self.storage.smart_position_active()
            if not rows:
                await self.send(i, "No SMART position observations yet.")
                return
            lines = ["🧠 **DEMO SMART POSITIONS · observation only**"]
            for x in rows:
                lines.append(
                    f"• **{x['symbol']} {x['side']}** · **{x['action']}** · health `{float(x['health_score']):.0f}`\n"
                    f"  now `{float(x['current_r']):+.2f}R` · max `{float(x['max_r']):+.2f}R` · "
                    f"min `{float(x['min_r']):+.2f}R` · giveback `{float(x['giveback_r']):.2f}R`\n"
                    f"  signal **{x.get('smart_status') or 'NO_DATA'} {float(x.get('smart_score') or 0):.0f}/100** · "
                    f"{x.get('smart_setup') or 'UNKNOWN'} / {x.get('smart_regime') or 'TRANSITION'}"
                )
            lines.append("\n_No order, SL, TP or close is changed by these observations._")
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_smart_stats", description="Actual Demo outcomes grouped by scanner SMART label")
        @app_commands.describe(days="1–30")
        async def smart_stats(i: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7):
            await self.defer(i)
            rows = await self.storage.smart_signal_outcomes(time.time() - days * 86400)
            if not rows:
                await self.send(i, "No SMART-labelled Demo trades yet.")
                return
            lines = [f"🧠 **DEMO SMART OUTCOMES — {days} DAYS**"]
            for x in rows:
                n = int(x.get("n") or 0); closed = int(x.get("closed_n") or 0)
                wins = int(x.get("winners") or 0)
                lines.append(
                    f"• **{x.get('smart_status') or 'NO_DATA'}** n={n}, closed={closed} · "
                    f"wins `{wins/closed*100 if closed else 0:.0f}%` · net `{float(x.get('net_pnl') or 0):+.2f} USDT` · "
                    f"avg `{float(x.get('avg_net_pnl') or 0):+.2f} USDT`"
                )
            lines.append("\n_Use a materially larger closed sample before enabling any SMART action._")
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_active", description="Real active Bybit Demo positions managed by this bot")
        async def active_cmd(i: discord.Interaction):
            await self.defer(i)

            rows = await self.storage.active()
            lines = ["🟢 **DEMO ACTIVE — REAL POSITIONS**"]
            shown = 0
            errors = []

            for x in rows:
                try:
                    pos = await self.bybit.position(x["symbol"])
                    qty = float((pos or {}).get("size") or 0)

                    if qty <= 0:
                        continue

                    entry = float(
                        (pos or {}).get("avgPrice")
                        or x.get("avg_entry")
                        or x.get("entry_signal")
                        or 0
                    )

                    mark = float((pos or {}).get("markPrice") or 0)
                    if mark <= 0:
                        try:
                            mark = float(await self.bybit.ticker(x["symbol"]))
                        except Exception:
                            pass

                    liq = float((pos or {}).get("liqPrice") or 0)
                    leverage = float((pos or {}).get("leverage") or x.get("leverage") or self.cfg.leverage)

                    lines.append(
                        f"• **{x['symbol']} {x['side']}**\n"
                        f"  Entry `{entry:.10g}` · Current `{mark:.10g}` · Qty `{qty:.10g}` · Lev `{leverage:g}x`\n"
                        f"  SL `{float(x['sl']):.10g}` · Liq `{liq:.10g}`\n"
                        f"  TP1 {'✅' if x['tp1_hit'] else '—'} · "
                        f"TP2 {'✅' if x['tp2_hit'] else '—'} · "
                        f"TP3 {'✅' if x['tp3_hit'] else '—'} · "
                        f"TP2-lock **{x.get('tp2_lock_status') or 'NOT_DUE'}**"
                    )
                    shown += 1

                except Exception as e:
                    errors.append(f"{x['symbol']}: {type(e).__name__}")

            if shown == 0:
                if errors:
                    await self.send(
                        i,
                        "⚠️ No positions could be confirmed.\n"
                        + "\n".join(f"• `{e}`" for e in errors)
                    )
                else:
                    await self.send(i, "No real active Bybit Demo positions.")
                return

            lines.insert(1, f"Open **{shown}**")
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_trade", description="Detailed view of one active demo trade")
        @app_commands.describe(symbol="e.g. BTRUSDT")
        async def trade(i: discord.Interaction, symbol: str):
            await self.defer(i)
            symbol = _norm_symbol(symbol)
            x = await self.storage.active_for_symbol(symbol)
            if not x:
                await self.send(i, "No active bot-managed trade for that symbol.")
                return
            pos = await self.bybit.position(symbol)
            orders = await self.bybit.open_orders(symbol)
            qty = float((pos or {}).get("size") or x["last_position_qty"] or 0)
            entry = float((pos or {}).get("avgPrice") or x["avg_entry"] or x["entry_signal"])
            mark = float((pos or {}).get("markPrice") or 0)
            liq = float((pos or {}).get("liqPrice") or 0)
            pim = float((pos or {}).get("positionIM") or 0)
            value = abs(float((pos or {}).get("positionValue") or 0))
            leverage = float((pos or {}).get("leverage") or x.get("leverage") or self.cfg.leverage)
            net = float(x.get("net_pnl_usdt") or 0)
            risk = float(x.get("risk_usdt") or 0)
            tp2_lock_price = float(x.get("tp2_lock_price") or 0)
            tp2_lock_target = f" · target `{tp2_lock_price:.10g}`" if tp2_lock_price else ""
            await self.send(
                i,
                f"🔎 **DEMO TRADE — {symbol} {x['side']}**\n"
                f"Status **{x['status']}** · score **{float(x.get('score') or 0):.0f}** · setup **{x.get('setup_type') or '—'}**\n"
                f"Entry `{entry:.10g}` · mark `{mark:.10g}` · qty `{qty:.10g}`\n"
                f"Notional **~{value:.2f} USDT** · leverage **{leverage:g}x** · position IM **~{pim:.2f} USDT** · liq `{liq:.10g}`\n"
                f"SL `{float(x['sl']):.10g}` · TP1 `{float(x['tp1']):.10g}` · TP2 `{float(x['tp2']):.10g}` · TP3 `{float(x['tp3']):.10g}`\n"
                f"TP1 {'✅' if x['tp1_hit'] else '—'} · TP2 {'✅' if x['tp2_hit'] else '—'} · TP3 {'✅' if x['tp3_hit'] else '—'} · open orders **{len(orders)}**\n"
                f"TP2 → TP1 protection **{x.get('tp2_lock_status') or 'NOT_DUE'}**"
                f"{tp2_lock_target}\n"
                f"Initial SL risk **{risk:.2f} USDT** · realized net **{net:+.2f} USDT** · extra margin **{float(x.get('extra_margin_usdt') or 0):.2f} USDT**",
            )

        @self.tree.command(name="demo_orders", description="Open TP/SL/conditional demo orders")
        @app_commands.describe(symbol="optional symbol, e.g. BTRUSDT")
        async def orders(i: discord.Interaction, symbol: str | None = None):
            await self.defer(i)
            symbol = _norm_symbol(symbol) if symbol else None
            rows = await self.bybit.open_orders(symbol)
            if not rows:
                await self.send(i, "No open demo orders.")
                return
            lines = [f"📋 **DEMO ORDERS{' — '+symbol if symbol else ''}**"]
            for x in rows[:50]:
                trigger = x.get("triggerPrice") or "—"
                lines.append(
                    f"• **{x.get('symbol')} {x.get('side')}** · {x.get('orderType')} · qty `{x.get('qty')}` · "
                    f"trigger `{trigger}` · reduceOnly `{x.get('reduceOnly')}` · `{x.get('orderLinkId') or '—'}`"
                )
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_risk", description="Current portfolio risk and margin exposure")
        async def risk(i: discord.Interaction):
            await self.defer(i)
            r = await self.executor.risk_snapshot()
            lines = [
                "⚖️ **DEMO RISK**",
                f"Equity **{r['equity']:.2f} USDT** · available **{r['available']:.2f} USDT**",
                f"Open notional **~{r['notional']:.2f} USDT** · position IM **~{r['margin']:.2f} USDT**",
                f"Initial SL risk **{r['initial_risk']:.2f} USDT ({r['initial_risk_pct']:.2f}% equity)**",
                f"Current remaining SL loss exposure **{r['current_sl_risk']:.2f} USDT ({r['current_sl_risk_pct']:.2f}% equity)**",
            ]
            for x in r["items"]:
                lines.append(
                    f"• **{x['symbol']} {x['side']}** · SL risk `{x['current_sl_risk']:.2f}` · margin `{x['margin']:.2f}` · notional `{x['notional']:.2f}`"
                )
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_margin", description="Isolated margin and liquidation for one trade")
        @app_commands.describe(symbol="e.g. BTRUSDT")
        async def margin(i: discord.Interaction, symbol: str):
            await self.defer(i)
            symbol = _norm_symbol(symbol)
            x = await self.storage.active_for_symbol(symbol)
            if not x:
                await self.send(i, "No active bot-managed trade for that symbol.")
                return
            pos = await self.bybit.position(symbol)
            if not pos:
                await self.send(i, "Trade exists locally but Bybit position is flat/missing.")
                return
            value = abs(float(pos.get("positionValue") or 0))
            pim = float(pos.get("positionIM") or 0)
            liq = float(pos.get("liqPrice") or 0)
            extra = float(x.get("extra_margin_usdt") or 0)
            leverage = float(pos.get("leverage") or x.get("leverage") or self.cfg.leverage)
            await self.send(
                i,
                f"🧯 **DEMO MARGIN — {symbol}**\n"
                f"Leverage **{leverage:g}x** · configured target **{self.cfg.leverage}x** · position value **~{value:.2f} USDT**\n"
                f"Current isolated position IM **~{pim:.2f} USDT**\n"
                f"Smart/manual extra margin recorded **{extra:.2f} USDT**\n"
                f"Liquidation `{liq:.10g}` · SL `{float(x['sl']):.10g}`\n"
                f"Smart Margin cap **+{self.cfg.smart_margin_max_extra_ratio*100:.0f}% of initial margin**",
            )

        @self.tree.command(name="demo_add_margin", description="Manually add bounded isolated margin")
        @app_commands.describe(symbol="e.g. BTRUSDT", amount_usdt="USDT margin to add")
        async def add_margin(i: discord.Interaction, symbol: str, amount_usdt: app_commands.Range[float, 1.0, 100000.0]):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            symbol = _norm_symbol(symbol)
            try:
                r = await self.executor.manual_add_margin(symbol, float(amount_usdt))
                await self.send(
                    i,
                    f"🧯 **MARGIN ADDED — {symbol}**\n"
                    f"Added **{r['added']:.2f} USDT** · total recorded extra **{r['extra_total']:.2f} USDT**\n"
                    f"Position IM **~{r['position_im']:.2f} USDT** · liq `{r['liq_before']:.10g}` → `{r['liq_after']:.10g}`",
                )
            except Exception as e:
                await self.send(i, f"🔴 `{type(e).__name__}: {e}`")

        @self.tree.command(name="demo_stats", description="Real demo fills/PnL statistics")
        @app_commands.describe(days="1–30")
        async def stats(i: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7):
            await self.defer(i)
            r = await self.storage.stats(time.time() - days * 86400)
            n = r["n"]
            closed = r["closed"]
            def pct(v, d): return v / d * 100 if d else 0
            pf = "∞" if r["pf"] == float("inf") else (f"{r['pf']:.2f}" if isinstance(r["pf"], (int, float)) else "—")
            await self.send(
                i,
                f"📊 **DEMO STATS — {days} DAYS**\n"
                f"Signals **{n}** · closed **{closed}** · active **{r['active']}**\n"
                f"✅ Win **{r['wins']} ({pct(r['wins'], closed):.0f}%)** · ➖ BE **{r['be']} ({pct(r['be'], closed):.0f}%)** · ❌ Loss **{r['losses']} ({pct(r['losses'], closed):.0f}%)**\n"
                f"Net PnL **{r['net']:+.2f} USDT** · fees **{r['fees']:.2f} USDT** · PF **{pf}**\n"
                f"Avg trade **{r['avg_r']:+.2f}R** · best **{r['best_r']:+.2f}R** · worst **{r['worst_r']:+.2f}R**\n"
                f"TP1 **{r['tp1']}/{n} ({pct(r['tp1'], n):.0f}%)** · TP2 **{r['tp2']}/{n} ({pct(r['tp2'], n):.0f}%)** · TP3 **{r['tp3']}/{n} ({pct(r['tp3'], n):.0f}%)**\n"
                f"Smart Margin assisted **{r['margin_assisted']}/{n}** · extra margin **{r['extra_margin']:.2f} USDT**",
            )

        @self.tree.command(name="demo_recent", description="Recent demo trades")
        @app_commands.describe(limit="1–15")
        async def recent(i: discord.Interaction, limit: app_commands.Range[int, 1, 15] = 10):
            await self.defer(i)
            rows = await self.storage.recent(limit)
            if not rows:
                await self.send(i, "No demo trades yet.")
                return
            lines = ["🕘 **DEMO RECENT**"]
            for x in rows:
                risk = float(x["risk_usdt"] or 0)
                net = float(x["net_pnl_usdt"] or 0)
                rr = net/risk if risk else 0
                lines.append(f"• **{x['symbol']} {x['side']}** · **{x['status']}** / {x['close_reason'] or '—'} · `{net:+.2f} USDT` · `{rr:+.2f}R`")
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_pause", description="Pause new demo entries")
        async def pause(i: discord.Interaction):
            if not self.allowed(i):
                await self.deny(i); return
            await self.executor.set_enabled(False)
            await self.send(i, "⏸️ New demo entries paused. Existing positions remain managed.")

        @self.tree.command(name="demo_resume", description="Resume new demo entries")
        async def resume(i: discord.Interaction):
            if not self.allowed(i):
                await self.deny(i); return
            await self.executor.set_enabled(True)
            await self.send(i, "▶️ New demo entries resumed.")

        @self.tree.command(name="demo_sync", description="Force Bybit ↔ bot trade reconciliation")
        async def sync(i: discord.Interaction):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            r = await self.executor.sync_now()
            text = (
                f"🔄 **DEMO SYNC**\nChecked **{r['checked']}** active trades · "
                f"history repaired **{r['backfilled']}** · failures **{len(r['failed'])}**"
            )
            if r["failed"]:
                text += "\n" + "\n".join(f"• {x}" for x in r["failed"])
            await self.send(i, text)

        @self.tree.command(name="demo_pending", description="SHADOW WOULD BLOCK signals waiting for your decision")
        async def pending(i: discord.Interaction):
            await self.defer(i)
            rows = await self.storage.pending()
            if not rows:
                empty = (
                    "✅ No EXECUTE signals waiting for entry."
                    if self.cfg.execution_mode == "ALL_EXECUTE"
                    else "✅ No SHADOW signals waiting for manual decision."
                )
                await self.send(i, empty)
                return
            automatic = self.cfg.execution_mode == "ALL_EXECUTE"
            lines = [
                "⏳ **DEMO PENDING — AUTO WAITING FOR ENTRY**"
                if automatic
                else "⚠️ **DEMO PENDING — MANUAL DECISION**"
            ]
            for x in rows[:20]:
                exp = float(x.get("expires_at") or 0)
                if exp:
                    left = int((exp - time.time()) / 60)
                    validity = f"{left}m left" if left > 0 else "EXPIRED"
                else:
                    validity = "no expiry"
                line = (
                    f"• **{x['symbol']} {x['side']}** · SHADOW **{x.get('shadow_status') or '—'}** · {validity}"
                )
                if not automatic:
                    line += f"\n  `/demo_approve {x['symbol']}` or `/demo_skip {x['symbol']}`"
                lines.append(line)
            await self.send(i, "\n".join(lines))

        @self.tree.command(name="demo_approve", description="Approve one SHADOW-blocked EXECUTE")
        @app_commands.describe(symbol="e.g. BTRUSDT")
        async def approve(i: discord.Interaction, symbol: str):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            if self.cfg.execution_mode == "ALL_EXECUTE":
                await self.send(i, "Manual SHADOW decisions are disabled in ALL_EXECUTE mode; entry waiting is automatic.")
                return
            symbol = _norm_symbol(symbol)
            try:
                r = await self.executor.approve_pending(symbol)
                if r.get("ok"):
                    await self.send(i, f"✅ **APPROVED — {symbol}**\nManual SHADOW override accepted. Normal safeguards still apply.")
                else:
                    await self.send(i, f"⚠️ **NOT OPENED — {symbol}**\nReason: `{r.get('skipped') or r}`")
            except Exception as e:
                await self.send(i, f"🔴 **APPROVAL ERROR — {symbol}**\n`{type(e).__name__}: {e}`")

        @self.tree.command(name="demo_skip", description="Reject one SHADOW-blocked EXECUTE")
        @app_commands.describe(symbol="e.g. BTRUSDT")
        async def skip(i: discord.Interaction, symbol: str):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            if self.cfg.execution_mode == "ALL_EXECUTE":
                await self.send(i, "Manual SHADOW decisions are disabled in ALL_EXECUTE mode; use `/demo_pause` to stop new entries.")
                return
            symbol = _norm_symbol(symbol)
            ok = await self.executor.skip_pending(symbol, f"Rejected by Discord user {i.user.id}")
            await self.send(i, f"⏭️ **SKIPPED — {symbol}**" if ok else f"No pending SHADOW signal for **{symbol}**.")

        @self.tree.command(name="demo_close", description="Close one bot-managed demo position")
        @app_commands.describe(symbol="e.g. BTRUSDT")
        async def close(i: discord.Interaction, symbol: str):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            symbol = _norm_symbol(symbol)
            async with self.executor.lock(symbol):
                ok = await self.executor.close_trade(symbol, "MANUAL", f"Closed by Discord user {i.user.id}")
            await self.send(i, "Closed." if ok else "No active bot trade for that symbol.")

        @self.tree.command(name="demo_close_all", description="Close every bot-managed demo position")
        async def close_all(i: discord.Interaction):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            r = await self.executor.close_all("MANUAL_ALL", f"Close-all by Discord user {i.user.id}")
            text = f"🏁 **DEMO CLOSE ALL**\nClosed **{len(r['closed'])}** · failed **{len(r['failed'])}**"
            if r["closed"]:
                text += "\nClosed: " + ", ".join(r["closed"])
            if r["failed"]:
                text += "\n" + "\n".join(f"• {x}" for x in r["failed"])
            await self.send(i, text)

        @self.tree.command(name="demo_emergency_stop", description="Pause entries and close all bot trades")
        async def emergency_stop(i: discord.Interaction):
            if not self.allowed(i):
                await self.deny(i); return
            await self.defer(i)
            r = await self.executor.emergency_stop(f"Emergency stop by Discord user {i.user.id}")
            text = (
                f"🛑 **DEMO EMERGENCY STOP**\n"
                f"New entries **PAUSED** · closed **{len(r['closed'])}** · failed **{len(r['failed'])}**"
            )
            if r["failed"]:
                text += "\n" + "\n".join(f"• {x}" for x in r["failed"])
            await self.send(i, text)

        @self.tree.command(name="demo_help", description="Bybit Demo Auto-Trader commands")
        async def help_cmd(i: discord.Interaction):
            await self.send(
                i,
                "🧪 **BYBIT DEMO AUTO-TRADER V1.5.3 — COMMANDS**\n"
                "`/demo_status` status · `/demo_balance` wallet/margin\n"
                "`/demo_active` real Bybit positions · `/demo_positions` DB-managed trades\n`/demo_trade SYMBOL` one trade\n"
                "`/demo_orders [SYMBOL]` open orders · `/demo_risk` portfolio risk\n"
                "`/demo_margin SYMBOL` margin/liq · `/demo_add_margin SYMBOL AMOUNT` add bounded margin\n"
                "`/demo_stats [DAYS]` PnL stats · `/demo_recent [LIMIT]` history\n"
                "`/demo_smart` live SMART observations · `/demo_smart_stats [DAYS]` outcomes\n"
                "`/demo_pause` pause entries · `/demo_resume` resume\n"
                "`/demo_sync` reconcile Bybit↔DB\n"
                "`/demo_pending` shadow decisions · `/demo_approve SYMBOL` approve · `/demo_skip SYMBOL` reject\n"
                "`/demo_close SYMBOL` close one\n"
                "`/demo_close_all` close all bot trades\n"
                "`/demo_emergency_stop` PAUSE + close all · `/demo_help` this list\n"
            )

        @self.bot.event
        async def on_ready():
            try:
                channel = self.bot.get_channel(self.cfg.discord_channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.cfg.discord_channel_id)
                if not getattr(channel, "guild", None):
                    raise RuntimeError("DISCORD_CHANNEL_ID is not a guild channel")
                # Restore persistent SHADOW buttons only while SHADOW is a manual gate.
                registered = getattr(self, "_shadow_persistent_registered", set())
                restored = 0
                live_restored = 0

                pending_rows = (
                    await self.storage.pending()
                    if self.cfg.execution_mode == "SHADOW_MANUAL"
                    else []
                )
                for row in pending_rows:
                    signal_id = str(row["signal_id"])

                    if signal_id in registered:
                        continue

                    self.bot.add_view(
                        ShadowDecisionView(
                            self.cfg,
                            self.executor,
                            signal_id,
                            row["symbol"],
                        )
                    )
                    registered.add(signal_id)
                    restored += 1

                    message_id = row.get("discord_message_id")

                    if message_id:
                        try:
                            payload = json.loads(row.get("payload_json") or "{}")

                            entry = float(payload.get("entry") or 0)
                            entry_low = float(payload.get("entry_low", entry))
                            entry_high = float(payload.get("entry_high", entry))
                            expires_at = float(row.get("expires_at") or 0)

                            message = await channel.fetch_message(int(message_id))

                            self.executor.start_pending_price_task(
                                signal_id,
                                row["symbol"],
                                entry_low,
                                entry_high,
                                expires_at,
                                message,
                            )

                            live_restored += 1

                        except Exception:
                            log.exception(
                                "Persistent SHADOW live price restore failed signal=%s",
                                signal_id,
                            )

                self._shadow_persistent_registered = registered

                if restored:
                    log.info("Persistent SHADOW views restored=%s", restored)

                if live_restored:
                    log.info(
                        "Persistent SHADOW live price restored=%s",
                        live_restored,
                    )

                guild = discord.Object(id=channel.guild.id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(
                    "Discord ready as %s · guild=%s · channel=#%s (%s) · slash_commands=%s",
                    self.bot.user, channel.guild.id, getattr(channel, "name", "?"),
                    self.cfg.discord_channel_id, len(synced),
                )
                self._ready_failures = 0
            except Exception:
                log.exception("Discord guild command sync failed")
                self._ready_failures = getattr(self, "_ready_failures", 0) + 1
                if self._ready_failures >= 3:
                    log.critical(
                        "Discord readiness failed %s times; stopping bot so systemd restarts the service",
                        self._ready_failures,
                    )
                    await self.bot.close()

    async def start(self):
        if not self.cfg.discord_bot_token:
            log.warning("DISCORD_BOT_TOKEN not set; Discord commands/notifications disabled")
            return
        await self.bot.start(self.cfg.discord_bot_token)

    async def close(self):
        if self.cfg.discord_bot_token:
            await self.bot.close()
