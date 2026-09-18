"""Tick-exact replay of the small-profit profile over cached XAUUSD history (see small_profit_fetch_history.py).

Signals come from the LIVE code (engines.scalper_analyse + strategy.generate_signal, config as shipped) on closed
M1 bars. Everything after the signal uses real ticks: entry at the first tick >= bar close + 1 s (ask for BUY, bid
for SELL), spread cap and session filter at that tick, up to MAX_OPEN_POSITIONS stacked, broker-side dollar TP/SL
resolved tick by tick (BUY exits on bid, SELL on ask; TP fills at its price, SL at the tick that crossed it).
Breakers: trades/day, daily loss, loss streak. 0.01 lot: $1 per 1.00 move. Not modelled: order latency beyond
1 s, requotes, commission/swap, news.
"""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
import config                                            # noqa: E402
from engines import scalper_analyse                      # noqa: E402
from strategy import generate_signal                     # noqa: E402

CACHE = os.path.join(ROOT, "logs", "backtest_cache")
POINT, USD_PER_UNIT = 0.01, 1.0                          # gold, 0.01 lot (verified by the live bot's startup log)
OOS_END = pd.Timestamp("2026-09-07")                     # the filters were chosen on live trades from 09-07 on


def load():
    bars = pd.DataFrame(np.load(os.path.join(CACHE, "bars_m1.npy")))
    bars["time"] = pd.to_datetime(bars["time"], unit="s")
    ticks = np.load(os.path.join(CACHE, "ticks.npy"))
    ok = (ticks["bid"] > 0) & (ticks["ask"] > 0)
    ticks = ticks[ok]
    return bars, ticks["time_msc"].astype(np.int64), ticks["bid"].astype(float), ticks["ask"].astype(float)


def signals(bars):
    df = scalper_analyse(bars.copy())
    out = []
    for row in df.to_dict("records"):
        if np.isnan(row["atr"]) or np.isnan(row["rsi"]):
            continue
        side = generate_signal(row)
        if side:
            out.append((row["time"], side))
    return out


def first_hit(series, start, hi, lo, step=20000):
    """Index of the first tick at/after `start` with series >= hi or series <= lo; None if never."""
    n = len(series)
    while start < n:
        chunk = series[start:start + step]
        hit = np.flatnonzero((chunk >= hi) | (chunk <= lo))
        if len(hit):
            return start + int(hit[0])
        start += step
    return None


