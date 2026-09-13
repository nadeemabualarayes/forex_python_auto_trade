"""Exit-hypothesis screen for the scalp-test XAUUSD M1 profile - tick-level replay.

    python docs/research/exit_hypothesis_screen.py > docs/research/<report>.txt

Read-only research tool. It reads the terminal's tick history, M1 bars, deal history and the bot's
journal/log, and prints a report. It changes no bot state, config or strategy code.

The pre-registration block below (hypotheses, exact rules, windows, friction scenarios, metrics and
decision rules) was written into this file BEFORE any out-of-sample result was computed and is
printed verbatim at the top of the report. Thresholds are fixed; nothing here is tuned.
"""
import calendar
import csv
import math
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(ROOT)

import MetaTrader5 as mt5                        # noqa: E402
import config                                    # noqa: E402
import mae_mfe_analysis as mm                    # noqa: E402  (M1 MFE for the reconciliation)
import forward_report as fr                      # noqa: E402
from execution import mt5_init_args             # noqa: E402
from strategy import generate_signal             # noqa: E402
from technicals import compute_indicators        # noqa: E402

PREREG = r"""
PRE-REGISTRATION  (frozen in exit_hypothesis_screen.py before any out-of-sample result was computed)
-----------------------------------------------------------------------------------------------------
Current live exit system (C0), exactly as position_manager.next_stop runs it on scalp-test:
  initial SL = 2.0 ATR, TP = 2.0 ATR  (so 1R = 2 ATR of the signal bar)
  every loop (~2 s): if profit >= 1.0 x live ATR  ->  SL = max(entry, price - 1.0 x live ATR), tighten only,
  with a minimum step of max(5 points, 0.05 x live ATR). Live ATR = ATR of the last closed M1 bar.
  Note: 1.0 ATR = +0.5R when live ATR equals the signal-bar ATR, so C0 ALREADY protects at ~+0.5R and
  trails immediately, 0.5R behind price.

Hypotheses (thresholds fixed; not tuned on any data):
  A  "protection at +0.5R": when profit >= 0.5R, move SL to entry (once). No trailing. TP unchanged.
  B  "delayed trail from +0.75R": when profit >= 0.5R, SL to entry; when profit >= 0.75R, trail
     SL = max(entry, price - 1.0 x live ATR) (same distance as C0), tighten only, same minimum step.
  N  reference only (not a hypothesis): no management - initial SL and TP only.
  R is the signal-bar stop distance; profit is marked at the bid for longs and the ask for shorts.

Windows (server time):
  IN-SAMPLE live window   2026-09-07 14:26:39 -> 2026-09-11 23:59   the 147-trade report's data; the
                          hypotheses were derived from it, so every result there is in-sample.
  OUT-OF-SAMPLE backtest  2026-08-03 02:00 -> 2026-09-04 23:59      all tick + M1 history available
                          before the live period; never inspected for exit behaviour. 5 weekly blocks.

Two lenses, always labelled:
  COUNTERFACTUAL (fixed entries): the same entries replayed tick-by-tick under each exit rule. One-to-one
    trade comparison; ignores that a longer hold changes which later signals the bot takes.
  BACKTEST (sequential): signals, one-position-at-a-time, spread cap, min-lot skip, daily cap/loss and
    streak breakers all re-simulated per exit rule. Path-dependent and the primary evidence.

Friction (spread is always inside the bid/ask ticks; commission and fees are 0 on this account):
  S0 ticks only | S1 median observed live slippage | S2 90th-percentile observed live slippage,
  applied per event type (entry fill, stop-type exit, TP exit), measured from the live deals.

Decision rules:
  D0 engine validity: C0 replayed on the actual live entries must match the live exit type on >= 85% of
     trades with median |R_replay - R_live| <= 0.05R; otherwise INSUFFICIENT DATA.
  D1 sample: the out-of-sample backtest must contain >= 300 C0 trades; otherwise INSUFFICIENT DATA.
  A hypothesis PASSES only if, on the out-of-sample backtest versus C0:
     P1 expectancy (R/trade) is higher under S0 and S1, and not lower under S2;
     P2 profit factor under S1 is >= C0's;
     P3 max drawdown (R) under S1 is at most 10% worse than C0's;
     P4 expectancy is higher in at least 4 of the 5 weekly blocks under S1;
     P5 the in-sample counterfactual under S1 moves expectancy in the same direction.
  Verdict: WORTH FORWARD TESTING if a hypothesis passes P1-P5 (with D0, D1);
           NOT WORTH TESTING if neither hypothesis raises expectancy under S1 out-of-sample;
           INSUFFICIENT DATA otherwise.
-----------------------------------------------------------------------------------------------------
"""

SYMBOL = "XAUUSD"
MAGIC = config.MAGIC_NUMBER
POINT = 0.01
CONTRACT = 100.0
VOL_MIN, VOL_STEP = 0.01, 0.01
BUDGET = config.RISK_USD_PER_TRADE
SL_ATR, TP_ATR = config.SL_ATR_MULTIPLIER, config.TP_ATR_MULTIPLIER
BE_ATR, TRAIL_ATR = config.BREAKEVEN_ATR, config.TRAIL_ATR
SPREAD_CAP = config.spread_limit(SYMBOL)
CHECK_S = 2.0

FWD_START = datetime(2026, 9, 7, 14, 26, 39)
FWD_END = datetime(2026, 9, 11, 23, 59, 59)
REPORT147_LAST = datetime(2026, 9, 11, 22, 16, 59)
OOS_START = datetime(2026, 8, 3, 2, 0)
OOS_END = datetime(2026, 9, 4, 23, 59, 59)
OOS_WEEKS = [(datetime(2026, 8, 3), datetime(2026, 8, 8)), (datetime(2026, 8, 10), datetime(2026, 8, 15)),
             (datetime(2026, 8, 17), datetime(2026, 8, 22)), (datetime(2026, 8, 24), datetime(2026, 8, 29)),
             (datetime(2026, 8, 31), datetime(2026, 9, 5))]

POLICIES = ("C0", "A", "B", "N")
POLICY_NAME = {"C0": "C0 current (BE+trail at 1 ATR)", "A": "A protect +0.5R, no trail",
               "B": "B BE +0.5R, trail from +0.75R", "N": "N reference: no management"}


