from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from models import ExecuteSignal, ManagementEvent
from smart_position import assess_position

log = logging.getLogger(__name__)


class DemoExecutor:
    def __init__(self, cfg, bybit, storage, notifier):
        self.cfg = cfg
        self.bybit = bybit
        self.storage = storage
        self.notifier = notifier
        self._locks: dict[str, asyncio.Lock] = {}
        self._entry_lock = asyncio.Lock()
        self._pending_live_tasks: dict[str, asyncio.Task] = {}
        self._orphan_snapshot = ""
        self._next_historical_backfill_at = 0.0
        self._running = True
        self._smart_last_action: dict[int, str] = {}

    def lock(self, symbol: str) -> asyncio.Lock:
        return self._locks.setdefault(symbol, asyncio.Lock())

    @staticmethod
    def _source_label(signal_id: str) -> str:
        sid = str(signal_id or "").upper()
        if sid.startswith("V26S"):
            return "V2.6"
        return "V2.5"

    @asynccontextmanager
    async def entry_guard(self, symbol: str):
        # One global entry gate makes the portfolio cap/wallet snapshot/order
        # submission atomic relative to every other entry and emergency stop.
        async with self._entry_lock:
            async with self.lock(symbol):
                yield

    async def enabled(self) -> bool:
        override = await self.storage.setting("auto_enabled", "")
        if override:
            return override == "1"
        return self.cfg.auto_trading_enabled

    async def set_enabled(self, enabled: bool):
        await self.storage.set_setting("auto_enabled", "1" if enabled else "0")

    def all_execute_mode(self) -> bool:
        return getattr(self.cfg, "execution_mode", "SHADOW_MANUAL") == "ALL_EXECUTE"

    @staticmethod
    def _select_leverage(instrument: dict, target: float) -> float:
        leverage_filter = instrument.get("leverageFilter", {}) or {}
        try:
            target_value = Decimal(str(target))
            min_value = Decimal(str(leverage_filter.get("minLeverage") or "1"))
            max_value = Decimal(str(leverage_filter.get("maxLeverage") or "0"))
            step = Decimal(str(leverage_filter.get("leverageStep") or "0"))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValueError("Invalid instrument leverage metadata") from e
        if not all(x.is_finite() for x in (target_value, min_value, max_value, step)):
            raise ValueError("Non-finite instrument leverage limits")
        if target_value <= 0 or min_value <= 0 or max_value < min_value or step < 0:
            raise ValueError("Invalid instrument leverage limits")
        selected = min(target_value, max_value)
        if step > 0:
            selected = (selected / step).to_integral_value(rounding=ROUND_DOWN) * step
        if selected < min_value or selected <= 0:
            raise ValueError("No valid leverage at or below configured target")
        return float(selected)

    async def execute(self, payload: dict, manual_shadow_approval: bool = False, exact_entry_required: bool = False):
        signal = ExecuteSignal.from_payload(payload)
        async with self.entry_guard(signal.symbol):
            existing = await self.storage.by_signal(signal.signal_id)
            if existing:
                return {"ok": True, "duplicate": True, "trade_id": existing["id"], "status": existing["status"]}

            if signal.expires_at and time.time() >= signal.expires_at:
                await self.storage.event(
                    "EXECUTE_SKIPPED_EXPIRED", signal.symbol,
                    message="Signal validity expired", payload=payload,
                )
                return {"ok": False, "skipped": "expired"}

            shadow_norm = signal.shadow_status.upper().replace("_", " ").replace("-", " ")
            shadow_would_block = "WOULD BLOCK" in shadow_norm
            if shadow_would_block and not self.all_execute_mode() and not manual_shadow_approval:
                previous = await self.storage.pending_by_signal(signal.signal_id)
                if previous:
                    return {
                        "ok": False,
                        "skipped": "shadow_manual_pending",
                        "pending": previous.get("status") == "PENDING",
                        "status": previous.get("status"),
                    }
                await self.storage.save_pending(signal, payload)
                await self.storage.event(
                    "SHADOW_MANUAL_PENDING", signal.symbol,
                    message=signal.shadow_note or signal.shadow_status, payload=payload
                )
                expiry = ""
                if signal.expires_at:
                    mins = max(0, int((signal.expires_at - time.time()) / 60))
                    expiry = f"\nEntry validity remaining **~{mins} min**"
                try:
                    current_price = await self.bybit.ticker(signal.symbol)
                    current_text = f"{current_price:.10g}"
                except Exception:
                    current_text = "unavailable"

                message = await self.notifier.send(
                    f"⚠️ **DEMO MANUAL DECISION — {signal.symbol} {signal.side}**\n"
                    f"Source **{self._source_label(signal.signal_id)}** · Scanner **EXECUTE** · SHADOW **WOULD BLOCK**\n"
                    f"Quality **{signal.quality or '—'}** · score **{signal.score:.0f}** · setup **{signal.setup_type or '—'}**\n"
                    f"Entry `{signal.entry_low:.10g}–{signal.entry_high:.10g}` · Current `{current_text}`\n"
                    f"SL `{signal.sl:.10g}`\n"
                    f"TP1 `{signal.tp1:.10g}` · TP2 `{signal.tp2:.10g}` · TP3 `{signal.tp3:.10g}`\n"
                    f"Shadow: {signal.shadow_note or 'No additional reason supplied.'}{expiry}\n\n"
                    f"**NO ORDER OPENED.**\n"
                    f"`/demo_approve {signal.symbol}` — open if still valid\n"
                    f"`/demo_skip {signal.symbol}` — reject",
                view=self.notifier.shadow_view(signal.signal_id, signal.symbol)
                )
                if message is not None:
                    try:
                        await self.storage.set_pending_message_id(
                            signal.signal_id,
                            message.id,
                        )
                    except Exception:
                        log.exception(
                            "Failed saving SHADOW Discord message id %s",
                            signal.signal_id,
                        )

                    self.start_pending_price_task(
                        signal.signal_id,
                        signal.symbol,
                        signal.entry_low,
                        signal.entry_high,
                        signal.expires_at,
                        message,
                    )

                return {"ok": False, "skipped": "shadow_manual_pending", "pending": True}

            if shadow_would_block and self.all_execute_mode() and not manual_shadow_approval:
                await self.storage.event(
                    "SHADOW_BYPASSED_ALL_EXECUTE",
                    signal.symbol,
                    message=signal.shadow_note or signal.shadow_status,
                    payload=payload,
                )

            if not await self.enabled():
                await self.storage.event("EXECUTE_SKIPPED_PAUSED", signal.symbol, message="Auto trading paused", payload=payload)
                return {"ok": False, "skipped": "paused"}
            await self._audit_orphan_positions()
            orphan_raw = await self.storage.setting("orphan_positions", "")
            orphan_symbols = set()
            if orphan_raw:
                try:
                    orphan_symbols = {
                        str(x).upper()
                        for x in json.loads(orphan_raw)
                        if str(x).strip()
                    }
                except Exception:
                    log.exception("Invalid orphan_positions setting: %r", orphan_raw)
                    await self.storage.event(
                        "EXECUTE_SKIPPED_ORPHAN_STATE_INVALID", signal.symbol,
                        message="Could not safely parse orphan-position state", payload=payload,
                    )
                    return {"ok": False, "skipped": "orphan_remote_position"}

            if signal.symbol.upper() in orphan_symbols:
                await self.storage.event(
                    "EXECUTE_SKIPPED_ORPHAN", signal.symbol,
                    message="Unmatched Bybit position exists for this symbol", payload=payload,
                )
                return {"ok": False, "skipped": "orphan_remote_position"}
            active = await self.storage.active()
            if len(active) >= self.cfg.max_open_positions:
                await self.storage.event("EXECUTE_SKIPPED_CAP", signal.symbol, message="Max open positions", payload=payload)
                await self.notifier.send(f"⚪ **DEMO SKIP — {signal.symbol} {signal.side}**\nMax open positions **{self.cfg.max_open_positions}** reached.")
                return {"ok": False, "skipped": "max_open_positions"}
            local_same = await self.storage.active_for_symbol(signal.symbol)
            remote_same = await self.bybit.position(signal.symbol)
            if local_same or remote_same:
                await self.storage.event("EXECUTE_SKIPPED_POSITION", signal.symbol, message="Position already exists", payload=payload)
                return {"ok": False, "skipped": "position_exists"}

            market = await self.bybit.ticker(signal.symbol)
            if exact_entry_required:
                lo = signal.entry_low
                hi = signal.entry_high
            else:
                lo = signal.entry_low * (1 - self.cfg.entry_tolerance_pct / 100)
                hi = signal.entry_high * (1 + self.cfg.entry_tolerance_pct / 100)
            if not (lo <= market <= hi):
                if self.all_execute_mode() and not exact_entry_required:
                    previous = await self.storage.pending_by_signal(signal.signal_id)
                    if previous:
                        return {
                            "ok": False,
                            "skipped": "entry_waiting",
                            "pending": previous.get("status") in {"PENDING", "WAITING_ENTRY"},
                            "status": previous.get("status"),
                        }
                    await self.storage.save_pending(signal, payload)
                    if not await self.storage.set_pending_waiting(signal.signal_id):
                        raise RuntimeError("Could not persist automatic entry wait")
                    await self.storage.event(
                        "ALL_EXECUTE_WAITING_ENTRY",
                        signal.symbol,
                        message=f"market={market} outside exact entry zone {signal.entry_low}-{signal.entry_high}",
                        payload=payload,
                    )
                    expiry = ""
                    if signal.expires_at:
                        mins = max(0, int((signal.expires_at - time.time()) / 60))
                        expiry = f" · valid ~{mins} min"
                    await self.notifier.send(
                        f"⏳ **DEMO AUTO WAIT — {signal.symbol} {signal.side}**\n"
                        f"Source **{self._source_label(signal.signal_id)}** · Scanner **EXECUTE** · "
                        f"SHADOW **audit only**\n"
                        f"Current `{market:.10g}` outside exact entry zone "
                        f"`{signal.entry_low:.10g}–{signal.entry_high:.10g}`{expiry}.\n"
                        "The order will be attempted automatically only if price enters the zone "
                        "while the signal is still valid."
                    )
                    return {"ok": False, "skipped": "entry_waiting", "pending": True}
                await self.storage.event("EXECUTE_SKIPPED_ENTRY", signal.symbol, message=f"market={market} outside {lo}-{hi}", payload=payload)
                await self.notifier.send(
                    f"⚪ **DEMO SKIP — {signal.symbol} {signal.side}**\n"
                    f"Market `{market:.10g}` outside entry window `{signal.entry_low:.10g}–{signal.entry_high:.10g}` (+{self.cfg.entry_tolerance_pct:.2f}% tolerance)."
                )
                return {"ok": False, "skipped": "entry_window"}

            if signal.side == "LONG" and market >= signal.tp1:
                return {"ok": False, "skipped": "tp1_already_passed"}
            if signal.side == "SHORT" and market <= signal.tp1:
                return {"ok": False, "skipped": "tp1_already_passed"}

            wallet = await self.bybit.wallet()
            equity = wallet["equity"]
            available = wallet["available"]
            if equity <= 0 or available <= 0:
                raise RuntimeError("Demo wallet has no available balance")

            instrument = await self.bybit.instrument(signal.symbol)
            # Align all order levels to the exchange tick size before sending them to Bybit.
            signal.sl = self.bybit.quantize_price(signal.sl, instrument)
            signal.tp1 = self.bybit.quantize_price(signal.tp1, instrument)
            signal.tp2 = self.bybit.quantize_price(signal.tp2, instrument)
            signal.tp3 = self.bybit.quantize_price(signal.tp3, instrument)
            signal.validate_levels()

            try:
                leverage = self._select_leverage(instrument, self.cfg.leverage)
            except ValueError as e:
                await self.storage.event(
                    "EXECUTE_SKIPPED_LEVERAGE_METADATA", signal.symbol,
                    message=str(e), payload=payload,
                )
                await self.notifier.send(
                    f"⚪ **DEMO SKIP — {signal.symbol} {signal.side}**\n"
                    "Bybit did not provide a valid leverage range for this instrument."
                )
                return {"ok": False, "skipped": "leverage_unavailable"}
            leverage_fallback = leverage + 1e-12 < float(self.cfg.leverage)

            # UTA 2.0 uses account-level margin mode. Re-assert isolated before every new entry.
            await self.bybit.ensure_isolated_margin()

            stop_pct = abs(market - signal.sl) / market
            if stop_pct <= 0:
                raise RuntimeError("Invalid stop distance")

            risk_budget = equity * self.cfg.risk_pct / 100
            risk_sized_notional = risk_budget / stop_pct
            min_notional_floor = self.cfg.min_margin_usdt * leverage
            minimum_floor_applied = risk_sized_notional < min_notional_floor

            # A valid trade is never smaller than MIN_MARGIN_USDT at the selected leverage.
            requested_notional = max(risk_sized_notional, min_notional_floor)

            margin_capped_notional = available * leverage * self.cfg.max_margin_fraction
            hard_cap = margin_capped_notional
            if self.cfg.max_notional_usdt > 0:
                hard_cap = min(hard_cap, self.cfg.max_notional_usdt)

            if hard_cap + 1e-9 < min_notional_floor:
                await self.storage.event(
                    "EXECUTE_SKIPPED_MIN_MARGIN", signal.symbol,
                    message=f"Cap {hard_cap:.2f} below minimum notional {min_notional_floor:.2f}", payload=payload
                )
                await self.notifier.send(
                    f"⚪ **DEMO SKIP — {signal.symbol} {signal.side}**\n"
                    f"Cannot allocate minimum **{self.cfg.min_margin_usdt:.2f} USDT isolated margin** "
                    f"(**{min_notional_floor:.2f} USDT notional @ {leverage}x**) within current balance/caps."
                )
                return {"ok": False, "skipped": "minimum_margin_unavailable"}

            notional = min(requested_notional, hard_cap)
            raw_qty = notional / market

            qty_text, qty, exchange_min_notional, min_qty_forced = self.bybit.quantize_qty(raw_qty, instrument)
            actual_notional = qty * market

            # Normal qty rounding is downward. If that would put us below the configured margin floor,
            # round one step upward instead.
            if actual_notional + 1e-9 < min_notional_floor:
                qty_text, qty = self.bybit.quantize_qty_up(min_notional_floor / market, instrument)
                actual_notional = qty * market
                minimum_floor_applied = True

            if exchange_min_notional and actual_notional < exchange_min_notional:
                raise RuntimeError(
                    f"Calculated notional {actual_notional:.4f} below Bybit minimum {exchange_min_notional}"
                )
            if actual_notional > hard_cap * 1.001:
                raise RuntimeError(
                    f"Quantity rounding would exceed allowed notional cap: {actual_notional:.2f} > {hard_cap:.2f} USDT"
                )

            actual_margin = actual_notional / leverage
            if actual_margin + 1e-6 < self.cfg.min_margin_usdt:
                raise RuntimeError(
                    f"Safety guard: actual margin {actual_margin:.4f} below configured minimum {self.cfg.min_margin_usdt:.2f}"
                )

            projected_risk = qty * abs(market - signal.sl)
            # Verify three exchange-valid partial TP quantities before opening anything.
            planned_tp_text = self.bybit.split_qty(
                qty,
                (self.cfg.tp1_fraction, self.cfg.tp2_fraction, self.cfg.tp3_fraction),
                instrument,
            )

            # The explicit minimum-position policy may override RISK_PCT. Rounding alone may not.
            if projected_risk > risk_budget * 1.001 and not minimum_floor_applied:
                why = "minimum order quantity" if min_qty_forced else "quantity rounding"
                raise RuntimeError(
                    f"{why} would exceed risk budget: {projected_risk:.2f} > {risk_budget:.2f} USDT"
                )

            trade_id = await self.storage.create_trade(signal, self.cfg.risk_pct, projected_risk, leverage, qty, payload)
            entry_link = self._link(trade_id, "ENTRY")
            tp_links = tuple(self._link(trade_id, f"TP{i}") for i in (1, 2, 3))
            await self.storage.set_order_plan(
                trade_id,
                entry_link,
                tp_links,
                tuple(float(x) for x in planned_tp_text),
            )
            try:
                await self.bybit.set_leverage(signal.symbol, leverage)
                if leverage_fallback:
                    await self.storage.event(
                        "LEVERAGE_FALLBACK_SELECTED", signal.symbol, trade_id,
                        f"Configured target {self.cfg.leverage:g}x unavailable; selected highest valid leverage {leverage:g}x",
                        payload,
                    )
                entry_resp = await self.bybit.place_market_entry(
                    signal.symbol,
                    signal.side,
                    qty_text,
                    entry_link,
                    signal.sl,
                    self.cfg.sl_trigger_by,
                )
                order_id = str(entry_resp.get("result", {}).get("orderId") or "")
                await self.storage.mark_entry_submitted(trade_id, order_id)
                pos = await self._wait_position(signal.symbol, timeout=12)
                if not pos:
                    raise RuntimeError("Entry accepted but position did not appear within 12s")
                await self.storage.mark_status(trade_id, "PROTECTING", "Entry visible; applying protection")
                fill_qty = float(pos.get("size") or 0)
                avg_entry = float(pos.get("avgPrice") or market)

                # Keep Bybit's unlimited auto-add OFF. Smart Margin Assist below adds only a bounded amount
                # when the real isolated liquidation price would conflict with the scanner SL.
                await self.bybit.set_auto_add_margin(signal.symbol, False)
                await self._set_and_verify_stop(signal.symbol, signal.side, signal.sl)
                margin_assist = await self._ensure_liquidation_buffer(
                    trade_id, signal.symbol, signal.side, signal.sl, pos, leverage
                )
                # Refresh after any margin adjustment.
                pos = await self.bybit.position(signal.symbol) or pos
                fill_qty = float(pos.get("size") or fill_qty)
                avg_entry = float(pos.get("avgPrice") or avg_entry)
                q1, q2, q3 = self.bybit.split_qty(fill_qty, (self.cfg.tp1_fraction, self.cfg.tp2_fraction, self.cfg.tp3_fraction), instrument)
                await self.storage.set_order_plan(
                    trade_id,
                    entry_link,
                    tp_links,
                    (float(q1), float(q2), float(q3)),
                )
                await self.bybit.place_reduce_trigger(signal.symbol, signal.side, q1, signal.tp1, self.cfg.tp_trigger_by, tp_links[0])
                await self.bybit.place_reduce_trigger(signal.symbol, signal.side, q2, signal.tp2, self.cfg.tp_trigger_by, tp_links[1])
                await self.bybit.place_reduce_trigger(signal.symbol, signal.side, q3, signal.tp3, self.cfg.tp_trigger_by, tp_links[2])

                actual_risk_usdt = fill_qty * abs(avg_entry - signal.sl)
                await self.storage.mark_opened(trade_id, avg_entry, fill_qty, actual_risk_usdt, order_id, entry_link, tp_links)
                await self.storage.event("OPENED", signal.symbol, trade_id, payload=payload)
                fill_notional = fill_qty * avg_entry
                fill_margin = fill_notional / leverage
                extra_margin = float(margin_assist.get("added_usdt") or 0)
                total_isolated_margin = fill_margin + extra_margin
                effective_risk_pct = actual_risk_usdt / equity * 100 if equity else 0.0
                margin_note = (
                    f"\n🧯 Smart Margin +**{extra_margin:.2f} USDT** · total isolated margin ~**{total_isolated_margin:.2f} USDT** "
                    f"· liq `{margin_assist.get('liq_before', 0):.10g}` → `{margin_assist.get('liq_after', 0):.10g}`"
                    if extra_margin > 0 else ""
                )
                floor_note = (
                    f"\n⚠️ Minimum **{self.cfg.min_margin_usdt:.0f} USDT margin** floor overrode {self.cfg.risk_pct:.2f}% sizing."
                    if minimum_floor_applied and actual_risk_usdt > risk_budget * 1.001 else ""
                )
                leverage_note = (
                    f"\n⚙️ 10x unavailable for this instrument; using highest valid **{leverage:g}x**."
                    if leverage_fallback else ""
                )
                await self.notifier.send(
                    f"🟢 **DEMO OPENED — {signal.symbol} {signal.side}**\n"
                    f"Quality **{signal.quality or '—'}** · score **{signal.score:.0f}** · setup **{signal.setup_type or '—'}**\n"
                    f"Fill `{avg_entry:.10g}` · qty `{fill_qty:.10g}` · **ISOLATED {leverage:g}x**{leverage_note}\n"
                    f"Notional **~{fill_notional:.2f} USDT** · initial isolated margin **~{fill_margin:.2f} USDT**\n"
                    f"Initial SL risk **~{actual_risk_usdt:.2f} USDT ({effective_risk_pct:.2f}% equity)**{floor_note}{margin_note}\n"
                    f"SL `{signal.sl:.10g}`\nTP1 `{signal.tp1:.10g}` ({self.cfg.tp1_fraction*100:.0f}%) · "
                    f"TP2 `{signal.tp2:.10g}` ({self.cfg.tp2_fraction*100:.0f}%) · TP3 `{signal.tp3:.10g}` ({self.cfg.tp3_fraction*100:.0f}%)\n"
                    f"Source signal `{signal.signal_id}`\n"
                    f"SMART **{signal.smart_status or 'NO_DATA'} {signal.smart_score:.0f}/100** · "
                    f"{signal.smart_setup or 'UNKNOWN'} / {signal.smart_regime or 'TRANSITION'} · observation only"
                )
                return {"ok": True, "trade_id": trade_id, "order_id": order_id, "qty": fill_qty, "avg_entry": avg_entry, "leverage": leverage}
            except Exception as e:
                error_text = str(e)
                error_lower = error_text.lower()

                # Bybit 110126: this contract requires a separate trading
                # agreement. The rejection occurs before a usable entry is
                # opened, so do not classify it as RECOVERY_REQUIRED.
                agreement_required = (
                    "110126" in error_text
                    or "sign the required agreement" in error_lower
                )

                if agreement_required:
                    position_check_ok = False
                    remote_pos = None
                    try:
                        remote_pos = await self.bybit.position(signal.symbol)
                        position_check_ok = True
                    except Exception:
                        log.exception(
                            "Could not verify position after contract rejection %s",
                            signal.symbol,
                        )

                    if position_check_ok and not remote_pos:
                        log.warning(
                            "Entry rejected by Bybit agreement gate %s: %s",
                            signal.symbol,
                            error_text,
                        )
                        await self.storage.mark_status(
                            trade_id,
                            "ERROR_FLAT",
                            f"Entry rejected before fill: {error_text}",
                        )
                        await self.storage.event(
                            "ENTRY_REJECTED_CONTRACT_AGREEMENT",
                            signal.symbol,
                            trade_id,
                            error_text,
                            payload,
                        )
                        await self.notifier.send(
                            f"⚪ **DEMO NOT OPENED — {signal.symbol} {signal.side}**\n"
                            "Bybit rejected this contract because the required "
                            "trading agreement is not enabled on the Demo account.\n"
                            "`ErrCode 110126` · no position was opened."
                        )
                        return {
                            "ok": False,
                            "skipped": "contract_agreement_required",
                        }

                # Any rejection where a position may exist, or any later
                # protection/order failure, keeps the original failsafe path.
                log.exception("Open failed %s", signal.symbol)
                await self.storage.mark_status(
                    trade_id, "RECOVERY_REQUIRED", error_text
                )
                await self.storage.event(
                    "OPEN_ERROR",
                    signal.symbol,
                    trade_id,
                    error_text,
                    payload,
                )
                flat = await self._failsafe_open(
                    await self.storage._one(
                        "SELECT * FROM trades WHERE id=?", (trade_id,)
                    ),
                    error_text,
                )
                outcome = (
                    "Failsafe flatten confirmed."
                    if flat
                    else "RECOVERY REQUIRED: flat state not confirmed."
                )
                await self.notifier.send(
                    f"🔴 **DEMO OPEN ERROR — {signal.symbol} {signal.side}**\n"
                    f"`{type(e).__name__}: {e}`\n{outcome}"
                )
                raise

    async def _ensure_liquidation_buffer(
        self, trade_id: int, symbol: str, side: str, stop_loss: float,
        pos: dict, leverage: float,
    ):
        """Bounded manual margin assist. It never enables exchange-side unlimited auto-add.

        Goal: real isolated liquidation price must sit beyond the planned scanner SL, plus a configurable
        buffer measured as a fraction of the entry-to-SL distance.
        """
        if not self.cfg.smart_margin_enabled:
            return {"added_usdt": 0.0, "liq_before": self._liq(pos), "liq_after": self._liq(pos), "safe": True}

        avg = float(pos.get("avgPrice") or 0)
        if avg <= 0:
            raise RuntimeError("Smart Margin: position avgPrice unavailable")
        stop_dist = abs(avg - stop_loss)
        if stop_dist <= 0:
            raise RuntimeError("Smart Margin: invalid SL distance")
        buffer = stop_dist * self.cfg.smart_margin_buffer_stop_fraction

        def safe(liq: float) -> bool:
            if liq <= 0:
                # Bybit may return an empty liqPrice if it falls outside instrument bounds; treat as safely remote.
                return True
            if side == "LONG":
                return liq <= (stop_loss - buffer)
            return liq >= (stop_loss + buffer)

        liq_before = self._liq(pos)
        if safe(liq_before):
            return {"added_usdt": 0.0, "liq_before": liq_before, "liq_after": liq_before, "safe": True}

        position_value = float(pos.get("positionValue") or 0)
        position_im = float(pos.get("positionIM") or 0)
        initial_margin = position_im if position_im > 0 else position_value / max(1.0, leverage)
        if initial_margin <= 0:
            raise RuntimeError("Smart Margin: cannot determine isolated position margin")

        wallet = await self.bybit.wallet()
        max_by_ratio = initial_margin * self.cfg.smart_margin_max_extra_ratio
        max_by_wallet = max(0.0, wallet.get("available", 0.0)) * self.cfg.max_margin_fraction
        max_extra = min(max_by_ratio, max_by_wallet)
        if max_extra <= 0:
            raise RuntimeError("Smart Margin needed but no bounded extra margin is available")

        step = max(self.cfg.smart_margin_step_usdt, initial_margin * 0.25)
        added = 0.0
        current = pos
        liq_after = liq_before

        # Iterative API-driven adjustment avoids approximating maintenance-margin tiers locally.
        for _ in range(20):
            remaining = max_extra - added
            if remaining <= 0.0001:
                break
            amount = min(step, remaining)
            await self.bybit.add_margin(symbol, amount)
            added += amount
            await self.storage.add_extra_margin(trade_id, amount)
            await self.storage.event(
                "SMART_MARGIN_ADDED", symbol, trade_id,
                f"Added {amount:.2f} USDT isolated margin; cumulative {added:.2f} USDT"
            )
            await asyncio.sleep(0.15)
            current = await self.bybit.position(symbol) or current
            liq_after = self._liq(current)
            if safe(liq_after):
                return {
                    "added_usdt": added, "liq_before": liq_before, "liq_after": liq_after, "safe": True
                }

        raise RuntimeError(
            f"Smart Margin cap exhausted: added {added:.2f} USDT but liquidation {liq_after:.10g} "
            f"is not safely beyond SL {stop_loss:.10g}"
        )

    @staticmethod
    def _liq(pos: dict) -> float:
        try:
            return float(pos.get("liqPrice") or 0)
        except (TypeError, ValueError):
            return 0.0

    async def _set_and_verify_stop(self, symbol: str, side: str, stop_loss: float):
        market = await self.bybit.ticker(symbol)
        if side == "LONG" and stop_loss >= market:
            raise RuntimeError(f"LONG stop {stop_loss} is not below market {market}")
        if side == "SHORT" and stop_loss <= market:
            raise RuntimeError(f"SHORT stop {stop_loss} is not above market {market}")

        last_actual = 0.0
        for _ in range(4):
            await self.bybit.set_full_stop(symbol, stop_loss, self.cfg.sl_trigger_by)
            await asyncio.sleep(0.25)
            pos = await self.bybit.position(symbol)
            if not pos:
                raise RuntimeError("Position disappeared while verifying stop")
            last_actual = float(pos.get("stopLoss") or 0)
            tolerance = max(abs(stop_loss) * 1e-10, 1e-12)
            if abs(last_actual - stop_loss) <= tolerance:
                return pos
        raise RuntimeError(
            f"Bybit did not confirm stop {stop_loss}; current stop is {last_actual or 'unset'}"
        )

    def start_pending_price_task(
        self, signal_id, symbol, entry_low, entry_high, expires_at, message
    ) -> asyncio.Task:
        key = str(signal_id)
        current = self._pending_live_tasks.get(key)
        if current and not current.done():
            return current
        task = asyncio.create_task(
            self._pending_price_loop(
                key, symbol, entry_low, entry_high, expires_at, message
            ),
            name=f"shadow-live-{key[:24]}",
        )
        self._pending_live_tasks[key] = task

        def forget(done: asyncio.Task):
            if self._pending_live_tasks.get(key) is done:
                self._pending_live_tasks.pop(key, None)

        task.add_done_callback(forget)
        return task

    async def _cancel_bot_orders(self, trade: dict):
        links = {
            str(trade.get("entry_link_id") or ""),
            str(trade.get("tp1_link_id") or ""),
            str(trade.get("tp2_link_id") or ""),
            str(trade.get("tp3_link_id") or ""),
        }
        for link in links - {""}:
            try:
                await self.bybit.cancel_order(trade["symbol"], link)
            except Exception:
                log.exception("Bot-order cancellation failed %s %s", trade["symbol"], link)

    async def _failsafe_open(self, trade: dict | None, error: str) -> bool:
        if not trade:
            return False
        symbol = trade["symbol"]
        entry_cancelled = False
        try:
            # Cancel an entry that may still be resting before checking for a
            # position. A fill racing with cancellation is caught by the polls.
            if trade.get("entry_link_id"):
                response = await self.bybit.cancel_order(symbol, trade["entry_link_id"])
                entry_cancelled = response is not None
        except Exception:
            log.exception("Failsafe entry cancellation failed %s", symbol)

        try:
            pos = await self._wait_position(symbol, timeout=2)
            if pos:
                await self.bybit.close_market(
                    symbol, trade["side"], self._attempt_link(trade["id"], "FAILSAFE")
                )
            flat = await self._wait_flat(symbol, timeout=20)
            if not flat:
                await self.storage.mark_status(
                    trade["id"], "RECOVERY_REQUIRED", f"Failsafe not confirmed flat: {error}"
                )
                return False
            await self._cancel_bot_orders(trade)
            await self._sync_fills(trade)
            quantities = await self.storage.fill_quantities(trade["id"])
            if quantities["entry"] <= 0:
                order = None
                if trade.get("entry_link_id"):
                    order = await self.bybit.order_by_link(symbol, trade["entry_link_id"])
                status = str((order or {}).get("orderStatus") or "").upper()
                if entry_cancelled or status in {"CANCELLED", "REJECTED", "DEACTIVATED"}:
                    await self.storage.mark_status(
                        trade["id"], "ERROR_FLAT", f"Entry never filled: {error}"
                    )
                    return True
            await self.storage.mark_flat_syncing(
                trade["id"],
                str(trade.get("close_reason_requested") or "OPEN_FAILSAFE"),
                f"Confirmed flat after recovery/failsafe: {error}",
            )
            await self._finalize_flat_trade(trade)
            return True
        except Exception:
            log.exception("Failsafe flatten failed for %s", symbol)
            await self.storage.mark_status(
                trade["id"], "RECOVERY_REQUIRED", f"Failsafe exception: {error}"
            )
            return False

    async def _pending_price_loop(
        self, signal_id, symbol, entry_low, entry_high, expires_at, message
    ):
        while self._running:
            row = await self.storage.pending_by_signal(str(signal_id))

            if not row or row.get("status") not in {"PENDING","WAITING_ENTRY"}:
                return

            if expires_at and time.time() >= float(expires_at):
                changed = await self.storage.resolve_pending(
                    str(signal_id), "EXPIRED", "Entry validity expired"
                )
                if changed:
                    await self.notifier.send(
                        f"⌛ **DEMO PENDING EXPIRED — {symbol}**"
                    )
                return

            try:
                price = await self.bybit.ticker(symbol)

                if entry_low <= price <= entry_high:
                    where = "🟢 IN ENTRY"
                elif price > entry_high:
                    where = "⬆️ ABOVE ENTRY"
                else:
                    where = "⬇️ BELOW ENTRY"

                line = f"Current `{price:.10g}` · **{where}**"
                content = message.content

                if "Current `" in content:
                    content = re.sub(
                        r"Current `[^`]+`(?: · \*\*[^*]+\*\*)?",
                        line,
                        content,
                        count=1,
                    )
                elif "\nSL `" in content:
                    content = content.replace(
                        "\nSL `",
                        f"\n{line}\nSL `",
                        1,
                    )
                else:
                    content += f"\n{line}"

                if content != message.content:
                    await message.edit(content=content)

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Pending live price update failed %s", symbol)
                await asyncio.sleep(15)
                continue

            await asyncio.sleep(5)

    async def approve_pending_signal(
        self,
        signal_id: str,
        exact_entry_required: bool = False,
        resolution_note: str = "Manual SHADOW approval",
    ):
        row = await self.storage.pending_by_signal(str(signal_id))
        if not row or row.get("status") not in {"PENDING","WAITING_ENTRY"}:
            return {"ok": False, "skipped": "no_pending_signal"}

        expires = float(row.get("expires_at") or 0)
        if expires and time.time() >= expires:
            await self.storage.resolve_pending(
                row["signal_id"], "EXPIRED", "Entry validity expired"
            )
            return {"ok": False, "skipped": "expired"}

        previous_status = str(row["status"])
        if not await self.storage.claim_pending(row["signal_id"]):
            return {"ok": False, "skipped": "decision_already_claimed"}

        payload = json.loads(row["payload_json"])
        try:
            result = await self.execute(
                payload,
                manual_shadow_approval=True,
                exact_entry_required=exact_entry_required,
            )
        except Exception:
            await self.storage.release_pending(
                row["signal_id"], previous_status, "Approval failed; decision released"
            )
            raise

        if result.get("ok"):
            await self.storage.resolve_pending(
                row["signal_id"], "APPROVED", resolution_note,
                from_statuses=("PROCESSING",),
            )
        elif result.get("skipped") in {
            "entry_window", "paused", "max_open_positions",
            "minimum_margin_unavailable", "orphan_remote_position",
        }:
            await self.storage.release_pending(
                row["signal_id"], previous_status, str(result.get("skipped"))
            )
        else:
            await self.storage.resolve_pending(
                row["signal_id"], "SKIPPED", str(result.get("skipped") or "not opened"),
                from_statuses=("PROCESSING",),
            )

        return result

    async def wait_pending_signal(self, signal_id: str):
        row = await self.storage.pending_by_signal(str(signal_id))
        if not row or row.get("status") not in {"PENDING","WAITING_ENTRY"}:
            return {"ok": False, "skipped": "no_pending_signal"}

        expires = float(row.get("expires_at") or 0)
        if expires and time.time() >= expires:
            await self.storage.resolve_pending(
                row["signal_id"], "EXPIRED", "Expired before WAIT"
            )
            return {"ok": False, "skipped": "expired"}

        changed = await self.storage.set_pending_waiting(row["signal_id"])
        return {"ok": changed, "skipped": None if changed else "decision_already_claimed"}

    async def skip_pending_signal(self, signal_id: str, note: str = ""):
        row = await self.storage.pending_by_signal(str(signal_id))
        if not row or row.get("status") not in {"PENDING","WAITING_ENTRY"}:
            return False

        return await self.storage.resolve_pending(
            row["signal_id"], "SKIPPED", note or "Rejected manually",
            from_statuses=("PENDING", "WAITING_ENTRY"),
        )

    async def approve_pending(self, symbol: str):
        symbol = symbol.upper().replace("-", "").replace("_", "").replace("/", "")
        row = await self.storage.pending_for_symbol(symbol)
        if not row:
            return {"ok": False, "skipped": "no_pending_signal"}
        expires_at = float(row.get("expires_at") or 0)
        if expires_at and time.time() >= expires_at:
            await self.storage.resolve_pending(
                row["signal_id"], "EXPIRED", "Entry validity expired before manual approval"
            )
            return {"ok": False, "skipped": "expired"}
        return await self.approve_pending_signal(row["signal_id"])

    async def skip_pending(self, symbol: str, note: str = ""):
        symbol = symbol.upper().replace("-", "").replace("_", "").replace("/", "")
        row = await self.storage.pending_for_symbol(symbol)
        if not row:
            return False
        changed = await self.storage.resolve_pending(
            row["signal_id"], "SKIPPED", note or "Rejected manually",
            from_statuses=("PENDING", "WAITING_ENTRY"),
        )
        if not changed:
            return False
        await self.storage.event(
            "SHADOW_MANUAL_SKIPPED", symbol, message=note or "Rejected manually"
        )
        return True

    async def waiting_entry_loop(self):
        await asyncio.sleep(2)

        while self._running:
            try:
                for expired in await self.storage.expire_pending():
                    await self.notifier.send(
                        f"⌛ **DEMO PENDING EXPIRED — {expired['symbol']}**"
                    )
                if self.all_execute_mode():
                    for row in await self.storage.pending():
                        if row.get("status") != "PENDING":
                            continue
                        if await self.storage.set_pending_waiting(str(row["signal_id"])):
                            await self.storage.event(
                                "SHADOW_PENDING_AUTO_ADOPTED",
                                row["symbol"],
                                message="Recovered as automatic ALL_EXECUTE entry wait",
                            )
                rows = await self.storage.waiting_entry()

                for row in rows:
                    signal_id = str(row["signal_id"])
                    symbol = row["symbol"]
                    expires = float(row.get("expires_at") or 0)

                    if expires and time.time() >= expires:
                        await self.storage.resolve_pending(
                            signal_id,
                            "EXPIRED",
                            "Expired while waiting for entry",
                        )
                        await self.notifier.send(
                            f"⌛ **DEMO WAIT EXPIRED — {symbol}**"
                        )
                        continue

                    payload = json.loads(row["payload_json"])
                    signal = ExecuteSignal.from_payload(payload)
                    market = await self.bybit.ticker(symbol)

                    # WAIT FOR ENTRY = exact scanner zone, no tolerance.
                    if not (signal.entry_low <= market <= signal.entry_high):
                        continue

                    result = await self.approve_pending_signal(
                        signal_id,
                        exact_entry_required=True,
                        resolution_note=(
                            "Automatic ALL_EXECUTE entry-zone trigger"
                            if self.all_execute_mode()
                            else "Manual SHADOW wait-for-entry trigger"
                        ),
                    )

                    if result.get("ok"):
                        continue

                    reason = result.get("skipped")

                    if reason in {
                        "entry_window",
                        "paused",
                        "max_open_positions",
                        "minimum_margin_unavailable",
                    }:
                        continue

                    if reason:
                        await self.storage.resolve_pending(
                            signal_id,
                            "SKIPPED",
                            str(reason),
                        )
                        await self.notifier.send(
                            f"⚪ **DEMO WAIT STOPPED — {symbol}**\n"
                            f"Reason: `{reason}`"
                        )

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("WAIT FOR ENTRY loop failed")

            await asyncio.sleep(1.0)

    async def management(self, payload: dict):
        ev = ManagementEvent.from_payload(payload)
        async with self.lock(ev.symbol):
            action = ev.action
            trade = await self.storage.active_for_symbol(ev.symbol)
            pending = None
            if not trade and action in {
                "CLOSE", "INVALIDATED", "CLOSE_EARLY", "EXIT",
                "SIGNAL_CLOSED", "ENTRY_WINDOW_CLOSED"
            }:
                pending = await self.storage.pending_for_symbol(ev.symbol)
                if pending:
                    if str(pending["signal_id"]) != ev.signal_id:
                        return {"ok": False, "skipped": "stale_signal_id"}
                    if pending.get("status") == "PROCESSING":
                        return {"ok": False, "skipped": "pending_decision_in_progress"}
            if not trade and not pending:
                return {"ok": False, "skipped": "no_active_trade"}
            if trade and str(trade.get("signal_id") or "") != ev.signal_id:
                await self.storage.event(
                    "MANAGEMENT_STALE_SIGNAL", ev.symbol, trade["id"],
                    f"Received {ev.signal_id}; active {trade.get('signal_id')}", payload,
                )
                return {"ok": False, "skipped": "stale_signal_id"}
            if not await self.storage.claim_management_event(
                ev.event_id, ev.signal_id, ev.symbol, action, payload
            ):
                return {"ok": True, "duplicate": True}
            try:
                result = await self._apply_management(ev, payload, trade, pending)
            except Exception as e:
                await self.storage.finish_management_event(
                    ev.event_id, error=f"{type(e).__name__}: {e}"
                )
                raise
            await self.storage.finish_management_event(ev.event_id)
            return result

    async def _apply_management(
        self, ev: ManagementEvent, payload: dict, trade: dict | None, pending: dict | None
    ):
        action = ev.action
        if pending:
            changed = await self.storage.resolve_pending(
                pending["signal_id"], "CANCELLED", ev.reason or action,
                from_statuses=("PENDING", "WAITING_ENTRY"),
            )
            if not changed:
                raise RuntimeError("Pending decision changed while cancellation was applied")
            await self.storage.event(
                "SHADOW_PENDING_CANCELLED", ev.symbol,
                message=ev.reason or action, payload=payload,
            )
            await self.notifier.send(
                f"🚫 **DEMO PENDING CANCELLED — {ev.symbol}**\n"
                f"Scanner: **{action}**\n{ev.reason}".strip()
            )
            return {"ok": True, "pending_cancelled": True}

        if not trade:
            raise RuntimeError("Management target disappeared")

        if action in {"SIGNAL_CLOSED", "ENTRY_WINDOW_CLOSED"}:
            return {"ok": True, "ignored_for_active_trade": True}
        if action in {"MOVE_SL", "SL", "BREAKEVEN", "BE", "PROTECT"}:
            if ev.new_sl is None:
                await self.storage.event(
                    "MANAGEMENT_NOTE", ev.symbol, trade["id"], ev.reason, payload
                )
                return {"ok": True, "note_only": True}

            pos = await self.bybit.position(ev.symbol)
            if not pos:
                return {"ok": False, "skipped": "no_remote_position"}
            instrument = await self.bybit.instrument(ev.symbol)
            new_sl = self.bybit.quantize_price(float(ev.new_sl), instrument)
            db_sl = float(trade.get("sl") or 0)
            exchange_sl = float(pos.get("stopLoss") or 0)
            side = str(trade.get("side") or "").upper()

            if side in {"LONG", "BUY"}:
                current_sl = max(db_sl, exchange_sl)
            else:
                nonzero = [x for x in (db_sl, exchange_sl) if x > 0]
                current_sl = min(nonzero) if nonzero else 0.0

            would_loosen = (
                current_sl > 0
                and (
                    (side in {"LONG", "BUY"} and new_sl < current_sl)
                    or
                    (side in {"SHORT", "SELL"} and new_sl > current_sl)
                )
            )

            if would_loosen:
                await self.storage.event(
                    "SL_UPDATE_IGNORED_LOOSEN", ev.symbol, trade["id"],
                    f"Requested {new_sl:.10g}, current {current_sl:.10g}. {ev.reason}",
                    payload,
                )
                log.warning(
                    "Ignored SL loosening %s %s current=%s requested=%s",
                    ev.symbol, side, current_sl, new_sl,
                )
                return {"ok": True, "ignored": "would_loosen_sl", "sl": current_sl}

            await self._set_and_verify_stop(ev.symbol, trade["side"], new_sl)
            await self.storage.update_sl(trade["id"], new_sl, ev.reason)
            await self.storage.event(
                "SL_UPDATED", ev.symbol, trade["id"], ev.reason, payload
            )
            await self.notifier.send(
                f"🛡️ **DEMO PROTECT — {ev.symbol}**\n"
                f"SL → `{new_sl:.10g}`\n{ev.reason}".strip()
            )
            return {"ok": True, "sl": new_sl}

        if action in {"CLOSE", "INVALIDATED", "CLOSE_EARLY", "EXIT"}:
            closed = await self.close_trade(ev.symbol, action, ev.reason)
            return {"ok": closed, "closing": True}
        await self.storage.event(
            "MANAGEMENT_IGNORED", ev.symbol, trade["id"],
            f"Unknown action {action}", payload,
        )
        return {"ok": False, "skipped": "unknown_action"}

    async def close_trade(self, symbol: str, reason: str, note: str = ""):
        trade = await self.storage.active_for_symbol(symbol)
        if not trade:
            return False
        if trade["status"] == "CLOSED_SYNCING":
            return await self._finalize_flat_trade(trade)
        await self.storage.mark_closing(trade["id"], reason, note)
        pos = await self.bybit.position(symbol)
        if pos:
            await self.bybit.close_market(
                symbol, trade["side"], self._attempt_link(trade["id"], "CLOSE")
            )
        else:
            # Prevent a not-yet-filled entry from opening after the close request.
            if trade.get("entry_link_id"):
                await self.bybit.cancel_order(symbol, trade["entry_link_id"])
        if not await self._wait_flat(symbol, timeout=20):
            await self.storage.mark_status(
                trade["id"], "RECOVERY_REQUIRED", f"Close not confirmed flat: {reason}. {note}"
            )
            await self.storage.event(
                "CLOSE_NOT_CONFIRMED", symbol, trade["id"], reason, {"note": note}
            )
            await self.notifier.send(
                f"🔴 **DEMO CLOSE NOT CONFIRMED — {symbol}**\n"
                "Position still visible; recovery will retry."
            )
            return False
        await self._cancel_bot_orders(trade)
        await self.storage.mark_flat_syncing(trade["id"], reason, note)
        refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        await self._finalize_flat_trade(refreshed or trade)
        return True

    async def sync_now(self):
        rows = await self.storage.reconcilable()
        checked = 0
        failed = []
        for trade in rows:
            symbol = trade["symbol"]
            try:
                async with self.lock(symbol):
                    await self._reconcile_trade(trade)
                checked += 1
            except Exception as e:
                log.exception("Manual sync failed %s", symbol)
                failed.append(f"{symbol}: {type(e).__name__}: {e}")
        backfill = await self._backfill_incomplete_closed()
        return {"checked": checked, "failed": failed, "backfilled": backfill}

    async def close_all(self, reason: str = "MANUAL_ALL", note: str = ""):
        rows = await self.storage.active()
        closed = []
        failed = []
        for trade in rows:
            symbol = trade["symbol"]
            try:
                async with self.lock(symbol):
                    ok = await self.close_trade(symbol, reason, note)
                if ok:
                    closed.append(symbol)
            except Exception as e:
                log.exception("Close-all failed %s", symbol)
                failed.append(f"{symbol}: {type(e).__name__}: {e}")
        return {"closed": closed, "failed": failed}

    async def emergency_stop(self, note: str = "Discord emergency stop"):
        # Disable immediately, then wait for any in-flight serialized entry to
        # finish before taking the definitive list of positions to close.
        await self.set_enabled(False)
        async with self._entry_lock:
            result = await self.close_all("EMERGENCY_STOP", note)
        await self.storage.event(
            "EMERGENCY_STOP",
            message=f"Auto entries paused; closed={len(result['closed'])}; failed={len(result['failed'])}",
        )
        return result

    async def manual_add_margin(self, symbol: str, amount_usdt: float):
        if amount_usdt <= 0:
            raise ValueError("Margin amount must be > 0")
        async with self.lock(symbol):
            trade = await self.storage.active_for_symbol(symbol)
            if not trade:
                raise RuntimeError("No active bot-managed trade for that symbol")
            pos = await self.bybit.position(symbol)
            if not pos:
                raise RuntimeError("Bybit position is not open")

            wallet = await self.bybit.wallet()
            available = float(wallet.get("available") or 0)
            if amount_usdt > available + 1e-9:
                raise RuntimeError(
                    f"Requested {amount_usdt:.2f} USDT exceeds available {available:.2f} USDT"
                )

            stored_extra = float(trade.get("extra_margin_usdt") or 0)
            position_value = float(pos.get("positionValue") or 0)
            position_im = float(pos.get("positionIM") or 0)
            estimated_initial = max(
                0.0,
                position_im - stored_extra,
                position_value / max(
                    1.0,
                    float(pos.get("leverage") or trade.get("leverage") or self.cfg.leverage),
                ),
            )
            max_extra = estimated_initial * self.cfg.smart_margin_max_extra_ratio
            remaining_cap = max(0.0, max_extra - stored_extra)
            if amount_usdt > remaining_cap + 1e-9:
                raise RuntimeError(
                    f"Smart-margin cap allows only {remaining_cap:.2f} USDT more "
                    f"(configured max extra {self.cfg.smart_margin_max_extra_ratio*100:.0f}% of initial margin)"
                )

            liq_before = self._liq(pos)
            await self.bybit.add_margin(symbol, amount_usdt)
            await self.storage.add_extra_margin(trade["id"], amount_usdt)
            await self.storage.event(
                "MANUAL_MARGIN_ADDED", symbol, trade["id"],
                f"Discord/manual margin +{amount_usdt:.2f} USDT"
            )
            await asyncio.sleep(0.2)
            after = await self.bybit.position(symbol) or pos
            liq_after = self._liq(after)
            return {
                "added": amount_usdt,
                "liq_before": liq_before,
                "liq_after": liq_after,
                "position_im": float(after.get("positionIM") or 0),
                "extra_total": stored_extra + amount_usdt,
            }

    async def risk_snapshot(self):
        wallet = await self.bybit.wallet()
        rows = await self.storage.active()
        items = []
        total_initial = 0.0
        total_current_sl = 0.0
        total_margin = 0.0
        total_notional = 0.0
        for trade in rows:
            pos = await self.bybit.position(trade["symbol"])
            if not pos:
                continue
            qty = float(pos.get("size") or 0)
            entry = float(pos.get("avgPrice") or trade.get("avg_entry") or trade["entry_signal"] or 0)
            sl = float(trade.get("sl") or 0)
            if trade["side"] == "LONG":
                sl_loss_per_unit = max(0.0, entry - sl)
            else:
                sl_loss_per_unit = max(0.0, sl - entry)
            current_sl_risk = qty * sl_loss_per_unit
            initial_risk = float(trade.get("risk_usdt") or 0)
            margin = float(pos.get("positionIM") or 0)
            notional = abs(float(pos.get("positionValue") or 0))
            total_initial += initial_risk
            total_current_sl += current_sl_risk
            total_margin += margin
            total_notional += notional
            items.append({
                "symbol": trade["symbol"],
                "side": trade["side"],
                "initial_risk": initial_risk,
                "current_sl_risk": current_sl_risk,
                "margin": margin,
                "notional": notional,
                "liq": self._liq(pos),
            })
        equity = float(wallet.get("equity") or 0)
        return {
            "equity": equity,
            "available": float(wallet.get("available") or 0),
            "initial_risk": total_initial,
            "current_sl_risk": total_current_sl,
            "margin": total_margin,
            "notional": total_notional,
            "initial_risk_pct": total_initial/equity*100 if equity else 0.0,
            "current_sl_risk_pct": total_current_sl/equity*100 if equity else 0.0,
            "items": items,
        }

    async def _observe_smart_position(self, trade: dict, position: dict):
        """Persist a counterfactual view of the actual Demo position.

        This observer is intentionally unable to place, amend or close orders.
        A failure here must never interrupt protection reconciliation.
        """
        if not getattr(self.cfg, "smart_position_shadow_enabled", True):
            return
        try:
            previous = await self.storage.smart_position_for_trade(int(trade["id"]))
            assessment = assess_position(trade, position, previous)
            await self.storage.save_smart_position(
                assessment, getattr(self.cfg, "smart_position_history_sec", 60.0)
            )
            old = self._smart_last_action.get(int(trade["id"]))
            self._smart_last_action[int(trade["id"])] = assessment.action
            if old != assessment.action:
                log.info(
                    "SMART POSITION %s %s->%s health=%.0f current=%+.2fR max=%+.2fR giveback=%.2fR",
                    trade["symbol"], old or "NEW", assessment.action,
                    assessment.health_score, assessment.current_r,
                    assessment.max_r, assessment.giveback_r,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("SMART position observer failed %s: %s", trade.get("symbol"), e)

    async def reconcile_loop(self):
        await asyncio.sleep(2)
        while self._running:
            try:
                await self._audit_orphan_positions()
                if time.time() >= self._next_historical_backfill_at:
                    await self._backfill_incomplete_closed()
                    self._next_historical_backfill_at = time.time() + 3600
                for trade in await self.storage.reconcilable():
                    async with self.lock(trade["symbol"]):
                        await self._reconcile_trade(trade)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Reconcile loop failed")
            await asyncio.sleep(max(1.0, self.cfg.reconcile_sec))

    async def _audit_orphan_positions(self):
        remote = await self.bybit.positions()
        managed = {x["symbol"] for x in await self.storage.active()}
        orphan = sorted(
            {
                str(x.get("symbol") or "")
                for x in remote
                if str(x.get("symbol") or "") not in managed
            }
            - {""}
        )
        snapshot = json.dumps(orphan, separators=(",", ":")) if orphan else ""
        previous = await self.storage.setting("orphan_positions", "")
        if snapshot != previous:
            await self.storage.set_setting("orphan_positions", snapshot)
            if orphan:
                await self.storage.event(
                    "ORPHAN_POSITIONS_DETECTED",
                    message=f"Unmatched remote positions: {', '.join(orphan)}",
                )
                await self.notifier.send(
                    "🔴 **DEMO ORPHAN POSITION DETECTED**\n"
                    f"`{', '.join(orphan)}` has no live DB trade. "
                    "New entries for those symbol(s) are blocked; other symbols remain eligible. "
                    "No automatic close was attempted."
                )
            elif previous:
                await self.storage.event("ORPHAN_POSITIONS_CLEARED")
                await self.notifier.send(
                    "✅ **DEMO ORPHAN POSITION BLOCK CLEARED**\n"
                    "Previously blocked orphan symbol(s) may accept new entries again."
                )

    async def _reconcile_trade(self, trade: dict):
        status = str(trade.get("status") or "")
        if status in {"OPENING", "ENTRY_SUBMITTED", "PROTECTING"}:
            await self._recover_opening_trade(trade)
            return
        if status == "RECOVERY_REQUIRED":
            await self._failsafe_open(trade, str(trade.get("note") or "recovery"))
            return
        if status == "CLOSING":
            await self.storage.mark_status(
                trade["id"], "RECOVERY_REQUIRED", "Recovering interrupted close"
            )
            await self._failsafe_open(
                trade, str(trade.get("close_reason_requested") or "interrupted close")
            )
            return
        if status == "CLOSED_SYNCING":
            if await self.bybit.position(trade["symbol"]):
                await self.storage.mark_status(
                    trade["id"], "RECOVERY_REQUIRED", "Position reappeared during fill finalization"
                )
                return
            await self._finalize_flat_trade(trade)
            return

        await self._sync_fills(trade)
        pos = await self.bybit.position(trade["symbol"])
        qty = float(pos.get("size") or 0) if pos else 0.0
        await self.storage.update_position_qty(trade["id"], qty)

        refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        if not refreshed:
            return

        if qty > 0 and pos:
            try:
                await self._restore_monotonic_stop(refreshed, pos)
            except Exception as e:
                log.exception("Active stop recovery failed %s", trade["symbol"])
                await self.storage.mark_status(
                    trade["id"], "RECOVERY_REQUIRED", f"Stop recovery failed: {e}"
                )
                await self.notifier.send(
                    f"🔴 **DEMO PROTECTION FAILURE — {trade['symbol']}**\n"
                    "Could not verify SL; failsafe recovery will flatten."
                )
                return

        # A TP counts as hit only when the cumulative execution quantity for
        # that exact link reaches the planned slice (not on the first partial).
        for n in (1, 2, 3):
            key = f"tp{n}_hit"
            link = refreshed.get(f"tp{n}_link_id") or ""
            expected = float(refreshed.get(f"tp{n}_expected_qty") or 0)
            filled = await self.storage.fill_qty_for_link(trade["id"], link) if link else 0.0
            complete = filled > 0 and (
                expected <= 0 or filled + max(expected * 1e-6, 1e-12) >= expected
            )
            if complete and not refreshed.get(key):
                await self.storage.set_tp_hit(trade["id"], n)
                await self.storage.recalc_pnl(trade["id"])
                now = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
                protection_note = ""
                if n == 1 and qty > 0:
                    protection_note = await self._attempt_tp1_breakeven(now, pos)
                elif n == 2 and qty > 0:
                    protection_note = await self._attempt_tp2_lock_to_tp1(now, pos)

                await self.notifier.send(
                    f"🎯 **DEMO TP{n} — {trade['symbol']} {trade['side']}**\n"
                    f"Net realized so far **{float(now['net_pnl_usdt'] or 0):+.2f} USDT** · "
                    f"remaining qty `{qty:.10g}`"
                    f"{protection_note}"
                )

        refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        if qty > 0 and refreshed and refreshed.get("tp1_hit") and refreshed.get("be_status") not in {"APPLIED", "NOT_NEEDED"}:
            await self._attempt_tp1_breakeven(refreshed, pos)
            refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        if (
            qty > 0
            and refreshed
            and refreshed.get("tp2_hit")
            and getattr(self.cfg, "tp2_lock_sl_to_tp1_enabled", True)
            and refreshed.get("tp2_lock_status") not in {"APPLIED", "NOT_NEEDED"}
        ):
            await self._attempt_tp2_lock_to_tp1(refreshed, pos)
            refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))

        if qty > 0 and refreshed and pos:
            await self._observe_smart_position(refreshed, pos)

        if qty <= 0:
            await self._cancel_bot_orders(refreshed or trade)
            reason = (refreshed or trade).get("close_reason_requested") or self._infer_close_reason(refreshed or trade)
            await self.storage.mark_flat_syncing(
                trade["id"], reason, "Detected flat position from Bybit"
            )
            finalizing = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
            await self._finalize_flat_trade(finalizing or trade)

    async def _recover_opening_trade(self, trade: dict):
        await self._sync_fills(trade)
        pos = await self.bybit.position(trade["symbol"])
        if pos:
            try:
                await self.storage.mark_status(
                    trade["id"], "PROTECTING", "Restart recovery found an open position"
                )
                await self.bybit.set_auto_add_margin(trade["symbol"], False)
                await self._set_and_verify_stop(trade["symbol"], trade["side"], float(trade["sl"]))
                await self._ensure_liquidation_buffer(
                    trade["id"], trade["symbol"], trade["side"], float(trade["sl"]), pos,
                    float(pos.get("leverage") or trade.get("leverage") or self.cfg.leverage),
                )
                pos = await self.bybit.position(trade["symbol"]) or pos
                await self._restore_tp_orders(trade, pos)
                qty = float(pos.get("size") or 0)
                avg = float(pos.get("avgPrice") or trade.get("entry_signal") or 0)
                risk = qty * abs(avg - float(trade["sl"]))
                order_id = str(trade.get("entry_order_id") or "")
                if not order_id and trade.get("entry_link_id"):
                    order = await self.bybit.order_by_link(trade["symbol"], trade["entry_link_id"])
                    order_id = str((order or {}).get("orderId") or "")
                links = tuple(str(trade.get(f"tp{i}_link_id") or "") for i in (1, 2, 3))
                await self.storage.mark_opened(
                    trade["id"], avg, qty, risk, order_id,
                    str(trade.get("entry_link_id") or ""), links,
                )
                await self.storage.event(
                    "OPEN_RECOVERED", trade["symbol"], trade["id"],
                    "Position, SL and TP orders recovered after interrupted opening",
                )
                await self.notifier.send(
                    f"🛡️ **DEMO OPEN RECOVERED — {trade['symbol']}**\n"
                    "Position and protection verified after restart/interruption."
                )
            except Exception as e:
                log.exception("Opening recovery failed %s", trade["symbol"])
                await self.storage.mark_status(
                    trade["id"], "RECOVERY_REQUIRED", f"Opening recovery failed: {e}"
                )
            return

        if trade.get("status") == "PROTECTING":
            await self.storage.mark_flat_syncing(
                trade["id"], self._infer_close_reason(trade),
                "Position closed while protection was being established",
            )
            await self._finalize_flat_trade(trade)
            return

        age = time.time() - float(trade.get("status_updated_at") or trade.get("received_at") or 0)
        order = None
        if trade.get("entry_link_id"):
            order = await self.bybit.order_by_link(trade["symbol"], trade["entry_link_id"])
        order_status = str((order or {}).get("orderStatus") or "").upper()
        if age < 30 and order_status not in {"CANCELLED", "REJECTED", "DEACTIVATED"}:
            return
        if trade.get("entry_link_id"):
            await self.bybit.cancel_order(trade["symbol"], trade["entry_link_id"])
        pos = await self._wait_position(trade["symbol"], timeout=2)
        if pos:
            refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
            await self._recover_opening_trade(refreshed or trade)
            return
        await self._sync_fills(trade)
        quantities = await self.storage.fill_quantities(trade["id"])
        if quantities["entry"] > 0 or order_status in {"FILLED", "PARTIALLYFILLED"}:
            await self.storage.mark_flat_syncing(
                trade["id"], "OPENING_INTERRUPTED_FLAT",
                "Entry had execution evidence but position is flat",
            )
            await self._finalize_flat_trade(trade)
        else:
            await self.storage.mark_status(
                trade["id"], "ERROR_FLAT", "Entry order confirmed absent/cancelled without a position"
            )

    async def _restore_tp_orders(self, trade: dict, pos: dict):
        instrument = await self.bybit.instrument(trade["symbol"])
        qty = float(pos.get("size") or 0)
        expected = tuple(float(trade.get(f"tp{i}_expected_qty") or 0) for i in (1, 2, 3))
        if sum(expected) <= 0:
            texts = self.bybit.split_qty(
                qty,
                (self.cfg.tp1_fraction, self.cfg.tp2_fraction, self.cfg.tp3_fraction),
                instrument,
            )
            expected = tuple(float(x) for x in texts)
            await self.storage.set_order_plan(
                trade["id"], str(trade.get("entry_link_id") or ""),
                tuple(str(trade.get(f"tp{i}_link_id") or self._link(trade["id"], f"TP{i}")) for i in (1, 2, 3)),
                expected,
            )
            trade = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],)) or trade

        open_by_link = {
            str(x.get("orderLinkId") or ""): x
            for x in await self.bybit.open_orders(trade["symbol"])
        }
        remaining_position = qty
        for n in (1, 2, 3):
            link = str(trade.get(f"tp{n}_link_id") or self._link(trade["id"], f"TP{n}"))
            filled = await self.storage.fill_qty_for_link(trade["id"], link)
            need = max(0.0, expected[n - 1] - filled)
            if need <= max(expected[n - 1] * 1e-6, 1e-12):
                continue
            if link in open_by_link:
                remaining_position = max(0.0, remaining_position - need)
                continue
            old = await self.bybit.order_by_link(trade["symbol"], link)
            old_status = str((old or {}).get("orderStatus") or "").upper()
            if old and old_status not in {"CANCELLED", "REJECTED", "DEACTIVATED"}:
                remaining_position = max(0.0, remaining_position - need)
                continue
            if old:
                raise RuntimeError(f"TP{n} order {link} was cancelled/rejected; refusing duplicate link reuse")
            qty_text, send_qty, _, _ = self.bybit.quantize_qty(min(need, remaining_position), instrument)
            if send_qty <= 0 or send_qty > remaining_position + 1e-12:
                raise RuntimeError(f"Cannot safely restore TP{n} quantity")
            await self.bybit.place_reduce_trigger(
                trade["symbol"], trade["side"], qty_text,
                float(trade[f"tp{n}"]), self.cfg.tp_trigger_by, link,
            )
            remaining_position = max(0.0, remaining_position - send_qty)

    async def _restore_monotonic_stop(self, trade: dict, pos: dict):
        db_sl = float(trade.get("sl") or 0)
        actual_sl = float(pos.get("stopLoss") or 0)
        side = str(trade.get("side") or "").upper()
        if db_sl <= 0:
            raise RuntimeError("DB stop is missing")
        actual_worse = actual_sl <= 0 or (
            side == "LONG" and actual_sl < db_sl
        ) or (
            side == "SHORT" and actual_sl > db_sl
        )
        if actual_worse:
            await self._set_and_verify_stop(trade["symbol"], side, db_sl)
            return
        actual_better = (
            side == "LONG" and actual_sl > db_sl
        ) or (
            side == "SHORT" and actual_sl < db_sl
        )
        if actual_better:
            await self.storage.update_sl(
                trade["id"], actual_sl, "Adopted stricter exchange-side SL"
            )

    async def _attempt_tp1_breakeven(self, trade: dict, pos: dict | None) -> str:
        if not trade.get("tp1_hit") or not pos:
            return ""
        if trade.get("be_status") in {"APPLIED", "NOT_NEEDED"}:
            return ""
        if trade.get("be_status") == "FAILED":
            attempts = int(trade.get("be_attempts") or 0)
            delay = min(300.0, 5.0 * (2 ** min(attempts, 6)))
            last = float(trade.get("be_last_attempt_at") or 0)
            if time.time() - last < delay:
                return ""
        try:
            actual_entry = float(
                pos.get("avgPrice") or trade.get("avg_entry") or trade.get("entry_signal") or 0
            )
            if actual_entry <= 0:
                raise RuntimeError("Average entry is unavailable")
            instrument = await self.bybit.instrument(trade["symbol"])
            be_price = self.bybit.quantize_price(actual_entry, instrument)
            db_sl = float(trade.get("sl") or 0)
            exchange_sl = float(pos.get("stopLoss") or 0)
            side = str(trade.get("side") or "").upper()
            current = max(db_sl, exchange_sl) if side == "LONG" else min(
                [x for x in (db_sl, exchange_sl) if x > 0] or [0.0]
            )
            should_move = (side == "LONG" and be_price > current) or (
                side == "SHORT" and (current <= 0 or be_price < current)
            )
            if not should_move:
                await self.storage.set_be_status(
                    trade["id"], "NOT_NEEDED", be_price,
                    "SL already stricter than breakeven",
                )
                return (
                    f"\n🛡️ SL kept at `{current:.10g}` "
                    f"(already better than entry `{be_price:.10g}`)"
                )
            await self._set_and_verify_stop(trade["symbol"], side, be_price)
            await self.storage.update_sl(trade["id"], be_price, "TP1 full fill -> breakeven")
            await self.storage.set_be_status(
                trade["id"], "APPLIED", be_price, "TP1 full fill -> breakeven"
            )
            await self.storage.event(
                "TP1_SL_TO_ENTRY", trade["symbol"], trade["id"],
                f"SL moved to actual avg entry {be_price:.10g}",
            )
            return f"\n🛡️ SL → **BREAKEVEN** `{be_price:.10g}`"
        except Exception as e:
            log.exception("TP1 breakeven protection failed %s", trade["symbol"])
            await self.storage.set_be_status(
                trade["id"], "FAILED", None, f"{type(e).__name__}: {e}"
            )
            await self.storage.event(
                "TP1_SL_TO_ENTRY_FAILED", trade["symbol"], trade["id"],
                f"{type(e).__name__}: {e}",
            )
            return "\n⚠️ TP1 filled, but breakeven SL update failed; retry scheduled"

    async def _attempt_tp2_lock_to_tp1(self, trade: dict, pos: dict | None) -> str:
        if not getattr(self.cfg, "tp2_lock_sl_to_tp1_enabled", True):
            return ""
        if not trade.get("tp2_hit") or not pos:
            return ""
        if trade.get("tp2_lock_status") in {"APPLIED", "NOT_NEEDED"}:
            return ""
        if trade.get("tp2_lock_status") == "FAILED":
            attempts = int(trade.get("tp2_lock_attempts") or 0)
            delay = min(300.0, 5.0 * (2 ** min(attempts, 6)))
            last = float(trade.get("tp2_lock_last_attempt_at") or 0)
            if time.time() - last < delay:
                return ""
        try:
            instrument = await self.bybit.instrument(trade["symbol"])
            tp1_price = self.bybit.quantize_price(float(trade.get("tp1") or 0), instrument)
            if tp1_price <= 0:
                raise RuntimeError("TP1 price is unavailable")

            db_sl = float(trade.get("sl") or 0)
            exchange_sl = float(pos.get("stopLoss") or 0)
            side = str(trade.get("side") or "").upper()
            if side == "LONG":
                current = max(db_sl, exchange_sl)
                should_move = tp1_price > current
                already_stricter = current > tp1_price
            elif side == "SHORT":
                current = min([x for x in (db_sl, exchange_sl) if x > 0] or [0.0])
                should_move = current <= 0 or tp1_price < current
                already_stricter = current > 0 and current < tp1_price
            else:
                raise RuntimeError(f"Unsupported side {side!r}")

            if not should_move:
                status = "NOT_NEEDED" if already_stricter else "APPLIED"
                await self.storage.set_tp2_lock_status(
                    trade["id"], status, tp1_price
                )
                return (
                    f"\n🛡️ SL kept at `{current:.10g}` "
                    f"(already {'better than' if already_stricter else 'at'} TP1 `{tp1_price:.10g}`)"
                )

            await self._set_and_verify_stop(trade["symbol"], side, tp1_price)
            await self.storage.update_sl(
                trade["id"], tp1_price, "TP2 full fill -> SL at TP1"
            )
            await self.storage.set_tp2_lock_status(
                trade["id"], "APPLIED", tp1_price
            )
            await self.storage.event(
                "TP2_SL_TO_TP1", trade["symbol"], trade["id"],
                f"SL moved to TP1 {tp1_price:.10g} after full TP2 fill",
            )
            return f"\n🛡️ SL → **TP1** `{tp1_price:.10g}`"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.exception("TP2-to-TP1 protection failed %s", trade["symbol"])
            await self.storage.set_tp2_lock_status(
                trade["id"], "FAILED", None, error
            )
            await self.storage.event(
                "TP2_SL_TO_TP1_FAILED", trade["symbol"], trade["id"], error,
            )
            return "\n⚠️ TP2 filled, but SL-to-TP1 update failed; retry scheduled"

    async def _finalize_flat_trade(self, trade: dict) -> bool:
        await self._sync_fills(trade)
        quantities = await self.storage.fill_quantities(trade["id"])
        entry_qty = quantities["entry"]
        exit_qty = quantities["exit"]
        tolerance = max(entry_qty * 1e-6, 1e-12)
        if entry_qty <= 0 or exit_qty + tolerance < entry_qty:
            await self.storage.mark_flat_syncing(
                trade["id"],
                str(trade.get("close_reason_requested") or self._infer_close_reason(trade)),
                f"Waiting for complete execution history: entry={entry_qty:.12g} exit={exit_qty:.12g}",
            )
            return False
        refreshed = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],)) or trade
        reason = str(refreshed.get("close_reason_requested") or self._infer_close_reason(refreshed))
        await self.storage.close_trade(
            trade["id"], reason, str(refreshed.get("note") or "Flat and fills complete")
        )
        final = await self.storage._one("SELECT * FROM trades WHERE id=?", (trade["id"],))
        net = float(final["net_pnl_usdt"] or 0)
        risk = float(final["risk_usdt"] or 0)
        rr = net / risk if risk else 0
        await self.storage.event("CLOSED", trade["symbol"], trade["id"], reason)
        await self.notifier.send(
            f"🏁 **DEMO CLOSED — {trade['symbol']} {trade['side']}**\n"
            f"Reason **{reason}** · TP1 **{'✅' if final['tp1_hit'] else '—'}** · "
            f"TP2 **{'✅' if final['tp2_hit'] else '—'}** · TP3 **{'✅' if final['tp3_hit'] else '—'}**\n"
            f"Gross **{float(final['gross_pnl_usdt'] or 0):+.2f} USDT** · "
            f"fees **{float(final['fees_usdt'] or 0):.2f}** · Net **{net:+.2f} USDT** · **{rr:+.2f}R**"
        )
        return True

    async def _backfill_incomplete_closed(self) -> int:
        repaired = 0
        for trade in await self.storage.closed_for_backfill():
            before = await self.storage.fill_quantities(trade["id"])
            tolerance = max(before["entry"] * 1e-6, 1e-12)
            if before["entry"] > 0 and before["exit"] + tolerance >= before["entry"]:
                continue
            await self._sync_fills(trade)
            after = await self.storage.fill_quantities(trade["id"])
            tolerance = max(after["entry"] * 1e-6, 1e-12)
            if (
                after["entry"] > 0
                and after["exit"] + tolerance >= after["entry"]
                and after != before
            ):
                repaired += 1
                await self.storage.event(
                    "CLOSED_FILLS_BACKFILLED", trade["symbol"], trade["id"],
                    f"entry={after['entry']:.12g} exit={after['exit']:.12g}",
                )
        if repaired:
            await self.notifier.send(
                f"✅ **DEMO HISTORY REPAIRED**\n"
                f"Complete fills/PnL restored for **{repaired}** closed trade(s)."
            )
        return repaired

    async def _sync_fills(self, trade: dict):
        received_ms = int(float(trade.get("received_at") or time.time()) * 1000)
        start_ms = max(0, received_ms - 1000)
        closed_s = float(trade.get("closed_at") or trade.get("close_detected_at") or 0)
        end_ms = None
        if closed_s > 0:
            end_ms = min(int(time.time() * 1000), int((closed_s + 60) * 1000))
        try:
            rows = await self.bybit.executions(trade["symbol"], start_ms, end_ms)
        except Exception:
            log.exception("Execution sync failed %s", trade["symbol"])
            return
        relevant_links = {
            trade.get("entry_link_id"), trade.get("tp1_link_id"), trade.get("tp2_link_id"), trade.get("tp3_link_id")
        }
        trade_prefix = f"BDT{trade['id']}-"
        for x in rows:
            if int(x.get("execTime") or 0) < received_ms:
                continue
            link = x.get("orderLinkId")
            # TP/entry are linked. SL generated by trading-stop may not carry our link; include closing executions
            # during this trade only when they close size and symbol matches.
            closed_size = float(x.get("closedSize") or 0)
            if link in relevant_links or str(link or "").startswith(trade_prefix) or closed_size > 0:
                await self.storage.add_fill(trade["id"], x)
        await self.storage.recalc_pnl(trade["id"])
        await self.storage.note_fill_sync(trade["id"])

    async def _wait_position(self, symbol: str, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            pos = await self.bybit.position(symbol)
            if pos and float(pos.get("size") or 0) > 0:
                return pos
            await asyncio.sleep(0.5)
        return None

    async def _wait_flat(self, symbol: str, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            if not await self.bybit.position(symbol):
                return True
            await asyncio.sleep(0.5)
        return False

    @staticmethod
    def _infer_close_reason(trade: dict) -> str:
        if trade.get("tp3_hit"):
            return "TP3"
        if trade.get("tp2_hit"):
            return "AFTER_TP2"
        if trade.get("tp1_hit"):
            return "AFTER_TP1"
        return "SL_OR_MANUAL"

    @staticmethod
    def _link(trade_id: int, suffix: str) -> str:
        # <=36 chars required by Bybit.
        return f"BDT{trade_id}-{suffix}"[:36]

    @staticmethod
    def _attempt_link(trade_id: int, suffix: str) -> str:
        # Unique retry IDs avoid an ambiguous timed-out close being rejected as
        # an orderLinkId duplicate. reduceOnly/closeOnTrigger still prevents entry.
        stamp = time.time_ns() % 10_000_000_000
        return f"BDT{trade_id}-{suffix}-{stamp}"[:36]