def replay(sigs, t_msc, bid, ask, neg_ask, tp_usd, sl_usd, max_open, blocked, spread_cap,
           max_day_loss, max_streak, max_trades):
    tp_d, sl_d = tp_usd / USD_PER_UNIT, sl_usd / USD_PER_UNIT
    trades, open_pos = [], []                            # open_pos: (exit_msc, pnl)
    day, entries, day_pnl, streak = None, 0, 0.0, 0
    skipped = {"cap_open": 0, "session": 0, "spread": 0, "breaker": 0, "no_tick": 0}

    for bar_time, side in sigs:
        want = int(bar_time.value // 1_000_000) + 61_000  # bar close + 1 s
        k = int(np.searchsorted(t_msc, want))
        if k >= len(t_msc) or t_msc[k] - want > 30_000:  # no quote within 30 s: market shut
            skipped["no_tick"] += 1
            continue
        now = datetime.utcfromtimestamp(t_msc[k] / 1000)
        if now.date() != day:
            day, entries, day_pnl, streak = now.date(), 0, 0.0, 0
        for pos in sorted(p for p in open_pos if p[0] <= t_msc[k]):   # settle what closed before this signal
            open_pos.remove(pos)
            day_pnl += pos[1]
            streak = streak + 1 if pos[1] < 0 else 0
        if len(open_pos) >= max_open:
            skipped["cap_open"] += 1
            continue
        if now.weekday() not in config.TRADING_WEEKDAYS or now.hour in blocked:
            skipped["session"] += 1
            continue
        if entries >= max_trades or day_pnl <= -max_day_loss or streak >= max_streak:
            skipped["breaker"] += 1
            continue
        spread_pts = (ask[k] - bid[k]) / POINT
        if spread_pts > spread_cap:
            skipped["spread"] += 1
            continue
        if side == "BUY":
            entry = ask[k]
            j = first_hit(bid, k + 1, entry + tp_d, entry - sl_d)
            if j is None:
                continue
            pnl = tp_usd if bid[j] >= entry + tp_d else (bid[j] - entry) * USD_PER_UNIT
        else:
            entry = bid[k]
            j = first_hit(neg_ask, k + 1, -(entry - tp_d), -(entry + sl_d))
            if j is None:
                continue
            pnl = tp_usd if ask[j] <= entry - tp_d else (entry - ask[j]) * USD_PER_UNIT
        entries += 1
        open_pos.append((int(t_msc[j]), round(pnl, 2)))
        trades.append(dict(time=now, side=side, spread=spread_pts, pnl=round(pnl, 2),
                           secs=(t_msc[j] - t_msc[k]) / 1000, hour=now.hour))
    return pd.DataFrame(trades), skipped


def stats(df):
    if df.empty:
        return "no trades"
    pnl = df["pnl"]
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    eq = pnl.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    days = df["time"].dt.date.nunique()
    return (f"{len(df):5d} trades ({len(df) / days:5.1f}/day)  win {100 * (pnl > 0).mean():5.1f}%  net {pnl.sum():+9.2f}  "
            f"PF {gp / gl if gl else float('inf'):4.2f}  avg {pnl.mean():+.3f}  worst {pnl.min():+.2f}  maxDD {dd:7.2f}")


def report(name, df):
    print(f"\n=== {name}")
    print("  all          ", stats(df))
    if df.empty:
        return
    print("  before 09-07 ", stats(df[df["time"] < OOS_END]), " <- out of sample")
    print("  from 09-07   ", stats(df[df["time"] >= OOS_END]), " <- period the filters were chosen on")


def main():
    bars, t_msc, bid, ask = load()
    neg_ask = -ask
    sigs = signals(bars)
    print(f"bars {len(bars)}  {bars['time'].iloc[0]} -> {bars['time'].iloc[-1]} | ticks {len(t_msc):,} | raw signals {len(sigs)}")
    print(f"median tick spread {np.median((ask - bid) / POINT):.0f} points")
    live = dict(tp_usd=config.EXIT_TP_USD, sl_usd=config.EXIT_SL_USD, max_open=config.MAX_OPEN_POSITIONS,
                blocked=config.SESSION_BLOCKED_HOURS, spread_cap=config.spread_limit("XAUUSD"),
                max_day_loss=config.MAX_DAILY_LOSS_USD, max_streak=config.MAX_CONSECUTIVE_LOSSES,
                max_trades=config.MAX_TRADES_PER_DAY)

    def run(**over):
        return replay(sigs, t_msc, bid, ask, neg_ask, **dict(live, **over))

    df, skipped = run()
    report(f"LIVE PROFILE  +{live['tp_usd']}/-{live['sl_usd']}, stack {live['max_open']}, 07-12 blocked, spread<=45", df)
    print("  skipped:", skipped)

    print("\n  by server hour block (live profile):")
    for lo, hi in ((0, 7), (7, 12), (12, 17), (17, 24)):
        print(f"    {lo:02d}-{hi:02d} ", stats(df[(df['hour'] >= lo) & (df['hour'] < hi)]))
    print("\n  by week (live profile):")
    for wk, g in df.groupby(df["time"].dt.to_period("W")):
        print(f"    {wk} ", stats(g))
    daily = df.groupby(df["time"].dt.date)["pnl"].sum()
    print(f"\n  days: {len(daily)}  green {int((daily > 0).sum())}  red {int((daily < 0).sum())}  "
          f"best {daily.max():+.2f}  worst {daily.min():+.2f}  median {daily.median():+.2f}")
    print(f"  holding time: median {df['secs'].median():.0f}s  90% under {df['secs'].quantile(0.9):.0f}s")

    off = dict(max_day_loss=1e9, max_streak=10**9, max_trades=10**9)
    report("same, breakers off (raw edge of the entries + exits)", run(**off)[0])
    report("no stacking (1 position), breakers off", run(**off, max_open=1)[0])
    report("all hours (07-12 not blocked), breakers off", run(**off, blocked=())[0])
    report("12-24 only, breakers off", run(**off, blocked=tuple(range(0, 12)))[0])

    print("\n=== exit grid, breakers off, stack 3, 07-12 blocked (exploratory: picking the best cell is curve fitting)")
    for tp, sl in ((0.5, 1.0), (1.0, 1.0), (1.0, 2.0), (1.5, 2.0), (2.0, 2.0), (1.0, 3.0), (2.0, 3.0), (3.0, 3.0),
                   (3.0, 2.0), (4.0, 2.0)):
        g = run(**off, tp_usd=tp, sl_usd=sl)[0]
        print(f"  +{tp:>3}/-{sl:<3} all: {stats(g)}")
        print(f"           oos: {stats(g[g['time'] < OOS_END])}")


if __name__ == "__main__":
    main()
