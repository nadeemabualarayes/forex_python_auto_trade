"""Tick microstructure study: is there a state, observable in the first seconds AFTER an M1 signal and BEFORE
entering, under which +$1 is reached clearly before -$1?

PRE-REGISTERED 2026-09-18 (user-specified design), before the first run.
  Signals    the live scalper rule as shipped, M1 bars built from ticks, 130 days (9,434 signals).
  Horizons   h = 1, 3, 5, 10, 30, 60 s after the signal time T (bar close + 1 s). Nothing is decided before T+h.
  Features   computed on the ticks in (T, T+h], all in the SIGNAL direction (positive = in our favour):
               move     mid(T+h) - mid(T), points
               mfe/mae  best / worst mid excursion in the window, points
               range    high - low of mid in the window, as a multiple of the M1 ATR at the signal
               ticks    number of quote updates in the window (activity)
               spread   spread at T+h minus spread at T, points
               contin   share of non-zero mid changes that went in our favour (0..1): continuous vs choppy
  Decision   at T+h we enter AT MARKET at the T+h quote (BUY at ask / SELL at bid). Outcomes measured from THAT
             price, never from the signal price, so no look-ahead:
               A  +$1.00 before -$1.00        B  +$1.50 before -$2.00      (0.01 lot: $1 per 1.00 move)
  Test       every feature is split into quintiles (per horizon); for each quintile: n, win rate, avg $/trade, PF,
             separately for the first and second half of the window. Baseline = all signals at that horizon.
  Verdict    a cell counts only if avg $/trade > 0 (PF > 1) in BOTH halves with >= 300 trades per half, AND the
             quintiles trend monotonically (the effect is not a single lucky bucket). Roughly 6 x 6 x 5 x 2 = 360
             cells are examined, so a handful of PF ~1.05 cells is what pure chance produces; only clear,
             consistent separation counts. A strongly NEGATIVE cell in both halves is reported too (it would mean
             fading the signal in that state).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from passive_entry_tick_backtest import first_hit, CACHE, POINT, SPREAD_CAP   # noqa: E402

HORIZONS = (1, 3, 5, 10, 30, 60)
EXITS = {"A +1/-1": (1.0, 1.0), "B +1.5/-2": (1.5, 2.0)}


def signals_with_atr():
    from engines import scalper_analyse
    from strategy import generate_signal
    df = pd.DataFrame(np.load(os.path.join(CACHE, "bars_m1t.npy")))
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = scalper_analyse(df)
    out = []
    for row in df.to_dict("records"):
        if np.isnan(row["atr"]) or np.isnan(row["rsi"]):
            continue
        side = generate_signal(row)
        if side:
            out.append((int(row["time"].value // 1_000_000) + 61_000, 1.0 if side == "BUY" else -1.0, row["atr"]))
    return out


def outcome(is_buy, entry, f, bid, ask, tp, sl):
    if is_buy:
        j = first_hit(bid, f + 1, entry + tp, entry - sl)
        return None if j is None else (tp if bid[j] >= entry + tp else float(bid[j]) - entry)
    j = first_hit(ask, f + 1, entry + sl, entry - tp)
    return None if j is None else (tp if ask[j] <= entry - tp else entry - float(ask[j]))


def build(sigs, t_msc, bid, ask):
    mid = (bid.astype(np.float64) + ask) / 2
    spread = (ask.astype(np.float64) - bid) / POINT
    rows = []
    for want, d, atr in sigs:
        k = int(np.searchsorted(t_msc, want))
        if k >= len(t_msc) or t_msc[k] - want > 30_000 or spread[k] > SPREAD_CAP:
            continue
        if pd.Timestamp(t_msc[k], unit="ms").weekday() > 4:
            continue
        base = {"time": pd.Timestamp(t_msc[k], unit="ms"), "dir": d}
        for h in HORIZONS:
            e = int(np.searchsorted(t_msc, t_msc[k] + h * 1000, side="right")) - 1   # last tick at/before T+h
            if e <= k:
                e = k                                                                   # no new quote: state unchanged
            w = mid[k:e + 1]
            dm = np.diff(w) * d
            nz = dm[dm != 0]
            r = dict(base, h=h,
                     move=(mid[e] - mid[k]) * d / POINT,
                     mfe=(w * d).max() * 1 - mid[k] * d if len(w) else 0.0,
                     mae=mid[k] * d - (w * d).min() if len(w) else 0.0,
                     range=(w.max() - w.min()) / atr if atr > 0 else np.nan,
                     ticks=e - k,
                     spread=spread[e] - spread[k],
                     contin=(nz > 0).mean() if len(nz) else np.nan)
            r["mfe"], r["mae"] = r["mfe"] / POINT, r["mae"] / POINT
            entry = float(ask[e]) if d > 0 else float(bid[e])
            for name, (tp, sl) in EXITS.items():
                r[name] = outcome(d > 0, entry, e, bid, ask, tp, sl)
            rows.append(r)
    return pd.DataFrame(rows)


def cell(p):
    p = p.dropna()
    if len(p) == 0:
        return (0, np.nan, np.nan, np.nan)
    gl = -p[p <= 0].sum()
    return (len(p), 100 * (p > 0).mean(), p.mean(), p[p > 0].sum() / gl if gl > 0 else 9.99)


def main():
    z = np.load(os.path.join(CACHE, "ticks_long.npz"))
    t_msc, bid, ask = z["t_msc"], z["bid"], z["ask"]
    sigs = signals_with_atr()
    df = build(sigs, t_msc, bid, ask)
    mid_t = df["time"].min() + (df["time"].max() - df["time"].min()) / 2
    df["half"] = np.where(df["time"] < mid_t, 1, 2)
    df.to_pickle(os.path.join(CACHE, "microstructure_rows.pkl"))
    print(f"signals {df['time'].nunique()} | rows {len(df)} | halves split {mid_t:%Y-%m-%d}\n")

    print("=== BASELINE: enter at market at T+h, all signals (n, win%, avg $, PF) per half")
    for ex in EXITS:
        for h in HORIZONS:
            g = df[df["h"] == h]
            c1, c2 = cell(g[g["half"] == 1][ex]), cell(g[g["half"] == 2][ex])
            print(f"  {ex:<10} h={h:2d}s  H1 n={c1[0]:4d} win {c1[1]:4.1f}% avg {c1[2]:+.3f} PF {c1[3]:4.2f}   "
                  f"H2 n={c2[0]:4d} win {c2[1]:4.1f}% avg {c2[2]:+.3f} PF {c2[3]:4.2f}")
    print()

    features = ["move", "mfe", "mae", "range", "ticks", "spread", "contin"]
    hits, fades = [], []
    for h in HORIZONS:
        g = df[df["h"] == h].copy()
        print(f"=== horizon {h}s: quintile Q1 (lowest) .. Q5 (highest) -> avg $/trade for exit A | exit B, per half")
        for feat in features:
            x = g[feat]
            if x.nunique() < 5:
                q = pd.qcut(x.rank(method="first"), 5, labels=False)
            else:
                q = pd.qcut(x.rank(method="first"), 5, labels=False)
            g["q"] = q
            line = f"  {feat:<7}"
            avgs = {ex: [] for ex in EXITS}
            for qi in range(5):
                sub = g[g["q"] == qi]
                lo, hi = sub[feat].min(), sub[feat].max()
                parts = []
                for ex in EXITS:
                    c1, c2 = cell(sub[sub["half"] == 1][ex]), cell(sub[sub["half"] == 2][ex])
                    avgs[ex].append((c1, c2))
                    parts.append(f"{c1[2]:+.2f}/{c2[2]:+.2f}")
                line += f"  Q{qi + 1}[{lo:6.2f}..{hi:6.2f}] " + " ".join(parts)
            print(line)
            for ex in EXITS:
                a = avgs[ex]
                means = [(c1[2] + c2[2]) / 2 for c1, c2 in a]
                mono = all(np.diff(means) >= 0) or all(np.diff(means) <= 0)
                for qi, (c1, c2) in enumerate(a):
                    ok_n = c1[0] >= 300 and c2[0] >= 300
                    if ok_n and c1[3] > 1 and c2[3] > 1 and mono and qi in (0, 4):
                        hits.append(f"h={h}s {feat} Q{qi + 1} {ex}: H1 PF {c1[3]:.2f} n={c1[0]}, H2 PF {c2[3]:.2f} n={c2[0]}")
                    if ok_n and c1[3] < 0.6 and c2[3] < 0.6 and mono and qi in (0, 4):
                        fades.append(f"h={h}s {feat} Q{qi + 1} {ex}: H1 PF {c1[3]:.2f}, H2 PF {c2[3]:.2f} (both strongly negative)")
        print()
    print("PASSED (PF > 1 both halves, n >= 300 each, monotonic, extreme quintile):", hits or "none")
    print("STRONGLY NEGATIVE in both halves (candidate to fade):", fades or "none")


if __name__ == "__main__":
    main()
