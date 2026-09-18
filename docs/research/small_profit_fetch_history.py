"""Fetch XAUUSD M1 bars + real ticks into logs/backtest_cache/ for small_profit_tick_backtest.py.

Attaches ONLY to the idle evaluation terminal by explicit path, never to the scalp terminal the live bot
drives (attaching a second client to a bot's terminal coincided with that terminal exiting twice)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYMBOL = "XAUUSD"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 45
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", "backtest_cache")

if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
ti, ai = mt5.terminal_info(), mt5.account_info()
print("terminal:", ti.path, "| account:", ai.login if ai else None, ai.server if ai else None)
if "mt5_scalp" in ti.path.lower():
    mt5.shutdown()
    raise SystemExit("attached to the scalp terminal: refusing")
mt5.symbol_select(SYMBOL, True)
info = mt5.symbol_info(SYMBOL)
print("point", info.point, "contract", info.trade_contract_size, "stops_level", info.trade_stops_level)

end = datetime.now(timezone.utc) + timedelta(days=1)
start = end - timedelta(days=DAYS + 1)
bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, start, end)
print("M1 bars:", None if bars is None else len(bars))
np.save(os.path.join(OUT, "bars_m1.npy"), bars)

chunks, day = [], start
while day < end:
    nxt = day + timedelta(days=1)
    t = mt5.copy_ticks_range(SYMBOL, day, nxt, mt5.COPY_TICKS_INFO)
    n = 0 if t is None else len(t)
    if n:
        chunks.append(t[["time_msc", "bid", "ask"]])
    print(day.date(), n, flush=True)
    day = nxt
ticks = np.concatenate(chunks)
np.save(os.path.join(OUT, "ticks.npy"), ticks)
print("ticks:", len(ticks), datetime.utcfromtimestamp(ticks["time_msc"][0] / 1000), "->",
      datetime.utcfromtimestamp(ticks["time_msc"][-1] / 1000))
mt5.shutdown()