def ep(dt: datetime) -> float:
    return float(calendar.timegm(dt.timetuple()))


def sdt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


# ============================================================================ data
class Bars:
    def __init__(self, df):
        self.open_s = (df["time"].values.astype("datetime64[s]").astype(np.int64)).astype(np.float64)
        self.close = df["close"].values.astype(float)
        self.lower = df["lower_band"].values.astype(float)
        self.upper = df["upper_band"].values.astype(float)
        self.rsi = df["rsi"].values.astype(float)
        self.atr = df["atr"].values.astype(float)
        buy = (self.close <= self.lower) & (self.rsi < config.RSI_OVERSOLD)
        sell = (self.close >= self.upper) & (self.rsi > config.RSI_OVERBOUGHT)
        sig = np.where(buy, 1, np.where(sell, -1, 0)).astype(np.int8)
        sig[np.isnan(self.atr) | np.isnan(self.lower) | np.isnan(self.rsi)] = 0
        self.sig = sig
        self.df = df

    def last_closed(self, t: float) -> int:
        """Index of the bar live code would read as df.iloc[-2] at time t."""
        target = math.floor(t / 60.0) * 60.0 - 60.0
        return int(np.searchsorted(self.open_s, target, side="right") - 1)

    def atr_at(self, t: float) -> float:
        k = self.last_closed(t)
        return float(self.atr[k]) if k >= 0 else float("nan")

    def penetration(self, k: int, side: int) -> float:
        a = self.atr[k]
        if not a or np.isnan(a):
            return float("nan")
        beyond = (self.lower[k] - self.close[k]) if side > 0 else (self.close[k] - self.upper[k])
        return max(0.0, beyond / a)


class Ticks:
    def __init__(self, ms, bid, ask):
        self.ms, self.bid, self.ask = ms, bid, ask


def load_window(start: datetime, end: datetime, tail_hours: int = 12):
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, utc(start - timedelta(hours=3)),
                                 utc(end + timedelta(hours=tail_hours)))
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = compute_indicators(df)
    parts = []
    cur = start - timedelta(minutes=10)
    stop = end + timedelta(hours=tail_hours)
    while cur < stop:
        nxt = min(cur + timedelta(days=2), stop)
        tk = None
        for _ in range(5):
            tk = mt5.copy_ticks_range(SYMBOL, utc(cur), utc(nxt), mt5.COPY_TICKS_ALL)
            if tk is not None:
                break
        if tk is not None and len(tk):
            parts.append(tk)
        cur = nxt
    tk = np.concatenate(parts)
    keep = (tk["bid"] > 0) & (tk["ask"] > 0) & (tk["ask"] >= tk["bid"])
    tk = tk[keep]
    order = np.argsort(tk["time_msc"], kind="stable")
    tk = tk[order]
    return Bars(df), Ticks(tk["time_msc"].astype(np.int64), tk["bid"].astype(float), tk["ask"].astype(float))


# ============================================================================ exit rules
def rule(policy: str, long: bool, entry: float, cur_sl: float, price: float, atr: float, stop: float):
    """New SL or None. Mirrors position_manager.next_stop for C0; A/B/N per the pre-registration."""
    if policy == "N":
        return None
    profit = (price - entry) if long else (entry - price)
    if policy == "C0":
        if atr <= 0 or np.isnan(atr) or profit < BE_ATR * atr:
            return None
        trail = price - TRAIL_ATR * atr if long else price + TRAIL_ATR * atr
        cand = max(entry, trail) if long else min(entry, trail)
        step = max(POINT * 5, atr * 0.05)
        ok = cand > cur_sl + step if long else cand < cur_sl - step
        return cand if ok else None
    if policy == "A":
        if profit >= 0.5 * stop and ((long and cur_sl < entry) or (not long and cur_sl > entry)):
            return entry
        return None
    if policy == "B":
        cand = None
        if profit >= 0.5 * stop:
            cand = entry
        if profit >= 0.75 * stop and atr > 0 and not np.isnan(atr):
            trail = price - TRAIL_ATR * atr if long else price + TRAIL_ATR * atr
            cand = max(entry, trail) if long else min(entry, trail)
        if cand is None:
            return None
        step = max(POINT * 5, (atr if atr > 0 and not np.isnan(atr) else 0.0) * 0.05)
        ok = cand > cur_sl + step if long else cand < cur_sl - step
        return cand if ok else None
    raise ValueError(policy)


def simulate(policy, long, ti_fill, entry, sl, tp, stop, B: Bars, T: Ticks):
    """Walk ticks after the fill. Broker-side SL/TP on every tick; management every CHECK_S seconds.
    Returns dict(exit_ms, exit_px, kind, mfe, mae, final_sl) or None if still open at end of data."""
    ms, n = T.ms, len(T.ms)
    mark = T.bid if long else T.ask
    t_fill = ms[ti_fill] / 1000.0
    cur_sl = sl
    i = ti_fill + 1
    k_chk = 1
    mfe = mae = 0.0
    while i < n:
        chk = t_fill + k_chk * CHECK_S
        j = int(np.searchsorted(ms, chk * 1000.0, side="right"))
        if j <= i:                                   # no ticks in this window: jump to the next tick
            k_chk = max(k_chk + 1, int(math.ceil((ms[i] / 1000.0 - t_fill) / CHECK_S)))
            continue
        seg = mark[i:j]
        hit = np.flatnonzero((seg <= cur_sl) | (seg >= tp)) if long else np.flatnonzero((seg >= cur_sl) | (seg <= tp))
        if hit.size:
            k = i + int(hit[0])
            s2 = mark[i:k + 1]
            mfe = max(mfe, (s2.max() - entry) if long else (entry - s2.min()))
            mae = max(mae, (entry - s2.min()) if long else (s2.max() - entry))
            px = float(mark[k])
            if (long and px >= tp) or (not long and px <= tp):
                kind = "TP"
            elif abs(cur_sl - sl) < 1e-9:
                kind = "SL"
            elif abs(cur_sl - entry) < 1e-6:
                kind = "BE"
            else:
                kind = "TRAIL"
            return dict(exit_ms=int(ms[k]), exit_px=px, kind=kind, mfe=float(mfe), mae=float(mae), final_sl=cur_sl)
        mfe = max(mfe, (seg.max() - entry) if long else (entry - seg.min()))
        mae = max(mae, (entry - seg.min()) if long else (seg.max() - entry))
        i = j
        new = rule(policy, long, entry, cur_sl, float(mark[j - 1]), B.atr_at(chk), stop)
        if new is not None:
            cur_sl = new
        k_chk += 1
    return None


