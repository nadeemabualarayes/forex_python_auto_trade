"""Idea 1: passive (limit-order) entries instead of market orders, tick-exact, 130 days of XAUUSD ticks.

PRE-REGISTERED 2026-09-18 before the first run.
  Signal   the live scalper rule as shipped (M1 Bollinger touch + RSI 35/65, no candle/trend filter) on M1 bars
           built from the ticks (bars_m1t.npy, validated against the broker's own M1 bars).
  Baseline market entry at the first tick >= bar close + 1 s (BUY at ask, SELL at bid)  -> pays the spread.
  Passive  at that same tick place a limit order on the OTHER side of the spread:
             BUY LIMIT at bid - offset  (MT5 fills a buy limit when ask <= limit)
             SELL LIMIT at ask + offset (fills when bid >= limit)
           offsets 0 and 10 points; the order is cancelled if unfilled after 60 s or 180 s.
  Exits    broker-side +$1.50 / -$2.00 from the FILL price (and +$2 / -$2), tick-exact as before.
  Rules    one position at a time, spread cap 45 points at signal time, weekdays, all hours, no breakers.
  Verdict  a cell counts only if PF > 1 on the whole window AND in both halves, with >= 200 trades per half.
  Extra    fill rate, and the P&L the SAME signals would have made with a market entry (adverse selection check).
  Not modelled: partial fills, queue position (a limit at the touch is assumed filled as soon as the far quote
  reaches it, which is optimistic), commission/swap, latency beyond 1 s.
"""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from engines import scalper_analyse                      # noqa: E402
from strategy import generate_signal                     # noqa: E402

CACHE = os.path.join(ROOT, "logs", "backtest_cache")
POINT, SPREAD_CAP = 0.01, 45


def signals():
    df = pd.DataFrame(np.load(os.path.join(CACHE, "bars_m1t.npy")))
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = scalper_analyse(df)
    out = []
    for row in df.to_dict("records"):
        if np.isnan(row["atr"]) or np.isnan(row["rsi"]):
            continue
        side = generate_signal(row)
        if side:
            out.append((int(row["time"].value // 1_000_000) + 61_000, side == "BUY"))
    return out


def first_hit(series, start, hi, lo, stop=None, step=50000):
    n = len(series) if stop is None else min(stop, len(series))
    while start < n:
        chunk = series[start:min(start + step, n)]
        hit = np.flatnonzero((chunk >= hi) | (chunk <= lo))
        if len(hit):
            return start + int(hit[0])
        start += step
    return None


def exit_pnl(is_buy, entry, f, bid, ask, tp, sl):
    """Tick-exact broker-side exit from fill index f. Returns (pnl, exit index) or None at end of data."""
    if is_buy:
        j = first_hit(bid, f + 1, entry + tp, entry - sl)
        if j is None:
            return None
        return (tp if bid[j] >= entry + tp else float(bid[j]) - entry), j
    j = first_hit(ask, f + 1, entry + sl, entry - tp)
    if j is None:
        return None
    return (tp if ask[j] <= entry - tp else entry - float(ask[j])), j


def replay(sigs, t_msc, bid, ask, mode, offset_pts, window_s, tp, sl):
    trades, busy_until, placed = [], 0, 0
    for want, is_buy in sigs:
        if want <= busy_until:
            continue
        k = int(np.searchsorted(t_msc, want))
        if k >= len(t_msc) or t_msc[k] - want > 30_000:
            continue
        if datetime.utcfromtimestamp(t_msc[k] / 1000).weekday() > 4 or (ask[k] - bid[k]) / POINT > SPREAD_CAP:
            continue
        placed += 1
        if mode == "market":
            f, entry = k, float(ask[k] if is_buy else bid[k])
        else:
            deadline = int(np.searchsorted(t_msc, want + window_s * 1000))
            if is_buy:
                limit = float(bid[k]) - offset_pts * POINT
                f = first_hit(ask, k + 1, np.inf, limit, stop=deadline)
            else:
                limit = float(ask[k]) + offset_pts * POINT
                f = first_hit(bid, k + 1, limit, -np.inf, stop=deadline)
            if f is None:
                continue
            entry = limit
            busy_until = int(t_msc[f])
        res = exit_pnl(is_buy, entry, f, bid, ask, tp, sl)
        if res is None:
            break
        pnl, j = res
        busy_until = int(t_msc[j])
        # what a market entry at signal time would have done for this same signal (adverse-selection check)
        mkt = exit_pnl(is_buy, float(ask[k] if is_buy else bid[k]), k, bid, ask, tp, sl)
        trades.append((pd.Timestamp(t_msc[k], unit="ms"), pnl, mkt[0] if mkt else np.nan, (t_msc[f] - t_msc[k]) / 1000))
    return pd.DataFrame(trades, columns=["time", "pnl", "pnl_market", "fill_s"]), placed


def pf(p):
    gl = -p[p <= 0].sum()
    return p[p > 0].sum() / gl if gl > 0 else 9.99


def stats(df):
    if len(df) < 5:
        return f"{len(df):5d} trades"
    p = df["pnl"]
    eq = p.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    return (f"{len(df):5d} tr  win {100 * (p > 0).mean():4.1f}%  net {p.sum():+8.2f}  PF {pf(p):4.2f}  "
            f"avg {p.mean():+.3f}  DD {dd:6.2f}")


def main():
    z = np.load(os.path.join(CACHE, "ticks_long.npz"))
    t_msc, bid, ask = z["t_msc"], z["bid"], z["ask"]
    sigs = signals()
    first, last = pd.Timestamp(t_msc[0], unit="ms"), pd.Timestamp(t_msc[-1], unit="ms")
    mid = first + (last - first) / 2
    print(f"ticks {len(t_msc):,}  {first} -> {last} | halves split at {mid:%Y-%m-%d} | raw signals {len(sigs)}\n")
    passed = []
    for tp, sl in ((1.5, 2.0), (2.0, 2.0)):
        print(f"===== exits +{tp} / -{sl}")
        cells = [("market", 0, 0)] + [("limit", o, w) for o in (0, 10) for w in (60, 180)]
        for mode, off, win in cells:
            df, placed = replay(sigs, t_msc, bid, ask, mode, off, win, tp, sl)
            a, b = df[df["time"] < mid], df[df["time"] >= mid]
            name = "MARKET entry" if mode == "market" else f"LIMIT at touch{'' if off == 0 else f' -{off}pt'}, cancel {win:3d}s"
            print(f"{name:<32} ALL {stats(df)}   filled {len(df)}/{placed} ({100 * len(df) / max(placed, 1):.0f}%)")
            print(f"{'':32} H1  {stats(a)}")
            print(f"{'':32} H2  {stats(b)}")
            if mode == "limit" and len(df):
                m = df["pnl_market"].dropna()
                print(f"{'':32} same signals with market entry: net {m.sum():+8.2f} PF {pf(m):4.2f}  "
                      f"| median fill after {df['fill_s'].median():.0f}s")
            if len(a) >= 200 and len(b) >= 200 and min(pf(df['pnl']), pf(a['pnl']), pf(b['pnl'])) > 1:
                passed.append(f"+{tp}/-{sl} {name}")
        print()
    print("PASSED the pre-registered rule (PF > 1 whole + both halves, >= 200 trades per half):", passed or "none")


if __name__ == "__main__":
    main()
