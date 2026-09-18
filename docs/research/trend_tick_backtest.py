"""Tick-exact replay of trend-following entries on XAUUSD (data: trend_fetch_history.py).

PRE-REGISTERED before the first run (2026-09-18), re-implementing the 2026-09-06 bar-based spike whose code was
not kept. Signals on CLOSED bars, H1 EMA200 gate via the live technicals.attach_trend (no look-ahead):

  pullback(f, s)  up-trend = ema_f > ema_s and close > H1 EMA200. Entry BUY when the bar's low touched ema_f
                  (low <= ema_f) and it closed back above it (close > ema_f) with close > open. SELL mirrored.
  donchian(n)     BUY when close > highest high of the previous n bars and close > H1 EMA200. SELL mirrored.

Variants: M5 and M15; pullback 10/30 and 20/50; donchian 40 and 80. Exits, all broker-side and tick-exact:
  atr15_3   SL 1.5 ATR / TP 3 ATR        atr2_4   SL 2 ATR / TP 4 ATR        usd    +$1.50 / -$2.00 (small-profit)
One position at a time per variant, entry at the first tick >= bar close + 1 s, spread cap 45 points, weekdays,
all hours, no breakers. 0.01 lot: $1 per 1.00 move. Verdict rule: a variant counts only if PF > 1 in BOTH halves
of the window AND on the whole; anything else is noise. Not modelled: commission/swap, latency beyond 1 s, news.
"""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
import config                                            # noqa: E402
from technicals import compute_indicators, compute_trend, attach_trend   # noqa: E402

CACHE = os.path.join(ROOT, "logs", "backtest_cache")
POINT, SPREAD_CAP = 0.01, 45
BAR_MS = {"m1t": 60_000, "m5": 300_000, "m15": 900_000}   # m1t: M1 bars built from the ticks (broker M1 history is capped)


def bars(name):
    df = pd.DataFrame(np.load(os.path.join(CACHE, f"bars_{name}.npy")))
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def prepare(tf, h1):
    df = attach_trend(compute_indicators(bars(tf)), compute_trend(h1.copy()))
    for span in (10, 20, 30, 50):
        df[f"ema{span}"] = df["close"].ewm(span=span, adjust=False).mean()
    for n in (40, 80):
        df[f"hh{n}"] = df["high"].rolling(n).max().shift(1)
        df[f"ll{n}"] = df["low"].rolling(n).min().shift(1)
    return df


def pullback(df, f, s):
    ef, es, c, o, t = df[f"ema{f}"], df[f"ema{s}"], df["close"], df["open"], df["trend_ema"]
    buy = (ef > es) & (c > t) & (df["low"] <= ef) & (c > ef) & (c > o)
    sell = (ef < es) & (c < t) & (df["high"] >= ef) & (c < ef) & (c < o)
    return buy, sell


def donchian(df, n):
    c, t = df["close"], df["trend_ema"]
    return (c > df[f"hh{n}"]) & (c > t), (c < df[f"ll{n}"]) & (c < t)


def first_hit(series, start, hi, lo, step=50000):
    n = len(series)
    while start < n:
        chunk = series[start:start + step]
        hit = np.flatnonzero((chunk >= hi) | (chunk <= lo))
        if len(hit):
            return start + int(hit[0])
        start += step
    return None


def replay(df, buy, sell, bar_ms, exit_mode, t_msc, bid, ask):
    trades, busy_until = [], 0
    sig = df[(buy | sell) & df["atr"].notna() & df["trend_ema"].notna()]
    for time, is_buy, atr in zip(sig["time"], buy[sig.index], sig["atr"]):
        want = int(time.value // 1_000_000) + bar_ms + 1000
        if want <= busy_until:
            continue
        k = int(np.searchsorted(t_msc, want))
        if k >= len(t_msc) or t_msc[k] - want > 30_000:
            continue
        now = datetime.utcfromtimestamp(t_msc[k] / 1000)
        if now.weekday() > 4 or (ask[k] - bid[k]) / POINT > SPREAD_CAP:
            continue
        sl_d, tp_d = {"atr15_3": (1.5 * atr, 3 * atr), "atr2_4": (2 * atr, 4 * atr), "usd": (2.0, 1.5)}[exit_mode]
        if is_buy:
            entry = float(ask[k])
            j = first_hit(bid, k + 1, entry + tp_d, entry - sl_d)
            if j is None:
                break
            pnl = tp_d if bid[j] >= entry + tp_d else float(bid[j]) - entry
        else:
            entry = float(bid[k])
            j = first_hit(ask, k + 1, entry + sl_d, entry - tp_d)
            if j is None:
                break
            pnl = tp_d if ask[j] <= entry - tp_d else entry - float(ask[j])
        busy_until = int(t_msc[j])
        trades.append((now, pnl, pnl / sl_d))
    return pd.DataFrame(trades, columns=["time", "pnl", "r"])


def stats(df):
    if len(df) < 5:
        return f"{len(df):4d} trades"
    pnl = df["pnl"]
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    eq = pnl.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    return (f"{len(df):4d} tr  win {100 * (pnl > 0).mean():4.1f}%  net {pnl.sum():+8.2f}  PF {gp / gl if gl else 9.99:4.2f}  "
            f"avgR {df['r'].mean():+.3f}  worst {pnl.min():+6.2f}  DD {dd:6.2f}")


def main():
    z = np.load(os.path.join(CACHE, "ticks_long.npz"))
    t_msc, bid, ask = z["t_msc"], z["bid"], z["ask"]
    h1 = bars("h1")
    first, last = pd.Timestamp(t_msc[0], unit="ms"), pd.Timestamp(t_msc[-1], unit="ms")
    mid = first + (last - first) / 2
    print(f"ticks {len(t_msc):,}  {first} -> {last}  | halves split at {mid:%Y-%m-%d}")
    print(f"median spread {np.median((ask[::50] - bid[::50]) / POINT):.0f} points\n")
    passed = []
    for tf in (sys.argv[1:] or ("m5", "m15")):
        df = prepare(tf, h1)
        df = df[df["time"] >= first - pd.Timedelta(days=1)].reset_index(drop=True)
        rules = {"pullback 10/30": pullback(df, 10, 30), "pullback 20/50": pullback(df, 20, 50),
                 "donchian 40": donchian(df, 40), "donchian 80": donchian(df, 80)}
        for rule, (buy, sell) in rules.items():
            for exit_mode in ("atr15_3", "atr2_4", "usd"):
                tr = replay(df, buy, sell, BAR_MS[tf], exit_mode, t_msc, bid, ask)
                a, b = tr[tr["time"] < mid], tr[tr["time"] >= mid]
                print(f"{tf.upper():>3} {rule:<15} {exit_mode:<8} ALL {stats(tr)}")
                print(f"{'':28} H1  {stats(a)}")
                print(f"{'':28} H2  {stats(b)}")
                pf = lambda d: d["pnl"][d["pnl"] > 0].sum() / max(1e-9, -d["pnl"][d["pnl"] <= 0].sum())   # noqa: E731
                if len(a) >= 20 and len(b) >= 20 and min(pf(tr), pf(a), pf(b)) > 1:
                    passed.append(f"{tf} {rule} {exit_mode}")
    print("\nPASSED the pre-registered rule (PF > 1 whole + both halves, >= 20 trades per half):", passed or "none")


if __name__ == "__main__":
    main()
