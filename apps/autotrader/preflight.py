from __future__ import annotations

import asyncio
from dotenv import load_dotenv

from bybit_demo import BybitDemo
from config import Config


async def main():
    load_dotenv()
    cfg = Config.from_env()
    api = BybitDemo(cfg.bybit_api_key, cfg.bybit_api_secret)
    await api.server_time()
    account = await api.ensure_isolated_margin()
    wallet = await api.wallet()
    btc = await api.instrument("BTCUSDT")
    px = await api.ticker("BTCUSDT")
    print("PRE-FLIGHT OK")
    print("Endpoint:", api.endpoint)
    print("Margin mode:", account.get("marginMode"))
    print("Leverage target:", f"{cfg.leverage}x; fallback to instrument maximum")
    print("Execution mode:", cfg.execution_mode)
    print("Maximum open positions:", cfg.max_open_positions)
    print("Minimum isolated margin:", f"{cfg.min_margin_usdt:.2f} USDT")
    print("Maximum minimum-notional floor:", f"{cfg.min_margin_usdt * cfg.leverage:.2f} USDT at target leverage")
    print("Smart Margin:", "ON" if cfg.smart_margin_enabled else "OFF")
    print("Smart Margin max extra:", f"{cfg.smart_margin_max_extra_ratio*100:.0f}% of initial margin")
    print("Liquidation buffer:", f"{cfg.smart_margin_buffer_stop_fraction*100:.0f}% of entry-to-SL distance")
    print("Demo equity:", f"{wallet['equity']:.2f} USDT")
    print("USDT wallet:", f"{wallet['wallet']:.2f} USDT")
    print("USDT position IM:", f"{wallet.get('position_im',0):.2f} USDT")
    print("USDT order IM:", f"{wallet.get('order_im',0):.2f} USDT")
    print("USDT locked:", f"{wallet.get('locked',0):.2f} USDT")
    print("USDT bonus:", f"{wallet.get('bonus',0):.2f} USDT")
    print("Available for isolated derivatives:", f"{wallet['available']:.2f} USDT")
    print("BTCUSDT last:", px)
    print("BTCUSDT qtyStep:", btc.get("lotSizeFilter", {}).get("qtyStep"))
    print("BTCUSDT max leverage:", btc.get("leverageFilter", {}).get("maxLeverage"))
    print("No order was placed.")


if __name__ == "__main__":
    asyncio.run(main())