# ============================================================================ friction
def live_friction(raw, entries_journal, sl_moves):
    """Adverse slippage (price units, + = against the trader) by event type, from live strategy deals."""
    by_pos = defaultdict(list)
    for d in raw:
        if d.symbol == SYMBOL and d.magic == MAGIC:
            by_pos[d.position_id].append(d)
    ent, stp, tpx = [], [], []
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d.entry == 0]
        outs = [d for d in ds if d.entry == 1]
        if not ins or pid not in entries_journal:
            continue
        j = entries_journal[pid]
        if j["time"] < FWD_START:
            continue
        long = ins[0].type == 0
        fill = ins[0].price
        ent.append((fill - j["quote"]) if long else (j["quote"] - fill))
        if outs:
            o = outs[-1]
            moves = [m for m in sl_moves.get(pid, []) if m[0] <= sdt(o.time) + timedelta(seconds=1)]
            level = moves[-1][1] if moves else j["sl"]
            if o.reason == 4:
                stp.append((level - o.price) if long else (o.price - level))
            elif o.reason == 5:
                tpx.append((j["tp"] - o.price) if long else (o.price - j["tp"]))
    q = lambda a, p: float(np.quantile(a, p)) if a else 0.0
    return dict(n=(len(ent), len(stp), len(tpx)),
                S0=dict(entry=0.0, stop=0.0, tp=0.0),
                S1=dict(entry=q(ent, .5), stop=q(stp, .5), tp=q(tpx, .5)),
                S2=dict(entry=q(ent, .9), stop=q(stp, .9), tp=q(tpx, .9)),
                raw=dict(entry=ent, stop=stp, tp=tpx))


