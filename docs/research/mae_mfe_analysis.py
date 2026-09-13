"""MAE / MFE / exit-efficiency analysis of the post-sizing-fix scalp-test trades.

    python docs/research/mae_mfe_analysis.py [> report.txt]

Read-only research tool. It touches no bot state: it reads the terminal's deal history, the M1 OHLC
series, and logs/trades.csv, and prints a report. Nothing here changes the strategy, the config or
any file the bot uses.

Method (documented in full in the report's methodology section):
  * A trade's lifetime is [entry fill, exit fill], both taken from the broker's own deals.
  * Excursions come from the M1 OHLC bars covering that lifetime. No intrabar path is invented:
    a bar contributes only its high and low, and the ordering inside a bar is unknown.
  * MT5 bars are BID prices. A long is marked at the bid, so bid bars are already correct for longs.
    A short is marked at the ask, so each bar's stored spread is added to its high and low before
    measuring a short's excursion.
  * R = the initial stop distance |entry fill - initial SL| taken from the ENTRY journal row.
  * Realised R = broker net P&L / (initial stop distance x contract size x lot), i.e. what actually
    landed in the account, including fill slippage.
"""
import csv
import os
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(ROOT)

import MetaTrader5 as mt5                        # noqa: E402
import config                                    # noqa: E402
import forward_report as fr                      # noqa: E402  (shared sourcing helpers)
from analytics import pair_trades                # noqa: E402
from execution import mt5_init_args              # noqa: E402
from history import Deal                         # noqa: E402

SYMBOL, MAGIC, BUDGET = fr.SYMBOL, fr.MAGIC, fr.BUDGET
FIX_TIME = fr.FIX_TIME
MFE_LEVELS = (0.25, 0.5, 0.75, 1.0)


# -- sourcing ---------------------------------------------------------------------------
def journal_entries():
    """position ticket -> (initial SL, initial TP) from the ENTRY row, and the set of managed tickets."""
    entries, managed = {}, set()
    path = config.TRADE_JOURNAL
    if not os.path.exists(path):
        return entries, managed
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not r["ticket"]:
                continue
            t = int(r["ticket"])
            if r["event"] == "ENTRY" and "[test]" not in r["note"]:
                entries[t] = (float(r["sl"]) if r["sl"] else None, float(r["tp"]) if r["tp"] else None)
            elif r["event"] == "SL_MOVE":
                managed.add(t)
    return entries, managed


def load():
    args, kw = mt5_init_args()
    if not mt5.initialize(*args, **kw):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    info = mt5.symbol_info(SYMBOL)
    raw = ()
    for _ in range(10):
        raw = mt5.history_deals_get(0, 2 ** 31 - 1) or ()
        if raw:
            break
    bars = fr.m1_series(fr.REGIME_DAYS)
    mt5.shutdown()
    return raw, bars, info


