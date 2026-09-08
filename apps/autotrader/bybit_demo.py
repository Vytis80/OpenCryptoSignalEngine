from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

from pybit.unified_trading import HTTP

log = logging.getLogger(__name__)


def _ok(resp: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(resp, dict) or resp.get("retCode") != 0:
        raise RuntimeError(f"{label} failed: {resp}")
    return resp


class BybitDemo:
    """Hard-wired to Bybit mainnet Demo Trading. Never points at live trading."""

    def __init__(self, api_key: str, api_secret: str):
        self.http = HTTP(
            testnet=False,
            demo=True,
            api_key=api_key,
            api_secret=api_secret,
            recv_window=5000,
        )
        endpoint = getattr(self.http, "endpoint", "")
        if "api-demo.bybit.com" not in endpoint:
            raise RuntimeError(f"Safety guard: unexpected Bybit endpoint: {endpoint}")
        self.endpoint = endpoint

    async def server_time(self):
        return _ok(await asyncio.to_thread(self.http.get_server_time), "server_time")


    async def account_info(self) -> dict[str, Any]:
        r = _ok(await asyncio.to_thread(self.http.get_account_info), "account_info")
        return dict(r.get("result", {}) or {})

    async def ensure_isolated_margin(self) -> dict[str, Any]:
        """UTA 2.0 margin mode is account-level. Enforce isolated mode and verify it."""
        info = await self.account_info()
        if str(info.get("marginMode") or "").upper() != "ISOLATED_MARGIN":
            _ok(
                await asyncio.to_thread(
                    self.http.set_margin_mode,
                    setMarginMode="ISOLATED_MARGIN",
                ),
                "set_margin_mode",
            )
            info = await self.account_info()
        mode = str(info.get("marginMode") or "").upper()
        if mode != "ISOLATED_MARGIN":
            raise RuntimeError(f"Safety guard: expected ISOLATED_MARGIN, got {mode or 'UNKNOWN'}")
        return info

    async def wallet(self) -> dict[str, float]:
        """Return USDT wallet/equity and isolated-derivatives available balance.

        Bybit UTA isolated margin does not use account-level totalAvailableBalance
        for derivatives sizing. For isolated margin the usable USDT balance is
        walletBalance - totalPositionIM - totalOrderIM - locked - bonus.
        """
        r = _ok(
            await asyncio.to_thread(
                self.http.get_wallet_balance,
                accountType="UNIFIED",
                coin="USDT",
            ),
            "wallet",
        )
        rows = r.get("result", {}).get("list", [])
        if not rows:
            return {
                "equity": 0.0, "available": 0.0, "wallet": 0.0,
                "position_im": 0.0, "order_im": 0.0, "locked": 0.0,
                "bonus": 0.0,
            }

        x = rows[0]
        coins = x.get("coin", []) or []
        usdt = next((c for c in coins if str(c.get("coin") or "").upper() == "USDT"), {})

        def num(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        wallet_balance = num(usdt.get("walletBalance"))
        position_im = num(usdt.get("totalPositionIM"))
        order_im = num(usdt.get("totalOrderIM"))
        locked = num(usdt.get("locked"))
        bonus = num(usdt.get("bonus"))
        available = max(0.0, wallet_balance - position_im - order_im - locked - bonus)

        return {
            "equity": num(x.get("totalEquity")) or num(usdt.get("equity")),
            "available": available,
            "wallet": wallet_balance,
            "position_im": position_im,
            "order_im": order_im,
            "locked": locked,
            "bonus": bonus,
        }

    async def ticker(self, symbol: str) -> float:
        r = _ok(await asyncio.to_thread(self.http.get_tickers, category="linear", symbol=symbol), "ticker")
        rows = r.get("result", {}).get("list", [])
        if not rows:
            raise RuntimeError(f"No ticker for {symbol}")
        return float(rows[0]["lastPrice"])

    async def instrument(self, symbol: str) -> dict[str, Any]:
        r = _ok(await asyncio.to_thread(self.http.get_instruments_info, category="linear", symbol=symbol), "instrument")
        rows = r.get("result", {}).get("list", [])
        if not rows:
            raise RuntimeError(f"No linear instrument {symbol}")
        return rows[0]

    async def position(self, symbol: str) -> dict[str, Any] | None:
        r = _ok(await asyncio.to_thread(self.http.get_positions, category="linear", symbol=symbol), "position")
        for x in r.get("result", {}).get("list", []):
            if x.get("symbol") == symbol and float(x.get("size") or 0) > 0:
                return x
        return None

    async def positions(self) -> list[dict[str, Any]]:
        """Return every non-flat USDT linear position, following Bybit cursors."""
        out: list[dict[str, Any]] = []
        cursor = ""
        while True:
            kwargs: dict[str, Any] = {
                "category": "linear",
                "settleCoin": "USDT",
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            r = _ok(
                await asyncio.to_thread(self.http.get_positions, **kwargs),
                "positions",
            )
            result = r.get("result", {}) or {}
            out.extend(
                x for x in result.get("list", []) or []
                if float(x.get("size") or 0) > 0
            )
            cursor = str(result.get("nextPageCursor") or "")
            if not cursor:
                return out

    async def set_leverage(self, symbol: str, leverage: float):
        leverage_text = format(Decimal(str(leverage)).normalize(), "f")
        try:
            return _ok(
                await asyncio.to_thread(
                    self.http.set_leverage,
                    category="linear",
                    symbol=symbol,
                    buyLeverage=leverage_text,
                    sellLeverage=leverage_text,
                ),
                "set_leverage",
            )
        except Exception as e:
            # Bybit may return "leverage not modified" when already set. Let caller decide only on real errors.
            text = str(e).lower()
            if "not modified" in text or "same leverage" in text:
                return {"retCode": 0, "retMsg": "already set"}
            raise

    async def set_auto_add_margin(self, symbol: str, enabled: bool = False):
        try:
            return _ok(
                await asyncio.to_thread(
                    self.http.set_auto_add_margin,
                    category="linear",
                    symbol=symbol,
                    autoAddMargin=1 if enabled else 0,
                    positionIdx=0,
                ),
                "set_auto_add_margin",
            )
        except Exception as e:
            text = str(e).lower()
            if "auto add margin not modified" in text or "not modified" in text:
                return {"retCode": 0, "retMsg": "already set"}
            raise

    async def add_margin(self, symbol: str, margin_usdt: float):
        if margin_usdt <= 0:
            raise ValueError("margin_usdt must be >0")
        # Bybit supports up to 4 decimals for manual isolated-margin adjustment.
        margin = f"{margin_usdt:.4f}".rstrip("0").rstrip(".")
        return _ok(
            await asyncio.to_thread(
                self.http.add_or_reduce_margin,
                category="linear",
                symbol=symbol,
                margin=margin,
                positionIdx=0,
            ),
            "add_margin",
        )

    async def place_market_entry(
        self,
        symbol: str,
        side: str,
        qty: str,
        link_id: str,
        stop_loss: float,
        sl_trigger_by: str,
    ):
        # Attach the initial stop to the entry request. The executor verifies and
        # re-applies it after the position appears, but there is no avoidable
        # post-fill interval where protection has not even been requested.
        return _ok(
            await asyncio.to_thread(
                self.http.place_order,
                category="linear",
                symbol=symbol,
                side="Buy" if side == "LONG" else "Sell",
                orderType="Market",
                qty=qty,
                positionIdx=0,
                reduceOnly=False,
                orderLinkId=link_id,
                stopLoss=str(stop_loss),
                slTriggerBy=sl_trigger_by,
            ),
            "place_market_entry",
        )

    async def set_full_stop(self, symbol: str, stop_loss: float, trigger_by: str):
        try:
            return _ok(
                await asyncio.to_thread(
                    self.http.set_trading_stop,
                    category="linear",
                    symbol=symbol,
                    tpslMode="Full",
                    positionIdx=0,
                    stopLoss=str(stop_loss),
                    slTriggerBy=trigger_by,
                ),
                "set_full_stop",
            )
        except Exception as e:
            # Bybit ErrCode 34040 means the requested stop is already set.
            # Treat this as idempotent success; executor immediately reads the
            # position back and verifies the actual stopLoss value.
            text = str(e).lower()
            if "34040" in text or "not modified" in text:
                return {"retCode": 0, "retMsg": "stop already set"}
            raise

    async def place_reduce_trigger(
        self,
        symbol: str,
        position_side: str,
        qty: str,
        trigger_price: float,
        trigger_by: str,
        link_id: str,
    ):
        # LONG TP triggers on rise; SHORT TP triggers on fall.
        trigger_direction = 1 if position_side == "LONG" else 2
        close_side = "Sell" if position_side == "LONG" else "Buy"
        return _ok(
            await asyncio.to_thread(
                self.http.place_order,
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=qty,
                triggerPrice=str(trigger_price),
                triggerDirection=trigger_direction,
                triggerBy=trigger_by,
                positionIdx=0,
                reduceOnly=True,
                closeOnTrigger=True,
                orderLinkId=link_id,
            ),
            "place_reduce_trigger",
        )

    async def close_market(self, symbol: str, side: str, link_id: str):
        close_side = "Sell" if side == "LONG" else "Buy"
        return _ok(
            await asyncio.to_thread(
                self.http.place_order,
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty="0",
                positionIdx=0,
                reduceOnly=True,
                closeOnTrigger=True,
                orderLinkId=link_id,
            ),
            "close_market",
        )

    async def open_orders(self, symbol: str | None = None):
        out: list[dict[str, Any]] = []
        cursor = ""
        while True:
            kwargs: dict[str, Any] = {"category": "linear", "openOnly": 0, "limit": 50}
            if symbol:
                kwargs["symbol"] = symbol
            else:
                kwargs["settleCoin"] = "USDT"
            if cursor:
                kwargs["cursor"] = cursor
            r = _ok(
                await asyncio.to_thread(self.http.get_open_orders, **kwargs),
                "open_orders",
            )
            result = r.get("result", {}) or {}
            out.extend(result.get("list", []) or [])
            cursor = str(result.get("nextPageCursor") or "")
            if not cursor:
                return out

    async def order_by_link(self, symbol: str, link_id: str) -> dict[str, Any] | None:
        """Find an order in realtime first and history second (which may lag)."""
        try:
            r = _ok(
                await asyncio.to_thread(
                    self.http.get_open_orders,
                    category="linear",
                    symbol=symbol,
                    orderLinkId=link_id,
                    openOnly=2,
                    limit=50,
                ),
                "order_realtime",
            )
            rows = r.get("result", {}).get("list", []) or []
            if rows:
                return rows[0]
        except Exception:
            log.exception("Realtime order lookup failed %s %s", symbol, link_id)
        r = _ok(
            await asyncio.to_thread(
                self.http.get_order_history,
                category="linear",
                symbol=symbol,
                orderLinkId=link_id,
                limit=50,
            ),
            "order_history",
        )
        rows = r.get("result", {}).get("list", []) or []
        return rows[0] if rows else None

    async def cancel_order(self, symbol: str, link_id: str):
        if not link_id:
            return None
        try:
            return _ok(
                await asyncio.to_thread(
                    self.http.cancel_order,
                    category="linear",
                    symbol=symbol,
                    orderLinkId=link_id,
                ),
                "cancel_order",
            )
        except Exception as e:
            text = str(e).lower()
            if any(x in text for x in ("order not exists", "order not found", "already cancelled", "already filled")):
                return None
            raise

    async def cancel_all(self, symbol: str):
        try:
            return _ok(await asyncio.to_thread(self.http.cancel_all_orders, category="linear", symbol=symbol), "cancel_all")
        except Exception:
            log.exception("cancel_all failed for %s", symbol)
            return None

    async def executions(
        self, symbol: str, start_ms: int, end_ms: int | None = None
    ) -> list[dict[str, Any]]:
        """Fetch all execution pages in <=7-day windows.

        Bybit caps each page at 100 and startTime-only queries to seven days.
        Windowing plus cursor traversal prevents silent fill/PnL truncation.
        """
        end_ms = int(time.time() * 1000) if end_ms is None else int(end_ms)
        window_ms = 7 * 24 * 60 * 60 * 1000 - 1
        out: dict[str, dict[str, Any]] = {}
        window_start = max(0, int(start_ms))
        while window_start <= end_ms:
            window_end = min(end_ms, window_start + window_ms)
            cursor = ""
            while True:
                kwargs: dict[str, Any] = {
                    "category": "linear",
                    "symbol": symbol,
                    "startTime": window_start,
                    "endTime": window_end,
                    "limit": 100,
                }
                if cursor:
                    kwargs["cursor"] = cursor
                r = _ok(
                    await asyncio.to_thread(self.http.get_executions, **kwargs),
                    "executions",
                )
                result = r.get("result", {}) or {}
                for row in result.get("list", []) or []:
                    exec_id = str(row.get("execId") or "")
                    if exec_id:
                        out[exec_id] = row
                cursor = str(result.get("nextPageCursor") or "")
                if not cursor:
                    break
            window_start = window_end + 1
        return sorted(out.values(), key=lambda x: int(x.get("execTime") or 0))

    @staticmethod
    def _floor_step(value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    @staticmethod
    def quantize_price(price: float, instrument: dict[str, Any]) -> float:
        tick = Decimal(str(instrument.get("priceFilter", {}).get("tickSize") or "0.00000001"))
        p = Decimal(str(price))
        q = (p / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        return float(q)

    @staticmethod
    def quantize_qty(raw_qty: float, instrument: dict[str, Any]) -> tuple[str, float, float, float]:
        lot = instrument.get("lotSizeFilter", {})
        step = Decimal(str(lot.get("qtyStep") or "0.001"))
        min_qty = Decimal(str(lot.get("minOrderQty") or step))
        min_notional = float(lot.get("minNotionalValue") or 0)
        q = BybitDemo._floor_step(Decimal(str(raw_qty)), step)
        used_minimum = False
        if q < min_qty:
            q = min_qty
            used_minimum = True
        text = format(q, "f")
        return text, float(q), min_notional, float(min_qty if used_minimum else 0)


    @staticmethod
    def quantize_qty_up(raw_qty: float, instrument: dict[str, Any]) -> tuple[str, float]:
        """Round quantity UP to qtyStep so a configured minimum notional is never rounded below its floor."""
        lot = instrument.get("lotSizeFilter", {})
        step = Decimal(str(lot.get("qtyStep") or "0.001"))
        min_qty = Decimal(str(lot.get("minOrderQty") or step))
        q = (Decimal(str(raw_qty)) / step).to_integral_value(rounding=ROUND_CEILING) * step
        if q < min_qty:
            q = min_qty
        return format(q, "f"), float(q)

    @staticmethod
    def split_qty(total_qty: float, fractions: tuple[float, float, float], instrument: dict[str, Any]) -> tuple[str, str, str]:
        lot = instrument.get("lotSizeFilter", {})
        step = Decimal(str(lot.get("qtyStep") or "0.001"))
        total = BybitDemo._floor_step(Decimal(str(total_qty)), step)
        q1 = BybitDemo._floor_step(total * Decimal(str(fractions[0])), step)
        q2 = BybitDemo._floor_step(total * Decimal(str(fractions[1])), step)
        q3 = total - q1 - q2
        min_qty = Decimal(str(lot.get("minOrderQty") or step))
        if q1 < min_qty or q2 < min_qty or q3 < min_qty:
            raise ValueError(
                f"Position qty {total} is too small for three TP slices; each must be >= {min_qty}"
            )
        return format(q1, "f"), format(q2, "f"), format(q3, "f")