def journal():
    entries, moves = {}, defaultdict(list)
    with open(config.TRADE_JOURNAL, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not r["ticket"]:
                continue
            t = int(r["ticket"])
            when = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
            if r["event"] == "ENTRY" and "[test]" not in r["note"]:
                entries[t] = dict(time=when, quote=float(r["price"]), sl=float(r["sl"]), tp=float(r["tp"]),
                                  lot=float(r["lot"]))
            elif r["event"] == "SL_MOVE":
                moves[t].append((when, float(r["sl"])))
    return entries, moves


def downtime_intervals(start: datetime, end: datetime, gap_s: int = 180):
    stamps = []
    for name in sorted(os.listdir(config.LOG_DIR)):
        if not name.startswith("bot.log"):
            continue
        with open(os.path.join(config.LOG_DIR, name), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
                if m:
                    stamps.append(ep(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")))
    stamps = sorted(s for s in set(stamps) if ep(start) - 3600 <= s <= ep(end) + 3600)
    out = []
    for a, b in zip(stamps, stamps[1:]):
        if b - a > gap_s:
            out.append((a, b))
    return out


# ============================================================================ backtest
def backtest(policy, B: Bars, T: Ticks, start: datetime, end: datetime, fric: dict, latency: float,
             downtime=()):
    """Sequential re-simulation of the scalp profile's entries under one exit policy."""
    trades, skips = [], defaultdict(int)
    ms = T.ms
    t = ep(start)
    t_end = ep(end)
    last_used = None
    day, day_net, day_entries, day_streak = None, 0.0, 0, 0
    dt_iv = list(downtime)

    def in_downtime(x):
        for a, b in dt_iv:
            if a <= x < b:
                return True
        return False

    while t < t_end:
        d = int(t // 86400)
        if d != day:
            day, day_net, day_entries, day_streak = d, 0.0, 0, 0
        k = B.last_closed(t)
        wd = sdt(t).weekday()
        nxt_bar = (math.floor(t / 60.0) + 1) * 60.0 + latency
        if (k < 0 or wd not in config.TRADING_WEEKDAYS or day_net <= -config.MAX_DAILY_LOSS_USD
                or day_streak >= config.MAX_CONSECUTIVE_LOSSES or day_entries >= config.MAX_TRADES_PER_DAY
                or B.sig[k] == 0 or B.open_s[k] == last_used or in_downtime(t)):
            t = nxt_bar
            continue
        ti = int(np.searchsorted(ms, t * 1000.0, side="left"))
        if ti >= len(ms):
            break
        tt = ms[ti] / 1000.0
        if B.last_closed(tt) != k:                  # quiet market: first tick belongs to a later bar period
            t = tt
            continue
        if (T.ask[ti] - T.bid[ti]) / POINT > SPREAD_CAP:
            skips["spread"] += 1
            t = tt + CHECK_S
            continue
        last_used = B.open_s[k]
        side = int(B.sig[k])
        long = side > 0
        atr = float(B.atr[k])
        stop = SL_ATR * atr
        lot = math.floor((BUDGET / (stop * CONTRACT)) / VOL_STEP + 1e-9) * VOL_STEP
        if lot < VOL_MIN - 1e-9:
            skips["min_lot"] += 1
            t = tt + CHECK_S
            continue
        quote = T.ask[ti] if long else T.bid[ti]
        entry = quote + fric["entry"] if long else quote - fric["entry"]   # fill = quote + adverse slip
        sl = quote - stop if long else quote + stop                         # live: SL/TP from the quote
        tp = quote + TP_ATR * atr if long else quote - TP_ATR * atr
        res = simulate(policy, long, ti, entry, sl, tp, stop, B, T)
        if res is None:
            skips["open_at_end"] += 1
            break
        rec = finish(res, long, entry, stop, lot, fric, tt, k, B, side)
        trades.append(rec)
        day_entries += 1
        day_net += rec["pnl"]
        day_streak = day_streak + 1 if rec["pnl"] < 0 else 0
        t = res["exit_ms"] / 1000.0 + latency
    return trades, skips


def finish(res, long, entry, stop, lot, fric, t_entry, k, B, side):
    px = res["exit_px"]
    if res["kind"] == "TP":
        px = px - fric["tp"] if long else px + fric["tp"]
    else:
        px = px - fric["stop"] if long else px + fric["stop"]
    move = (px - entry) if long else (entry - px)
    return dict(t=t_entry, exit_t=res["exit_ms"] / 1000.0, long=long, side="LONG" if long else "SHORT",
                entry=entry, stop=stop, lot=lot, pnl=move * CONTRACT * lot, r=move / stop,
                kind=res["kind"], mfe_r=res["mfe"] / stop, mae_r=res["mae"] / stop,
                session=fr.session_bucket(sdt(t_entry).hour),
                atr=float(B.atr[k]) if k is not None else float("nan"),
                pen=B.penetration(k, side) if k is not None else float("nan"),
                hold_s=res["exit_ms"] / 1000.0 - t_entry)


# ============================================================================ metrics
def metrics(tr):
    if not tr:
        return dict(n=0, win=0.0, be=0, net=0.0, netR=0.0, pf=0.0, expR=0.0, ddR=0.0, streak=0,
                    tp=0, sl=0, trail=0, bev=0)
    pnl = np.array([x["pnl"] for x in tr])
    r = np.array([x["r"] for x in tr])
    eq = np.concatenate([[0.0], np.cumsum(r)])
    gl = -pnl[pnl < 0].sum()
    streak = worst = 0
    for p in pnl:
        streak = streak + 1 if p < 0 else 0
        worst = max(worst, streak)
    kinds = defaultdict(int)
    for x in tr:
        kinds[x["kind"]] += 1
    return dict(n=len(tr), win=100.0 * (pnl > 0).mean(), be=int((np.abs(pnl) < 0.005).sum()),
                net=float(pnl.sum()), netR=float(r.sum()), pf=float(pnl[pnl > 0].sum() / gl) if gl > 0 else float("inf"),
                expR=float(r.mean()), ddR=float((np.maximum.accumulate(eq) - eq).max()), streak=worst,
                tp=kinds["TP"], sl=kinds["SL"], trail=kinds["TRAIL"], bev=kinds["BE"])


MH = (f"{'':<32}{'n':>5}{'win%':>7}{'net$':>9}{'netR':>8}{'PF':>6}{'expR':>8}{'maxDD_R':>9}{'streak':>7}"
      f"{'TP':>5}{'TRAIL':>6}{'BE':>5}{'SL':>5}")


def mrow(label, m):
    pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
    return (f"{label:<32}{m['n']:>5}{m['win']:>7.1f}{m['net']:>+9.2f}{m['netR']:>+8.2f}{pf:>6}{m['expR']:>+8.3f}"
            f"{m['ddR']:>9.2f}{m['streak']:>7}{m['tp']:>5}{m['trail']:>6}{m['bev']:>5}{m['sl']:>5}")


def regime_of(atr, cuts):
    if atr is None or np.isnan(atr) or cuts is None:
        return "n/a"
    return "LOW" if atr < cuts[0] else "HIGH" if atr >= cuts[1] else "NORMAL"


def pen_of(p):
    if p is None or np.isnan(p):
        return "n/a"
    return "touch" if p < 0.1 else "small" if p < 0.3 else "medium" if p < 0.6 else "deep"


def breakdown(title, runs, cuts):
    """runs: {policy: trades}. Prints each slice for every policy."""
    dims = [("SESSION", lambda x: x["session"], ["00-07", "07-12", "12-17", "17-24"]),
            ("DIRECTION", lambda x: x["side"], ["LONG", "SHORT"]),
            ("ATR REGIME", lambda x: regime_of(x["atr"], cuts), ["LOW", "NORMAL", "HIGH"]),
            ("BB PENETRATION", lambda x: pen_of(x["pen"]), ["touch", "small", "medium", "deep"])]
    for dname, key, labels in dims:
        print(f"\n  {title} - by {dname}")
        print("  " + MH)
        for lab in labels:
            for p in POLICIES:
                sub = [x for x in runs[p] if key(x) == lab]
                print("  " + mrow(f"{lab:<7} {p}", metrics(sub)))
            base = metrics([x for x in runs["C0"] if key(x) == lab])["expR"]
            print("  " + f"{'':<32}" + "   delta expR vs C0:  " + "  ".join(
                f"{p} {metrics([x for x in runs[p] if key(x) == lab])['expR'] - base:+.3f}" for p in ("A", "B", "N")))


# ============================================================================ live trades (fixed entries)
def live_trades(raw, jent, moves):
    """Post-fix live strategy trades (manual closes excluded) with fill/exit times in ms."""
    by_pos = defaultdict(list)
    for d in raw:
        if d.symbol == SYMBOL and d.magic in (MAGIC, 0):
            by_pos[d.position_id].append(d)
    out = []
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d.entry == 0 and d.magic == MAGIC]
        outs = [d for d in ds if d.entry == 1]
        if not ins or not outs or pid not in jent:
            continue
        i0, o = ins[0], outs[-1]
        when = sdt(i0.time)
        if when < FWD_START or when > FWD_END:
            continue
        if o.reason not in (4, 5):                  # manual/mobile close: the exit was not the strategy's
            continue
        j = jent[pid]
        long = i0.type == 0
        stop = abs(i0.price - j["sl"])
        net = sum(d.profit + d.commission + d.swap + d.fee for d in ds)
        mv = [m for m in moves.get(pid, []) if m[0] <= sdt(o.time) + timedelta(seconds=1)]
        kind = "TP" if o.reason == 5 else ("SL" if not mv else ("BE" if abs(mv[-1][1] - i0.price) < 0.005 else "TRAIL"))
        out.append(dict(pid=pid, t=i0.time_msc / 1000.0, fill_ms=i0.time_msc, exit_ms=o.time_msc, long=long,
                        side="LONG" if long else "SHORT", entry=i0.price, sl=j["sl"], tp=j["tp"], quote=j["quote"],
                        stop=stop, lot=i0.volume, net=net, r=net / (stop * CONTRACT * i0.volume), kind=kind,
                        in147=when <= REPORT147_LAST))
    return sorted(out, key=lambda x: x["t"])


def tick_excursion(T: Ticks, long, entry, fill_ms, exit_ms):
    a = int(np.searchsorted(T.ms, fill_ms, side="right"))
    b = int(np.searchsorted(T.ms, exit_ms, side="right"))
    if b <= a:
        return 0.0, 0.0
    seg = (T.bid if long else T.ask)[a:b]
    return float(max(0.0, (seg.max() - entry) if long else (entry - seg.min()))), \
        float(max(0.0, (entry - seg.min()) if long else (seg.max() - entry)))


def replay_fixed(policy, lt, B, T, fric):
    """Counterfactual: the live trade's own entry (fill, quote-based SL/TP) under `policy`."""
    ti = int(np.searchsorted(T.ms, lt["fill_ms"], side="right") - 1)
    res = simulate(policy, lt["long"], ti, lt["entry"], lt["sl"], lt["tp"], lt["stop"], B, T)
    if res is None:
        return None
    px = res["exit_px"]
    if res["kind"] == "TP":
        px = px - fric["tp"] if lt["long"] else px + fric["tp"]
    else:
        px = px - fric["stop"] if lt["long"] else px + fric["stop"]
    move = (px - lt["entry"]) if lt["long"] else (lt["entry"] - px)
    k = B.last_closed(lt["t"])
    return dict(t=lt["t"], exit_t=res["exit_ms"] / 1000.0, long=lt["long"], side=lt["side"], entry=lt["entry"],
                stop=lt["stop"], lot=lt["lot"], pnl=move * CONTRACT * lt["lot"], r=move / lt["stop"],
                kind=res["kind"], mfe_r=res["mfe"] / lt["stop"], mae_r=res["mae"] / lt["stop"],
                session=fr.session_bucket(sdt(lt["t"]).hour), atr=float(B.atr[k]) if k >= 0 else float("nan"),
                pen=B.penetration(k, 1 if lt["long"] else -1) if k >= 0 else float("nan"),
                hold_s=res["exit_ms"] / 1000.0 - lt["t"], pid=lt.get("pid"))


def fixed_entry_set(src_trades):
    """Turn backtest trades (C0, S0) into fixed-entry inputs for the one-to-one counterfactual."""
    return src_trades


# ============================================================================ main
def main():
    args, kw = mt5_init_args()
    if not mt5.initialize(*args, **kw):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    raw = ()
    for _ in range(10):
        raw = mt5.history_deals_get(0, 2 ** 31 - 1) or ()
        if raw:
            break
    print(f"loading in-sample window ...", file=sys.stderr)
    Bf, Tf = load_window(FWD_START, FWD_END)
    print(f"loading out-of-sample window ...", file=sys.stderr)
    Bo, To = load_window(OOS_START, OOS_END)
    mt5.shutdown()

    jent, moves = journal()
    fric_all = live_friction(raw, jent, moves)
    lts = live_trades(raw, jent, moves)
    l147 = [x for x in lts if x["in147"]]

    now = datetime.now()
    print("=" * 118)
    print(f"EXIT-HYPOTHESIS SCREEN - XAUUSD scalp-test (magic {MAGIC})   generated {now:%Y-%m-%d %H:%M} server")
    print(f"profile: M1, RSI {config.RSI_OVERSOLD}/{config.RSI_OVERBOUGHT}, SL/TP {SL_ATR}/{TP_ATR} ATR, BE {BE_ATR} ATR, "
          f"trail {TRAIL_ATR} ATR, manage={config.MANAGE_POSITIONS}, trend={config.TREND_FILTER_ENABLED}, "
          f"candles={config.CANDLE_MODE}, risk ${BUDGET:.2f}, one position")
    print("RESEARCH ONLY - no bot, config or strategy code was changed; nothing was restarted.")
    print("=" * 118)
    print(PREREG)

    # ------------------------------------------------------------------ data quality
    print("\n1. DATA QUALITY AND METHOD")
    print(f"  tick data     : YES - MT5 COPY_TICKS_ALL with millisecond timestamps, bid and ask per tick.")
    print(f"                  in-sample {len(Tf.ms):,} ticks, out-of-sample {len(To.ms):,} ticks.")
    print(f"                  => results below are a TICK-LEVEL REPLAY, not M1 bounds. Tick order is known, so no")
    print(f"                     intrabar ordering assumption is needed for SL/TP versus management.")
    sp_f = (Tf.ask - Tf.bid) / POINT
    sp_o = (To.ask - To.bid) / POINT
    print(f"  spread (pts)  : in-sample median {np.median(sp_f):.0f} p90 {np.quantile(sp_f, .9):.0f} | "
          f"out-of-sample median {np.median(sp_o):.0f} p90 {np.quantile(sp_o, .9):.0f}  (inside every replayed fill)")
    print(f"  broker costs  : commission $0, fees $0 on this account (live deals); swap ignored (-$0.13 total live).")
    fr_n = fric_all["n"]
    print(f"  live slippage : measured on {fr_n[0]} entries, {fr_n[1]} stop exits, {fr_n[2]} TP exits "
          f"(price units, + = adverse)")
    for s in ("S1", "S2"):
        f = fric_all[s]
        print(f"    {s}: entry {f['entry']:+.3f}  stop-exit {f['stop']:+.3f}  tp-exit {f['tp']:+.3f}")
    # signal equivalence with the live function
    sample = Bo.df.iloc[::7].to_dict("records")
    mism = 0
    for row in sample:
        live = generate_signal(row) if not (np.isnan(row["atr"]) or np.isnan(row["lower_band"])) else None
        vec = {1: "BUY", -1: "SELL", 0: None}[int((row["close"] <= row["lower_band"] and row["rsi"] < config.RSI_OVERSOLD)
                                                  - (row["close"] >= row["upper_band"] and row["rsi"] > config.RSI_OVERBOUGHT))]
        if (live or None) != (vec or None):
            mism += 1
    print(f"  signal check  : vectorised entry rule vs strategy.generate_signal on {len(sample):,} bars -> {mism} mismatches")
    # entry latency measured live
    lat = []
    for x in lts:
        k = Bf.last_closed(x["t"])
        if k >= 0:
            close_t = Bf.open_s[k] + 60.0
            if 0 <= x["t"] - close_t < 60:
                lat.append(x["t"] - close_t)
    latency = float(np.median(lat)) if lat else 1.0
    print(f"  entry latency : live fills land a median {latency:.2f} s after the signal bar closes "
          f"(n={len(lat)}); the backtest uses that value.")
    print(f"  live set      : {len(lts)} post-fix strategy trades closed by SL/TP in the live window "
          f"({len(l147)} are the 147-report set; manual closes excluded)")

    # ------------------------------------------------------------------ D0 calibration
    print("\n2. ENGINE CALIBRATION (D0) - C0 replayed on the actual live entries vs what really happened")
    agree, dR, dt_exit = 0, [], []
    for x in l147:
        rep = replay_fixed("C0", x, Bf, Tf, fric_all["S0"])
        if rep is None:
            continue
        live_kind = x["kind"]
        rep_kind = rep["kind"]
        same = (live_kind == rep_kind) or ({live_kind, rep_kind} <= {"BE", "TRAIL"})
        agree += same
        dR.append(abs(rep["r"] - x["r"]))
        dt_exit.append(rep["exit_t"] - x["exit_ms"] / 1000.0)
    n147 = len(l147)
    agree_pct = 100.0 * agree / max(1, n147)
    med_dR = float(np.median(dR)) if dR else float("nan")
    print(f"  trades replayed: {n147}")
    print(f"  exit type agreement (BE and TRAIL count as the same managed exit): {agree}/{n147} = {agree_pct:.1f}%")
    print(f"  |R_replay - R_live|: median {med_dR:.3f}R  p75 {np.quantile(dR, .75):.3f}R  p90 {np.quantile(dR, .9):.3f}R")
    print(f"  exit time difference replay-live: median {np.median(dt_exit):+.1f}s  p90 |diff| {np.quantile(np.abs(dt_exit), .9):.1f}s")
    d0 = agree_pct >= 85.0 and med_dR <= 0.05
    print(f"  D0 {'PASS' if d0 else 'FAIL'} (needs >= 85% and <= 0.05R)")

    dti = downtime_intervals(FWD_START, FWD_END)
    seq_live, _ = backtest("C0", Bf, Tf, FWD_START, REPORT147_LAST, fric_all["S0"], latency, downtime=dti)
    live_t = [x["t"] for x in l147]
    matched = sum(1 for s in seq_live if any(abs(s["t"] - lt_) <= 3.0 for lt_ in live_t))
    print(f"  full sequential C0 backtest over the same window (bot downtime masked, {len(dti)} gaps): "
          f"{len(seq_live)} trades vs {n147} live; {matched} entries within 3 s of a live entry "
          f"({100.0 * matched / max(1, n147):.1f}% of live)")
    ml, ms_ = metrics([dict(pnl=x["net"], r=x["r"], kind=x["kind"]) for x in l147]), metrics(seq_live)
    print("  " + MH)
    print("  " + mrow("live (actual 147)", ml))
    print("  " + mrow("sequential C0 replay", ms_))

    # ------------------------------------------------------------------ tick vs M1 reconciliation
    print("\n3. IN-SAMPLE HISTORICAL COUNTERFACTUAL - the 147 live trades, fixed entries, tick paths")
    print("\n3a. The 147-report's M1 excursion numbers re-measured on ticks (fill to actual exit)")
    tmfe = {}
    for x in l147:
        mfe, mae = tick_excursion(Tf, x["long"], x["entry"], x["fill_ms"], x["exit_ms"])
        tmfe[x["pid"]] = (mfe / x["stop"], mae / x["stop"])
    losers = [x for x in l147 if x["net"] < 0]
    small_w = [x for x in l147 if 0 < x["r"] <= 0.25]
    print(f"  {'claim (M1 report)':<44}{'M1 report':>10}{'ticks':>8}")
    for lab, m1v, tv in (
            ("losers reaching >= +0.25R", 28, sum(tmfe[x['pid']][0] >= .25 for x in losers)),
            ("losers reaching >= +0.50R", 12, sum(tmfe[x['pid']][0] >= .5 for x in losers)),
            ("losers reaching >= +0.75R", 5, sum(tmfe[x['pid']][0] >= .75 for x in losers)),
            ("small winners (<=0.25R) with MFE >= +0.50R", 39, sum(tmfe[x['pid']][0] >= .5 for x in small_w)),
            ("small winners (<=0.25R) with MFE >= +0.75R", 11, sum(tmfe[x['pid']][0] >= .75 for x in small_w))):
        print(f"  {lab:<44}{m1v:>10}{tv:>8}")
    print(f"  all trades reaching +0.5R: M1 100, ticks {sum(v[0] >= .5 for v in tmfe.values())};  "
          f"+0.75R: M1 65, ticks {sum(v[0] >= .75 for v in tmfe.values())};  +1.0R: M1 35, ticks {sum(v[0] >= 1 for v in tmfe.values())}")
    # why did C0 not protect losers that truly reached +0.5R?
    lp = [x for x in losers if tmfe[x["pid"]][0] >= 0.5]
    print(f"\n  losers whose tick MFE truly reached +0.5R: {len(lp)}. Why C0's breakeven did not save them:")
    for x in lp:
        k0 = Bf.last_closed(x["t"])
        a_entry = float(Bf.atr[k0]) if k0 >= 0 else float("nan")
        a = int(np.searchsorted(Tf.ms, x["fill_ms"], side="right"))
        b = int(np.searchsorted(Tf.ms, x["exit_ms"], side="right"))
        seg = (Tf.bid if x["long"] else Tf.ask)[a:b]
        kpk = int(np.argmax(seg) if x["long"] else np.argmin(seg))
        t_pk = Tf.ms[a + kpk] / 1000.0
        a_live = Bf.atr_at(t_pk)
        trig_R = BE_ATR * a_live / x["stop"]
        print(f"    {sdt(x['t']):%m-%d %H:%M:%S} {x['side']:<5} MFE {tmfe[x['pid']][0]:+.2f}R  C0 trigger at peak = "
              f"{trig_R:.2f}R (live ATR {a_live:.2f} vs signal ATR {a_entry:.2f})  -> "
              f"{'trigger above the peak (ATR expanded)' if trig_R > tmfe[x['pid']][0] else 'peak between 2 s checks / step gate'}")

    # ------------------------------------------------------------------ fixed-entry counterfactual, in-sample
    print("\n3b. Fixed-entry counterfactual on the 147 live entries (one-to-one)")
    ins_runs = {}
    for sname in ("S0", "S1", "S2"):
        ins_runs[sname] = {p: [r for r in (replay_fixed(p, x, Bf, Tf, fric_all[sname]) for x in l147) if r] for p in POLICIES}
        print(f"\n  friction {sname}")
        print("  " + MH)
        for p in POLICIES:
            print("  " + mrow(POLICY_NAME[p], metrics(ins_runs[sname][p])))
    impact_tables("IN-SAMPLE (147 live entries, S1)", ins_runs["S1"])
    cuts_f = np.quantile(Bf.atr[~np.isnan(Bf.atr)], [1 / 3, 2 / 3])
    breakdown("IN-SAMPLE fixed-entry, S1", ins_runs["S1"], cuts_f)

    # ------------------------------------------------------------------ current trailing mechanism
    print("\n4. THE CURRENT TRAILING MECHANISM (C0) ON THE 147 LIVE TRADES - tick-measured")
    trail = [x for x in l147 if x["kind"] in ("TRAIL", "BE")]
    tm = np.array([tmfe[x["pid"]][0] for x in trail])
    tr_r = np.array([x["r"] for x in trail])
    print(f"  managed exits: {len(trail)}; tick MFE mean {tm.mean():.2f}R median {np.median(tm):.2f}R; "
          f"realised mean {tr_r.mean():+.3f}R median {np.median(tr_r):+.3f}R")
    print(f"  capture (realised/MFE): median {np.median(tr_r / np.where(tm > 0, tm, np.nan)):.2f}")
    gap = tm - tr_r
    print(f"  give-back MFE - realised: mean {gap.mean():.2f}R median {np.median(gap):.2f}R  "
          f"<- the trail sits 1.0 live ATR = ~0.5R behind price by design")
    print(f"\n  small managed exits grouped by realised R and by peak (tick MFE):")
    print(f"  {'realised R':<14}" + "".join(f"{lab:>14}" for lab in ("MFE 0.5-0.75", "MFE 0.75-1.0", "MFE >=1.0", "MFE <0.5")))
    for lo, hi in ((-0.05, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 9)):
        cells = []
        for mlo, mhi in ((0.5, 0.75), (0.75, 1.0), (1.0, 99), (0, 0.5)):
            cells.append(sum(1 for x in trail if lo <= x["r"] < hi and mlo <= tmfe[x["pid"]][0] < mhi))
        print(f"  {f'[{lo:+.2f},{hi:+.2f})':<14}" + "".join(f"{c:>14}" for c in cells))
    by_s = defaultdict(list)
    for x in trail:
        by_s[fr.session_bucket(sdt(x["t"]).hour)].append(x["r"])
    print("  managed exits by session: " + ", ".join(f"{s} n={len(v)} mean {np.mean(v):+.2f}R" for s, v in sorted(by_s.items())))

    # ------------------------------------------------------------------ OOS backtest
    print("\n5. OUT-OF-SAMPLE BACKTEST - sequential re-simulation, 2026-08-03 02:00 -> 2026-09-04 23:59")
    oos = {}
    for sname in ("S0", "S1", "S2"):
        oos[sname] = {}
        for p in POLICIES:
            print(f"  running {sname} {p} ...", file=sys.stderr)
            oos[sname][p], sk = backtest(p, Bo, To, OOS_START, OOS_END, fric_all[sname], latency)
            if sname == "S0" and p == "C0":
                skips0 = sk
        print(f"\n  friction {sname}")
        print("  " + MH)
        for p in POLICIES:
            print("  " + mrow(POLICY_NAME[p], metrics(oos[sname][p])))
    print(f"\n  C0/S0 skipped signals: {dict(skips0)}")
    print("\n  weekly blocks, expectancy R/trade under S1")
    print(f"  {'week':<24}" + "".join(f"{p:>12}" for p in POLICIES))
    weekly = defaultdict(dict)
    for a, b in OOS_WEEKS:
        cells = []
        for p in POLICIES:
            sub = [x for x in oos["S1"][p] if ep(a) <= x["t"] < ep(b)]
            m = metrics(sub)
            weekly[(a, b)][p] = m["expR"]
            cells.append(f"{m['expR']:+.3f} n{m['n']}")
        print(f"  {a:%m-%d} -> {b - timedelta(days=1):%m-%d}          " + "".join(f"{c:>12}" for c in cells))
    cuts_o = np.quantile(Bo.atr[~np.isnan(Bo.atr)], [1 / 3, 2 / 3])
    breakdown("OUT-OF-SAMPLE backtest, S1", oos["S1"], cuts_o)

    print("\n5b. Out-of-sample fixed-entry counterfactual (C0's own S0 entries replayed under each rule, S1 exits)")
    fixed_src = oos["S0"]["C0"]
    oos_fixed = {p: [] for p in POLICIES}
    for x in fixed_src:
        ti = int(np.searchsorted(To.ms, x["t"] * 1000.0, side="left"))
        k = Bo.last_closed(x["t"])
        quote = x["entry"]
        long = x["long"]
        stop = x["stop"]
        sl = quote - stop if long else quote + stop
        tp = quote + stop * (TP_ATR / SL_ATR) if long else quote - stop * (TP_ATR / SL_ATR)
        for p in POLICIES:
            res = simulate(p, long, ti, quote, sl, tp, stop, Bo, To)
            if res is None:
                continue
            oos_fixed[p].append(finish(res, long, quote, stop, x["lot"], fric_all["S1"], x["t"], k, Bo,
                                       1 if long else -1))
    print("  " + MH)
    for p in POLICIES:
        print("  " + mrow(POLICY_NAME[p], metrics(oos_fixed[p])))
    impact_tables("OUT-OF-SAMPLE (C0 entries, S1)", oos_fixed)

    # ------------------------------------------------------------------ decision rules
    print("\n6. DECISION RULES (as pre-registered)")
    n_oos = metrics(oos["S0"]["C0"])["n"]
    d1 = n_oos >= 300
    print(f"  D0 engine validity: {'PASS' if d0 else 'FAIL'}   ({agree_pct:.1f}% exit agreement, median |dR| {med_dR:.3f}R)")
    print(f"  D1 sample         : {'PASS' if d1 else 'FAIL'}   ({n_oos} out-of-sample C0 trades)")
    verdicts = {}
    for h in ("A", "B"):
        base = {s: metrics(oos[s]["C0"]) for s in ("S0", "S1", "S2")}
        hyp = {s: metrics(oos[s][h]) for s in ("S0", "S1", "S2")}
        p1 = hyp["S0"]["expR"] > base["S0"]["expR"] and hyp["S1"]["expR"] > base["S1"]["expR"] \
            and hyp["S2"]["expR"] >= base["S2"]["expR"]
        p2 = hyp["S1"]["pf"] >= base["S1"]["pf"]
        p3 = hyp["S1"]["ddR"] <= base["S1"]["ddR"] * 1.10
        wk = sum(1 for w in weekly.values() if w[h] > w["C0"])
        p4 = wk >= 4
        ins_delta = metrics(ins_runs["S1"][h])["expR"] - metrics(ins_runs["S1"]["C0"])["expR"]
        oos_delta = hyp["S1"]["expR"] - base["S1"]["expR"]
        p5 = (ins_delta > 0) == (oos_delta > 0) and ins_delta != 0
        improves_s1 = oos_delta > 0
        verdicts[h] = dict(p1=p1, p2=p2, p3=p3, p4=p4, p5=p5, improves_s1=improves_s1, wk=wk,
                           oos_delta=oos_delta, ins_delta=ins_delta)
        print(f"\n  Hypothesis {h}: {POLICY_NAME[h]}")
        print(f"    expR  S0 {base['S0']['expR']:+.3f} -> {hyp['S0']['expR']:+.3f} | S1 {base['S1']['expR']:+.3f} -> "
              f"{hyp['S1']['expR']:+.3f} | S2 {base['S2']['expR']:+.3f} -> {hyp['S2']['expR']:+.3f}   P1 {'PASS' if p1 else 'FAIL'}")
        pfs = lambda v: "inf" if v == float("inf") else f"{v:.2f}"
        print(f"    PF S1 {pfs(base['S1']['pf'])} -> {pfs(hyp['S1']['pf'])}   P2 {'PASS' if p2 else 'FAIL'}")
        print(f"    maxDD_R S1 {base['S1']['ddR']:.2f} -> {hyp['S1']['ddR']:.2f}   P3 {'PASS' if p3 else 'FAIL'}")
        print(f"    weeks better under S1: {wk}/5   P4 {'PASS' if p4 else 'FAIL'}")
        print(f"    in-sample delta expR {ins_delta:+.3f} vs out-of-sample {oos_delta:+.3f}   P5 {'PASS' if p5 else 'FAIL'}")
        print(f"    => {'PASSES' if all((p1, p2, p3, p4, p5)) else 'does not pass'}")
    if not (d0 and d1):
        verdict = "INSUFFICIENT DATA"
    elif any(all((v["p1"], v["p2"], v["p3"], v["p4"], v["p5"])) for v in verdicts.values()):
        verdict = "WORTH FORWARD TESTING"
    elif not any(v["improves_s1"] for v in verdicts.values()):
        verdict = "NOT WORTH TESTING"
    else:
        verdict = "INSUFFICIENT DATA"
    print(f"\n  RULE-BASED VERDICT: {verdict}")
    return verdict


def impact_tables(title, runs):
    """Q1-Q4: one-to-one comparison of each hypothesis against C0 on the same entries."""
    base = runs["C0"]
    idx = {round(x["t"], 3): x for x in base}
    print(f"\n  IMPACT vs C0 - {title}")
    for h in ("A", "B", "N"):
        pairs = [(idx.get(round(x["t"], 3)), x) for x in runs[h]]
        pairs = [(c, x) for c, x in pairs if c is not None]
        diff = [(c, x) for c, x in pairs if abs(c["r"] - x["r"]) > 1e-6 or c["kind"] != x["kind"]]
        c_tp = [(c, x) for c, x in pairs if c["kind"] == "TP"]
        tp_gross = sum(c["pnl"] for c, _ in c_tp)
        tp_harm = [(c, x) for c, x in c_tp if x["r"] < c["r"] - 1e-6]
        c_los = [(c, x) for c, x in pairs if c["pnl"] < 0]
        los_saved = [(c, x) for c, x in c_los if x["pnl"] >= 0]
        c_win = [(c, x) for c, x in pairs if c["pnl"] > 0]
        win_cut = [(c, x) for c, x in c_win if x["r"] < c["r"] - 1e-6]
        win_cut_be = [(c, x) for c, x in c_win if x["kind"] == "BE"]
        trail_up = [(c, x) for c, x in pairs if c["kind"] in ("TRAIL", "BE") and x["r"] > c["r"] + 1e-6]
        trail_dn = [(c, x) for c, x in pairs if c["kind"] in ("TRAIL", "BE") and x["r"] < c["r"] - 1e-6]
        print(f"   {h} ({POLICY_NAME[h]}):")
        print(f"     Q1 trades whose outcome changes            : {len(diff)} of {len(pairs)}")
        print(f"     Q2 C0 losers turned into BE-or-better      : {len(los_saved)} of {len(c_los)} "
              f"(${sum(x['pnl'] - c['pnl'] for c, x in los_saved):+.2f})")
        print(f"     Q3 C0 winners that end lower               : {len(win_cut)} of {len(c_win)} "
              f"(${sum(x['pnl'] - c['pnl'] for c, x in win_cut):+.2f}); of which stopped at breakeven: {len(win_cut_be)}")
        print(f"     Q4 C0 TP gross ${tp_gross:+.2f} on {len(c_tp)} trades; TP winners harmed: {len(tp_harm)} "
              f"(${sum(x['pnl'] - c['pnl'] for c, x in tp_harm):+.2f})")
        print(f"     C0 managed exits improved / worsened       : {len(trail_up)} (${sum(x['pnl'] - c['pnl'] for c, x in trail_up):+.2f})"
              f" / {len(trail_dn)} (${sum(x['pnl'] - c['pnl'] for c, x in trail_dn):+.2f})")
        mix = defaultdict(int)
        for c, x in trail_up + trail_dn:
            mix[f"{c['kind']}->{x['kind']}"] += 1
        print(f"     transitions of changed managed exits       : {dict(sorted(mix.items()))}")


if __name__ == "__main__":
    main()