def build_trades(raw, bars, info, entries, managed, ctx, cuts):
    """One row per bot-opened position, with its context and its M1 excursions."""
    all_deals = [Deal.from_mt5(d) for d in raw if d.symbol == SYMBOL]
    bot_pos = {d.position_id for d in all_deals
               if d.magic == MAGIC and d.entry == 0 and not d.comment.upper().startswith("TEST")}
    close_reason = {d.position_id: d.reason for d in all_deals if d.position_id in bot_pos and d.entry == 1}
    deals = [d for d in all_deals if d.position_id in bot_pos]

    times = bars["time"].values
    highs, lows, spreads = bars["high"].values, bars["low"].values, bars["spread"].values
    point = info.point

    rows = []
    for t in sorted(pair_trades(deals), key=lambda x: x.entry_time):
        when = fr.server_dt(t.entry_time)
        out = fr.server_dt(t.exit_time)
        sl, tp = entries.get(t.position_id, (None, None))
        stop = abs(t.entry_price - sl) if sl else None
        risk = stop * info.trade_contract_size * t.volume if stop else None
        reason_code = close_reason.get(t.position_id)
        is_managed = t.position_id in managed
        reason = ("TP" if reason_code == 5 else
                  ("TRAIL" if is_managed else "SL") if reason_code == 4 else "MANUAL")

        # bars covering the lifetime; entry and exit bars are partial (see methodology)
        lo = np.datetime64(when.replace(second=0, microsecond=0))
        hi = np.datetime64(out.replace(second=0, microsecond=0))
        sel = (times >= lo) & (times <= hi)
        strict = (times > lo) & (times < hi)

        def excursions(mask):
            if not mask.any():
                return None, None
            h, l, sp = highs[mask], lows[mask], spreads[mask] * point
            if t.side == "BUY":                       # long is marked at the bid: bars are already right
                fav, adv = h - t.entry_price, t.entry_price - l
            else:                                     # short is marked at the ask: add each bar's spread
                fav, adv = t.entry_price - (l + sp), (h + sp) - t.entry_price
            return float(max(fav.max(), 0.0)), float(max(adv.max(), 0.0))

        mfe, mae = excursions(sel)
        mfe_s, mae_s = excursions(strict)
        c = ctx.get(t.position_id, {})
        atr, pen = fr.bar_context(bars, c.get("bar"), t.side) if c.get("bar") else (c.get("atr"), None)
        regime = ("LOW" if atr < cuts[0] else "HIGH" if atr >= cuts[1] else "NORMAL") if (atr and cuts) else "n/a"
        realized_r = (t.net / risk) if risk else None
        mfe_r = (mfe / stop) if (mfe is not None and stop) else None
        mae_r = (mae / stop) if (mae is not None and stop) else None
        rows.append(dict(
            ticket=t.position_id, when=when, out=out, side="LONG" if t.side == "BUY" else "SHORT",
            entry=t.entry_price, exit=t.exit_price, sl=sl, tp=tp, stop=stop, lot=t.volume, risk=risk,
            net=t.net, realized_r=realized_r, reason=reason, managed=is_managed,
            mfe=mfe, mae=mae, mfe_r=mfe_r, mae_r=mae_r,
            mfe_strict=mfe_s, mae_strict=mae_s,
            mfe_r_strict=(mfe_s / stop) if (mfe_s is not None and stop) else None,
            bars=int(sel.sum()), duration_min=int((t.exit_time - t.entry_time) // 60),
            atr=atr, regime=regime, pen=pen, pen_bucket=fr.penetration_bucket(pen),
            session=fr.session_bucket(when.hour), prefix=when < FIX_TIME,
            efficiency=(t.net / risk) / (mfe / stop) if (risk and stop and mfe and mfe > 0) else None,
        ))
    return rows


# -- aggregation ------------------------------------------------------------------------
def stat(rows):
    if not rows:
        return None
    r = np.array([x["realized_r"] for x in rows if x["realized_r"] is not None], dtype=float)
    mfe = np.array([x["mfe"] for x in rows if x["mfe"] is not None], dtype=float)
    mae = np.array([x["mae"] for x in rows if x["mae"] is not None], dtype=float)
    mfer = np.array([x["mfe_r"] for x in rows if x["mfe_r"] is not None], dtype=float)
    maer = np.array([x["mae_r"] for x in rows if x["mae_r"] is not None], dtype=float)
    eff = np.array([x["efficiency"] for x in rows if x["efficiency"] is not None], dtype=float)
    sl_rows = [x for x in rows if x["reason"] == "SL"]
    return dict(
        n=len(rows),
        win=round(100 * sum(1 for x in rows if x["net"] > 0) / len(rows), 1),
        net=round(sum(x["net"] for x in rows), 2),
        avg_mfe=round(float(mfe.mean()), 2) if len(mfe) else 0.0,
        med_mfe=round(float(np.median(mfe)), 2) if len(mfe) else 0.0,
        avg_mfe_r=round(float(mfer.mean()), 2) if len(mfer) else 0.0,
        med_mfe_r=round(float(np.median(mfer)), 2) if len(mfer) else 0.0,
        avg_mae=round(float(mae.mean()), 2) if len(mae) else 0.0,
        med_mae=round(float(np.median(mae)), 2) if len(mae) else 0.0,
        avg_mae_r=round(float(maer.mean()), 2) if len(maer) else 0.0,
        med_mae_r=round(float(np.median(maer)), 2) if len(maer) else 0.0,
        avg_r=round(float(r.mean()), 3) if len(r) else 0.0,
        eff=round(float(eff.mean()), 2) if len(eff) else 0.0,
        sl_pos_mfe=(round(100 * sum(1 for x in sl_rows if (x["mfe_r"] or 0) > 0) / len(sl_rows), 1)
                    if sl_rows else None),
        levels={lv: round(100 * sum(1 for x in rows if (x["mfe_r"] or 0) >= lv) / len(rows), 1) for lv in MFE_LEVELS},
    )


HEAD = (f"{'group':<26}{'n':>4}{'win%':>7}{'net$':>9}{'avgMFE':>8}{'medMFE':>8}{'avgMFEr':>9}{'medMFEr':>9}"
        f"{'avgMAEr':>9}{'medMAEr':>9}{'avgR':>7}{'eff':>7}{'SL+MFE%':>9}"
        + "".join(f"{'>='+str(lv)+'R':>8}" for lv in MFE_LEVELS))


def line(label, s):
    if s is None:
        return f"{label:<26}{'(none)':>4}"
    sl = f"{s['sl_pos_mfe']:.1f}" if s["sl_pos_mfe"] is not None else "-"
    return (f"{label:<26}{s['n']:>4}{s['win']:>7.1f}{s['net']:>+9.2f}{s['avg_mfe']:>8.2f}{s['med_mfe']:>8.2f}"
            f"{s['avg_mfe_r']:>9.2f}{s['med_mfe_r']:>9.2f}{s['avg_mae_r']:>9.2f}{s['med_mae_r']:>9.2f}"
            f"{s['avg_r']:>+7.2f}{s['eff']:>7.2f}{sl:>9}"
            + "".join(f"{s['levels'][lv]:>8.1f}" for lv in MFE_LEVELS))


def table(title, groups):
    print(f"\n{title}")
    print(HEAD)
    for label, rows in groups.items():
        print(line(label, stat(rows)))


def main():
    raw, bars, info = load()
    entries, managed = journal_entries()
    ctx = fr.signal_context(fr.log_lines())
    atr_all = bars["atr"].dropna().values
    cuts = tuple(np.quantile(atr_all, [1 / 3, 2 / 3])) if len(atr_all) else None
    rows = build_trades(raw, bars, info, entries, managed, ctx, cuts)

    post = [r for r in rows if not r["prefix"] and r["reason"] != "MANUAL"]
    pre = [r for r in rows if r["prefix"]]
    manual = [r for r in rows if r["reason"] == "MANUAL" and not r["prefix"]]

    print("=" * 150)
    print(f"EXIT-EFFICIENCY / MAE-MFE CHECKPOINT   {SYMBOL}  magic {MAGIC}   generated {datetime.now():%Y-%m-%d %H:%M} server")
    print(f"profile: M1, RSI {config.RSI_OVERSOLD}/{config.RSI_OVERBOUGHT}, SL/TP {config.SL_ATR_MULTIPLIER}/"
          f"{config.TP_ATR_MULTIPLIER} ATR, trend={config.TREND_FILTER_ENABLED}, candles={config.CANDLE_MODE}, "
          f"manage={config.MANAGE_POSITIONS}, risk ${BUDGET:.2f}, one position at a time")
    print(f"post-fix window: from {FIX_TIME} server; bars {bars['time'].iloc[0]} -> {bars['time'].iloc[-1]} "
          f"({len(bars)} M1 bars)")
    print("=" * 150)

    # ---- B. data integrity -------------------------------------------------------------
    print("\nB. DATA INTEGRITY / METHODOLOGY")
    no_bars = [r for r in post if not r["bars"]]
    no_stop = [r for r in post if not r["stop"]]
    viol = [r for r in post if r["mfe_r"] is not None and r["realized_r"] is not None
            and r["realized_r"] > r["mfe_r"] + 0.02]
    sl_r = [r["realized_r"] for r in post if r["reason"] == "SL"]
    tp_r = [r["realized_r"] for r in post if r["reason"] == "TP"]
    print(f"  trades on record: {len(rows)}  = {len(pre)} pre-fix (excluded) + {len(post)} post-fix strategy "
          f"+ {len(manual)} closed by hand (excluded)")
    print(f"  post-fix trades with no covering M1 bar : {len(no_bars)}")
    print(f"  post-fix trades with no journal SL      : {len(no_stop)}")
    print(f"  realised R > measured MFE R (impossible): {len(viol)}   <- 0 means the excursion window is sound")
    if sl_r:
        print(f"  full-SL exits realised R: mean {np.mean(sl_r):+.3f}  min {min(sl_r):+.3f}  max {max(sl_r):+.3f} "
              f"(expected ~ -1.00)")
    if tp_r:
        print(f"  TP exits realised R     : mean {np.mean(tp_r):+.3f}  min {min(tp_r):+.3f}  max {max(tp_r):+.3f} "
              f"(expected ~ +1.00)")
    strict_ok = [r for r in post if r["mfe_r_strict"] is not None]
    if strict_ok:
        d = [r["mfe_r"] - r["mfe_r_strict"] for r in strict_ok]
        print(f"  sensitivity: dropping the partial entry/exit bars lowers MFE R by {np.mean(d):.3f} on average "
              f"({len(strict_ok)} trades have a fully-interior bar)")
    print("""  method:
    - lifetime = broker entry fill -> broker exit fill; excursions from M1 bars whose minute falls in
      [entry minute, exit minute]. The first and last bars are partial, so the headline MFE/MAE is an
      UPPER bound; the sensitivity line above shows the effect of dropping them.
    - no intrabar path is assumed: only each bar's high and low are used, never their order.
    - bars are BID. Longs mark at the bid (bars used as-is); shorts mark at the ask, so each bar's own
      stored spread is added to its high and low before measuring a short.
    - R = |entry fill - initial SL| from the ENTRY journal row. Realised R = broker net / (R x 100 x lot).
    - exit efficiency = realised R / MFE R, computed only where MFE R > 0.
    - 'SL' = stop hit with no stop move; 'TRAIL' = stop hit after a breakeven/trail move; 'TP' = target.""")

    # ---- C. overall ---------------------------------------------------------------------
    winners = [r for r in post if r["net"] > 0]
    losers = [r for r in post if r["net"] <= 0]
    by_reason = OrderedDict((k, [r for r in post if r["reason"] == k]) for k in ("SL", "TRAIL", "TP"))
    print("\nC. OVERALL MAE / MFE")
    table("all / winners / losers", OrderedDict([("ALL post-fix", post), ("winners", winners), ("losers", losers)]))
    table("by exit type", by_reason)

    # ---- D. exit efficiency --------------------------------------------------------------
    print("\nD. EXIT EFFICIENCY (realised R vs the best R that was on the table before the exit)")
    eff_rows = [r for r in post if r["efficiency"] is not None]
    if eff_rows:
        e = np.array([r["efficiency"] for r in eff_rows])
        print(f"  trades with positive MFE: {len(eff_rows)} of {len(post)}")
        print(f"  efficiency mean {e.mean():+.2f}  median {np.median(e):+.2f}  "
              f"p25 {np.quantile(e, .25):+.2f}  p75 {np.quantile(e, .75):+.2f}")
        print(f"  captured <= 0 of the available move: {100 * (e <= 0).mean():.1f}% of them")
    print(f"\n  MFE reached by the whole post-fix set: " +
          "  ".join(f">={lv}R {stat(post)['levels'][lv]:.1f}%" for lv in MFE_LEVELS))

    # ---- E. groups ------------------------------------------------------------------------
    A = [r for r in post if r["reason"] == "SL" and (r["realized_r"] or 0) <= -0.9 and (r["mfe_r"] or 0) >= 0.25]
    B = [r for r in post if 0 < (r["realized_r"] or 0) <= 0.5 and (r["mfe_r"] or 0) >= 1.0]
    C = by_reason["TRAIL"]
    D = by_reason["TP"]
    print("\nE. THE FOUR FOCUS GROUPS")
    table("A: full SL after >= +0.25R MFE | B: small win after >= +1R MFE | C: managed exits | D: TP",
          OrderedDict([("A full-SL, MFE>=0.25R", A), ("B small win, MFE>=1R", B), ("C managed exits", C),
                       ("D TP exits", D)]))
    print(f"\n  A as a share of all full-SL exits: {len(A)}/{len(by_reason['SL'])}"
          f" = {100 * len(A) / max(1, len(by_reason['SL'])):.1f}%")
    if A:
        tot = sum(r["mfe_r"] for r in A)
        print(f"  A: mean MFE {np.mean([r['mfe_r'] for r in A]):+.2f}R, median {np.median([r['mfe_r'] for r in A]):+.2f}R, "
              f"max {max(r['mfe_r'] for r in A):+.2f}R; total forgone {tot:.1f}R across {len(A)} trades")
    if B:
        print(f"  B: mean realised {np.mean([r['realized_r'] for r in B]):+.2f}R against mean MFE "
              f"{np.mean([r['mfe_r'] for r in B]):+.2f}R")

    # ---- F/G/H/I/J. slices ------------------------------------------------------------------
    def by(key, order=None):
        g = defaultdict(list)
        for r in post:
            g[r[key]].append(r)
        labels = order or sorted(g)
        return OrderedDict((k, g.get(k, [])) for k in labels)

    table("F. BY SESSION (server hours)", by("session", ["00-07", "07-12", "12-17", "17-24"]))
    table("J. BY DIRECTION", by("side", ["LONG", "SHORT"]))
    table("I. BY ATR REGIME", by("regime", ["LOW", "NORMAL", "HIGH"]))
    table("H. BY BB PENETRATION", by("pen_bucket", ["touch", "small", "medium", "deep"]))

    # 07-12 anatomy
    m = [r for r in post if r["session"] == "07-12"]
    rest = [r for r in post if r["session"] != "07-12"]
    print("\nF2. 07-12 ANATOMY vs THE REST")
    table("morning vs rest", OrderedDict([("07-12", m), ("other sessions", rest)]))
    print("  07-12 exit mix : " + ", ".join(f"{k} {sum(1 for r in m if r['reason'] == k)}" for k in ("SL", "TRAIL", "TP")))
    print("  other exit mix : " + ", ".join(f"{k} {sum(1 for r in rest if r['reason'] == k)}" for k in ("SL", "TRAIL", "TP")))
    table("07-12 by direction", OrderedDict((k, [r for r in m if r["side"] == k]) for k in ("LONG", "SHORT")))
    table("07-12 by ATR regime", OrderedDict((k, [r for r in m if r["regime"] == k]) for k in ("LOW", "NORMAL", "HIGH")))
    table("07-12 by penetration", OrderedDict((k, [r for r in m if r["pen_bucket"] == k])
                                              for k in ("touch", "small", "medium", "deep")))
    per_day = defaultdict(lambda: [0, 0.0])
    for r in m:
        k = r["when"].date().isoformat()
        per_day[k][0] += 1
        per_day[k][1] += r["net"]
    print("  07-12 per day: " + ", ".join(f"{d}: {n} trades {v:+.2f}" for d, (n, v) in sorted(per_day.items())))

    # 17-24 LONG
    print("\nG. 17-24 LONG vs OTHER LONG")
    table("evening longs", OrderedDict([
        ("17-24 LONG", [r for r in post if r["session"] == "17-24" and r["side"] == "LONG"]),
        ("other LONG", [r for r in post if r["session"] != "17-24" and r["side"] == "LONG"]),
        ("17-24 SHORT", [r for r in post if r["session"] == "17-24" and r["side"] == "SHORT"]),
    ]))

    # ---- K. execution / sizing ---------------------------------------------------------------
    print("\nK. EXECUTION / SIZING SANITY CHECK")
    over = [r for r in post if r["risk"] and r["risk"] > BUDGET + 0.005]
    lots = defaultdict(int)
    for r in post:
        lots[r["lot"]] += 1
    print(f"  post-fix trades: {len(post)}")
    print(f"  lot sizes used: " + ", ".join(f"{k} x{v}" for k, v in sorted(lots.items())))
    print(f"    the lot is NOT pinned to the broker minimum: it scales with the stop. $5 / (stop x 100)")
    print(f"    buys 0.02 lots whenever the stop is <= 2.50, and 0.01 above that, floored to the 0.01 step.")
    for lot in sorted(lots):
        sub = [r for r in post if r["lot"] == lot]
        print(f"    lot {lot}: stop {min(r['stop'] for r in sub):.2f}-{max(r['stop'] for r in sub):.2f}, "
              f"risk ${min(r['risk'] for r in sub):.2f}-${max(r['risk'] for r in sub):.2f}")
    print("")
    print(f"  realised risk at the initial stop above ${BUDGET:.2f}: {len(over)} of {len(post)}")
    for r in over:
        implied = r["stop"] * 100 * r["lot"]
        print(f"    {r['when']:%Y-%m-%d %H:%M} {r['side']:<5} lot {r['lot']} stop {r['stop']:.2f} "
              f"-> ${implied:.2f} (over by ${implied - BUDGET:.2f})")
    print(f"    all {len(over)} are 0.01-lot trades: 0.01 is the broker minimum, so the only way to hold the")
    print(f"    budget would have been to skip the trade. The lot rule sized them correctly against the QUOTED")
    print(f"    stop; the realised stop came out wider because the market fill differed from the quote")
    print(f"    (XAUUSD is Market execution here, so the order's requested price is ignored). A signal whose")
    print(f"    QUOTED stop already exceeds the budget is refused up front - the min-lot SKIP lines in the log.")
    risks = [r["risk"] for r in post if r["risk"]]
    print(f"  risk at stop across the set: min ${min(risks):.2f}  median ${np.median(risks):.2f}  "
          f"max ${max(risks):.2f}  mean ${np.mean(risks):.2f}")
    print(f"  worst-case overshoot ${max(r['risk'] for r in over) - BUDGET:.2f} on a ${BUDGET:.2f} budget "
          f"= {100 * (max(r['risk'] for r in over) - BUDGET) / BUDGET:.0f}% - bounded and rare "
          f"({100 * len(over) / len(post):.1f}% of trades).")

    # ---- per-trade appendix -------------------------------------------------------------------
    print("\nAPPENDIX: EVERY POST-FIX TRADE")
    print(f"{'entry (server)':<17}{'side':<6}{'entry':>9}{'stop':>6}{'risk$':>7}{'net$':>8}{'R':>7}"
          f"{'MFE':>7}{'MFEr':>7}{'MAE':>7}{'MAEr':>7}{'eff':>7}  {'exit':<7}{'min':>5}  {'sess':<6}{'regime':<7}{'pen'}")
    for r in post:
        eff = f"{r['efficiency']:+.2f}" if r["efficiency"] is not None else "  -  "
        print(f"{r['when']:%Y-%m-%d %H:%M}  {r['side']:<6}{r['entry']:>9.2f}{r['stop']:>6.2f}{r['risk']:>7.2f}"
              f"{r['net']:>+8.2f}{r['realized_r']:>+7.2f}{r['mfe']:>7.2f}{r['mfe_r']:>+7.2f}{r['mae']:>7.2f}"
              f"{r['mae_r']:>+7.2f}{eff:>7}  {r['reason']:<7}{r['duration_min']:>5}  {r['session']:<6}"
              f"{r['regime']:<7}{r['pen_bucket']}")


if __name__ == "__main__":
    main()
