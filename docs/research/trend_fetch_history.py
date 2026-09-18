"""Fetch a longer XAUUSD window for trend_tick_backtest.py: M5/M15/H1 bars + real ticks (compact arrays).

Attaches ONLY to the idle Program Files terminal by explicit path, never to the scalp terminal a bot drives."""
import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYMBOL = "XAUUSD"
TICK_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 130
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", "backtest_cache")

if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
ti = mt5.terminal_info()
if "mt5_scalp" in ti.path.lower():
    mt5.shutdown()
    raise SystemExit("attached to the scalp terminal: refusing")
mt5.symbol_select(SYMBOL, True)

end = datetime.now(timezone.utc) + timedelta(days=1)
for name, tf in (("m5", mt5.TIMEFRAME_M5), ("m15", mt5.TIMEFRAME_M15), ("h1", mt5.TIMEFRAME_H1)):
    bars = mt5.copy_rates_range(SYMBOL, tf, end - timedelta(days=TICK_DAYS + 60), end)
    print(name, None if bars is None else (len(bars), datetime.utcfromtimestamp(int(bars["time"][0])),
                                           datetime.utcfromtimestamp(int(bars["time"][-1]))))
    np.save(os.path.join(OUT, f"bars_{name}.npy"), bars)

t_parts, b_parts, a_parts = [], [], []
day = end - timedelta(days=TICK_DAYS + 1)
while day < end:
    nxt = day + timedelta(days=1)
    t = mt5.copy_ticks_range(SYMBOL, day, nxt, mt5.COPY_TICKS_INFO)
    if t is not None and len(t):
        ok = (t["bid"] > 0) & (t["ask"] > 0)
        t_parts.append(t["time_msc"][ok].astype(np.int64))
        b_parts.append(t["bid"][ok].astype(np.float32))
        a_parts.append(t["ask"][ok].astype(np.float32))
    print(day.date(), 0 if t is None else len(t), flush=True)
    day = nxt
t_msc = np.concatenate(t_parts)
np.savez(os.path.join(OUT, "ticks_long.npz"), t_msc=t_msc, bid=np.concatenate(b_parts), ask=np.concatenate(a_parts))
print("ticks:", len(t_msc), datetime.utcfromtimestamp(t_msc[0] / 1000), "->", datetime.utcfromtimestamp(t_msc[-1] / 1000))
mt5.shutdown()
