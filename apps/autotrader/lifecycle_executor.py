"""AutoTrader runtime adapter for the shared exchange-independent risk lifecycle.

The base executor continues to own Bybit I/O, retries, persistence and Discord
messages. This subclass replaces only automatic TP milestone stop decisions so
those decisions come from ``open_crypto_signal_engine.risk``.
"""

from __future__ import annotations

import logging
import time

from executor import DemoExecutor
from open_crypto_signal_engine.risk import (
    evaluate_post_tp_protection,
    is_stricter_stop,
)

log = logging.getLogger(__name__)


class LifecycleDemoExecutor(DemoExecutor):
    """Demo executor whose automatic TP protection follows the shared contract."""

    @staticmethod
    def _risk_side(side: str) -> str:
        normalized = str(side or "").upper()
        if normalized in {"LONG", "BUY"}:
            return "LONG"
        if normalized in {"SHORT", "SELL"}:
            return "SHORT"
        raise RuntimeError(f"Unsupported side {side!r}")

    @classmethod
    def _strictest_current_stop(
        cls,
        side: str,
        db_stop: float,
        exchange_stop: float,
    ) -> float | None:
        """Return the stricter positive stop persisted locally or on exchange."""

        risk_side = cls._risk_side(side)
        values = [float(value) for value in (db_stop, exchange_stop) if float(value) > 0]
        if not values:
            return None
        current = values[0]
        for candidate in values[1:]:
            if is_stricter_stop(risk_side, candidate, current):
                current = candidate
        return current

    async def _restore_monotonic_stop(self, trade: dict, pos: dict):
        """Reconcile DB/exchange SL without ever adopting weaker protection."""

        db_sl = float(trade.get("sl") or 0)
        actual_sl = float(pos.get("stopLoss") or 0)
        side = self._risk_side(str(trade.get("side") or ""))
        if db_sl <= 0:
            raise RuntimeError("DB stop is missing")

        if actual_sl <= 0 or is_stricter_stop(side, db_sl, actual_sl):
            await self._set_and_verify_stop(trade["symbol"], side, db_sl)
            return
        if is_stricter_stop(side, actual_sl, db_sl):
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
                pos.get("avgPrice")
                or trade.get("avg_entry")
                or trade.get("entry_signal")
                or 0
            )
            if actual_entry <= 0:
                raise RuntimeError("Average entry is unavailable")

            instrument = await self.bybit.instrument(trade["symbol"])
            be_price = self.bybit.quantize_price(actual_entry, instrument)
            tp1_price = self.bybit.quantize_price(
                float(trade.get("tp1") or 0), instrument
            )
            side = self._risk_side(str(trade.get("side") or ""))
            current = self._strictest_current_stop(
                side,
                float(trade.get("sl") or 0),
                float(pos.get("stopLoss") or 0),
            )
            decision = evaluate_post_tp_protection(
                side,
                be_price,
                tp1_price,
                tp1_hit=True,
                tp2_hit=False,
                current_stop=current,
            )

            if not decision.move_stop:
                kept = decision.effective_stop
                await self.storage.set_be_status(
                    trade["id"],
                    "NOT_NEEDED",
                    be_price,
                    "SL already at or stricter than breakeven",
                )
                return (
                    f"\n🛡️ SL kept at `{kept:.10g}` "
                    f"(already at/better than entry `{be_price:.10g}`)"
                )

            new_stop = decision.effective_stop
            await self._set_and_verify_stop(trade["symbol"], side, new_stop)
            await self.storage.update_sl(
                trade["id"], new_stop, "TP1 full fill -> breakeven"
            )
            await self.storage.set_be_status(
                trade["id"], "APPLIED", new_stop, "TP1 full fill -> breakeven"
            )
            await self.storage.event(
                "TP1_SL_TO_ENTRY",
                trade["symbol"],
                trade["id"],
                f"SL moved to actual avg entry {new_stop:.10g}",
            )
            return f"\n🛡️ SL → **BREAKEVEN** `{new_stop:.10g}`"
        except Exception as e:
            log.exception("TP1 breakeven protection failed %s", trade["symbol"])
            await self.storage.set_be_status(
                trade["id"], "FAILED", None, f"{type(e).__name__}: {e}"
            )
            await self.storage.event(
                "TP1_SL_TO_ENTRY_FAILED",
                trade["symbol"],
                trade["id"],
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
            actual_entry = float(
                pos.get("avgPrice")
                or trade.get("avg_entry")
                or trade.get("entry_signal")
                or 0
            )
            if actual_entry <= 0:
                raise RuntimeError("Average entry is unavailable")

            instrument = await self.bybit.instrument(trade["symbol"])
            entry_price = self.bybit.quantize_price(actual_entry, instrument)
            tp1_price = self.bybit.quantize_price(
                float(trade.get("tp1") or 0), instrument
            )
            if tp1_price <= 0:
                raise RuntimeError("TP1 price is unavailable")

            side = self._risk_side(str(trade.get("side") or ""))
            current = self._strictest_current_stop(
                side,
                float(trade.get("sl") or 0),
                float(pos.get("stopLoss") or 0),
            )
            decision = evaluate_post_tp_protection(
                side,
                entry_price,
                tp1_price,
                tp1_hit=True,
                tp2_hit=True,
                current_stop=current,
            )

            if not decision.move_stop:
                kept = decision.effective_stop
                already_stricter = not abs(kept - tp1_price) <= max(
                    abs(tp1_price) * 1e-12, 1e-12
                )
                status = "NOT_NEEDED" if already_stricter else "APPLIED"
                await self.storage.set_tp2_lock_status(
                    trade["id"], status, tp1_price
                )
                return (
                    f"\n🛡️ SL kept at `{kept:.10g}` "
                    f"(already {'better than' if already_stricter else 'at'} "
                    f"TP1 `{tp1_price:.10g}`)"
                )

            new_stop = decision.effective_stop
            await self._set_and_verify_stop(trade["symbol"], side, new_stop)
            await self.storage.update_sl(
                trade["id"], new_stop, "TP2 full fill -> SL at TP1"
            )
            await self.storage.set_tp2_lock_status(
                trade["id"], "APPLIED", new_stop
            )
            await self.storage.event(
                "TP2_SL_TO_TP1",
                trade["symbol"],
                trade["id"],
                f"SL moved to TP1 {new_stop:.10g} after full TP2 fill",
            )
            return f"\n🛡️ SL → **TP1** `{new_stop:.10g}`"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.exception("TP2-to-TP1 protection failed %s", trade["symbol"])
            await self.storage.set_tp2_lock_status(
                trade["id"], "FAILED", None, error
            )
            await self.storage.event(
                "TP2_SL_TO_TP1_FAILED",
                trade["symbol"],
                trade["id"],
                error,
            )
            return "\n⚠️ TP2 filled, but SL-to-TP1 update failed; retry scheduled"
