"""Entry-quality diagnosis (research only, files only): what good and bad entries look like in the first seconds
and minutes after the fill, on the same 299 verified tick paths as the two previous studies.

    python docs/research/entry_quality_analysis.py > out.md

Descriptive statistics only. Windows, thresholds and groups are the ones fixed in the task; nothing is searched or
optimised. Reuses load_trades() of small_profit_small_loss_analysis.py (same exclusions, same marking: longs at the
bid, shorts at the ask, no interpolation, tick order preserved, daily-break quotes left out). Existing entry features
come from the bot's own SIGNAL log lines (RSI, ATR, signal-bar close, candle pattern, trend EMA) and the 09-15
forward report (Bollinger penetration for the first 200 trades). No terminal is attached.
"""
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from small_profit_small_loss_analysis import load_trades, stats, SPLIT_MS, SCALP, ROOT   # noqa: E402
import path_recorder as pr                                                                # noqa: E402

WINDOWS = (5, 10, 20, 30, 60, 120, 300)
FAV = (0.10, 0.15, 0.20, 0.25, 0.33, 0.50)
ADV = (-0.10, -0.15, -0.20, -0.25, -0.33)
TIMES = (10, 30, 60, 120)
FULL = -0.9                                   # final R at or below this = full loss


def med(xs, nd=2):
    xs = [x for x in xs if x is not None]
    return f"{st.median(xs):.{nd}f}" if xs else "n/a"


def mean(xs, nd=2):
    xs = [x for x in xs if x is not None]
    return f"{sum(xs) / len(xs):.{nd}f}" if xs else "n/a"


def pct(k, n):
    return f"{100 * k / n:.0f}%" if n else "n/a"


def first_time(t, level):
    """Seconds from the fill to the first tick at/beyond level (>= for +, <= for -); None if never."""
    for r, ms in zip(t["r"], t["msc"]):
        if (level > 0 and r >= level - 1e-9) or (level < 0 and r <= level + 1e-9):
            return (ms - t["fill_ms"]) / 1000
    return None


def window(t, secs):
    """(mfe, mae, r_at_end) over ticks within `secs` of the fill; None if no tick in the window."""
    rs = [r for r, ms in zip(t["r"], t["msc"]) if ms - t["fill_ms"] <= secs * 1000]
    if not rs:
        return None, None, None
    return max(rs), min(rs), rs[-1]


def load_signals():
    """SIGNAL lines of the bot log: (epoch s, side, rsi, atr, close, ema, pattern)."""
    out = []
    pat = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) .*SIGNAL (BUY|SELL) bar=\S+ \S+ close=([\d.]+) rsi=([\d.]+) atr=([\d.]+) ema=(\S+) pattern=(\S+)")
    with open(os.path.join(SCALP, "logs", "bot.log"), encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                out.append((ts, "LONG" if m.group(2) == "BUY" else "SHORT", float(m.group(4)), float(m.group(5)),
                            float(m.group(3)), m.group(6), m.group(7)))
    return out


def load_pen_values():
    vals = {}
    rp = os.path.join(ROOT, "docs", "research", "forward_validation_2026-09-15.txt")
    pat = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d)\s+(LONG|SHORT)\s+([\d.]+)\s+.*?\s(LOW|NORMAL|HIGH)\s+([\d.]+)\s+(touch|small|medium|deep)")
    if os.path.exists(rp):
        for line in open(rp, encoding="utf-8"):
            m = pat.match(line)
            if m:
                vals[(m.group(1), m.group(2), round(float(m.group(3)), 2))] = float(m.group(5))
    return vals


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    trades, excluded = load_trades()
    signals = load_signals()
    pens = load_pen_values()
    for t in trades:
        t["r"] = [u / t["risk"] for u in t["upnl"]]
        t["R"] = t["net"] / t["risk"]
        t["win"] = t["net"] > 0
        t["full"] = t["R"] <= FULL
        t["dur"] = (t["exit_ms"] - t["fill_ms"]) / 1000
        t["mfe"], t["mae"] = max(t["r"]), min(t["r"])
        t["half"] = "A" if t["fill_ms"] < SPLIT_MS else "B"
        for lv in FAV + ADV + (0.75, 1.0, -0.50, -0.75, -1.0):
            t[f"t{lv:+.2f}"] = first_time(t, lv)
        for w in WINDOWS:
            t[f"mfe{w}"], t[f"mae{w}"], t[f"r{w}"] = window(t, w)
        # spread around entry from the raw path
        src = os.path.join(SCALP, "logs", "paths") if t["src"] == "live" else os.path.join(ROOT, "logs", "replay_paths_2026-09-07_11")
        d = pr.load_path(os.path.join(src, f"XAUUSD_{t['pid']}.jsonl"))
        tk = [x for x in d["ticks"] if x.get("spread_pts") is not None and x["spread_pts"] <= 300]
        q = d["open"]["quote_before_fill"]
        t["sp_entry"] = round((q["ask"] - q["bid"]) / 0.01, 1) if q else None
        s10 = [x["spread_pts"] for x in tk if x["msc"] - t["fill_ms"] <= 10_000]
        s30 = [x["spread_pts"] for x in tk if x["msc"] - t["fill_ms"] <= 30_000]
        s60 = [x["spread_pts"] for x in tk if x["msc"] - t["fill_ms"] <= 60_000]
        t["sp_min10"], t["sp_max10"] = (min(s10), max(s10)) if s10 else (None, None)
        t["sp_avg30"] = sum(s30) / len(s30) if s30 else None
        t["sp_max60"] = max(s60) if s60 else None
        # existing entry features from the SIGNAL line just before the fill (same side, within 90 s)
        fill_s = t["fill_ms"] / 1000
        cands = [s for s in signals if s[1] == t["side"] and fill_s - 90 <= s[0] <= fill_s + 2]
        if cands:
            _, _, rsi, atr, close, ema, pattern = cands[-1]
            t["rsi"], t["atr_sig"], t["pattern"], t["trend"] = rsi, atr, pattern, ("off" if ema == "nan" else "on")
            t["rsi_excess"] = (35 - rsi) if t["side"] == "LONG" else (rsi - 65)           # how far beyond the 35/65 trigger
            drift = (t["entry"] - close) if t["side"] == "LONG" else (close - t["entry"])   # + = filled worse than the bar close
            t["drift_r"] = drift / (t["risk"] / (100 * t["lot"]))
        else:
            t["rsi"] = t["atr_sig"] = t["pattern"] = t["trend"] = t["rsi_excess"] = t["drift_r"] = None
        t["pen_val"] = pens.get((t["fill"].strftime("%Y-%m-%d %H:%M"), t["side"], round(t["entry"], 2)))
        # group A-E by the highest favourable threshold reached
        m = t["mfe"]
        t["grp"] = "E +1.00R" if m >= 1.0 - 1e-9 else "D +0.75R" if m >= 0.75 - 1e-9 else "C +0.50R" if m >= 0.5 - 1e-9 else "B +0.25R" if m >= 0.25 - 1e-9 else "A never +0.25R"
    n = len(trades)
    winners = [t for t in trades if t["win"]]
    losers = [t for t in trades if not t["win"]]
    fulls = [t for t in trades if t["full"]]
    doa = [t for t in trades if t["grp"].startswith("A")]
    up50 = [t for t in trades if t["mfe"] >= 0.5 - 1e-9]
    out = []
    p = out.append

    p(f"Trades: **{n}** (excluded {dict(excluded)}); winners {len(winners)}, losers {len(losers)}, full losses (final ≤ −0.9R) {len(fulls)}, "
      f"never +0.25R {len(doa)}, reached +0.50R {len(up50)}; half A {sum(1 for t in trades if t['half'] == 'A')}, half B "
      f"{sum(1 for t in trades if t['half'] == 'B')}. SIGNAL line matched for {sum(1 for t in trades if t['rsi'] is not None)} trades; "
      f"penetration value for {sum(1 for t in trades if t['pen_val'] is not None)}. Median trade duration {med([t['dur'] for t in trades], 0)} s "
      f"(winners {med([t['dur'] for t in winners], 0)} s, full losses {med([t['dur'] for t in fulls], 0)} s).")

    # ---------------------------------------------------------------- Part 1
    p("\n### Part 1. Early path by window (all 299 trades; a window that outlives the trade covers its whole life)\n")
    p("| window | trades with a tick in it | median MFE | median MAE | median R at end | reached +0.25R | +0.33R | +0.50R | −0.25R | −0.50R | −0.75R | −1.00R |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for w in WINDOWS:
        have = [t for t in trades if t[f"mfe{w}"] is not None]
        def reached(lv):
            k = sum(1 for t in trades if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w)
            return f"{k} ({pct(k, n)})"
        p(f"| {w} s | {len(have)} | {med([t[f'mfe{w}'] for t in have])} | {med([t[f'mae{w}'] for t in have])} | {med([t[f'r{w}'] for t in have])} | "
          f"{reached(0.25)} | {reached(0.33)} | {reached(0.50)} | {reached(-0.25)} | {reached(-0.50)} | {reached(-0.75)} | {reached(-1.0)} |")
    p("\n| first touch of | trades | median s | mean s | 25th pct s | 75th pct s |")
    p("| --- | ---: | ---: | ---: | ---: | ---: |")
    for lv in (0.25, -0.25, 0.50, -0.50):
        xs = sorted(t[f"t{lv:+.2f}"] for t in trades if t[f"t{lv:+.2f}"] is not None)
        if xs:
            p(f"| {lv:+.2f}R | {len(xs)} | {st.median(xs):.0f} | {sum(xs)/len(xs):.0f} | {xs[len(xs)//4]:.0f} | {xs[3*len(xs)//4]:.0f} |")

    # ---------------------------------------------------------------- Part 2
    p("\n### Part 2. Groups by the highest favourable level reached\n")
    p("| group | trades | win rate | net | expectancy | PF | avg initial risk $ | median MFE | median MAE | mean time to first +0.10R | mean time to +0.25R | mean time to first −0.10R | mean time to −0.25R | full losses |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    groups = defaultdict(list)
    for t in trades:
        groups[t["grp"]].append(t)
    for g in sorted(groups):
        ts = groups[g]
        s = stats([t["net"] for t in ts])
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        p(f"| {g} | {len(ts)} | {s['win_rate']:.0f}% | {s['net']:+.2f} | {s['expectancy']:+.2f} | {pf} | {mean([t['risk'] for t in ts])} | "
          f"{med([t['mfe'] for t in ts])} | {med([t['mae'] for t in ts])} | {mean([t['t+0.10'] for t in ts], 0)} s | {mean([t['t+0.25'] for t in ts], 0)} s | "
          f"{mean([t['t-0.10'] for t in ts], 0)} s | {mean([t['t-0.25'] for t in ts], 0)} s | {sum(1 for t in ts if t['full'])} |")
    p("\nGroup A versus winners in the first 10 / 30 / 60 seconds:\n")
    p("| population | n | window | median MFE | median MAE | median R at end | reached +0.10R by then | reached −0.10R | reached −0.25R | no tick yet |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, ts in (("A never +0.25R", doa), ("winners", winners), ("full losses", fulls), ("large winners ≥ +0.75R", [t for t in trades if t["R"] >= 0.75])):
        for w in (10, 30, 60):
            have = [t for t in ts if t[f"mfe{w}"] is not None]
            p(f"| {name} | {len(ts)} | {w} s | {med([t[f'mfe{w}'] for t in have])} | {med([t[f'mae{w}'] for t in have])} | {med([t[f'r{w}'] for t in have])} | "
              f"{pct(sum(1 for t in ts if t['t+0.10'] is not None and t['t+0.10'] <= w), len(ts))} | "
              f"{pct(sum(1 for t in ts if t['t-0.10'] is not None and t['t-0.10'] <= w), len(ts))} | "
              f"{pct(sum(1 for t in ts if t['t-0.25'] is not None and t['t-0.25'] <= w), len(ts))} | {len(ts) - len(have)} |")

    # ---------------------------------------------------------------- Part 3 / 4
    def reach_table(levels, title):
        p(f"\n### {title}\n")
        p("| level | within | trades reaching it | eventually full loss | eventually profitable | mean final R | median final R | trades NOT reaching it | their full-loss rate | their win rate |")
        p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for lv in levels:
            for w in TIMES:
                yes = [t for t in trades if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w]
                no = [t for t in trades if t not in yes]
                p(f"| {lv:+.2f}R | {w} s | {len(yes)} ({pct(len(yes), n)}) | {pct(sum(1 for t in yes if t['full']), len(yes))} | "
                  f"{pct(sum(1 for t in yes if t['win']), len(yes))} | {mean([t['R'] for t in yes])} | {med([t['R'] for t in yes])} | "
                  f"{len(no)} | {pct(sum(1 for t in no if t['full']), len(no))} | {pct(sum(1 for t in no if t['win']), len(no))} |")
    p(f"\nBase rates for the whole set: full loss {pct(len(fulls), n)}, profitable {pct(len(winners), n)}, mean final R {mean([t['R'] for t in trades])}, median {med([t['R'] for t in trades])}.")
    reach_table(ADV, "Part 3. Early adverse movement: reaching a level within a time (only the tick path decides)")
    reach_table(FAV, "Part 4. Early favourable movement")

    # ---------------------------------------------------------------- Part 5
    p("\n### Part 5. Speed of the move (medians; 'n/a' = never reached)\n")
    p("| population | n | R at 10 s | R at 30 s | R at 60 s | R/s over first 30 s | time to +0.10R | time to +0.25R | time to −0.10R | time to −0.25R | share reaching +0.10R | share reaching −0.10R | time to MFE | duration |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, ts in (("winners", winners), ("losers (net ≤ 0)", losers), ("full losses", fulls), ("never +0.25R", doa), ("reached +0.50R", up50)):
        tmfe = []
        for t in ts:
            i = t["r"].index(t["mfe"])
            tmfe.append((t["msc"][i] - t["fill_ms"]) / 1000)
        p(f"| {name} | {len(ts)} | {med([t['r10'] for t in ts])} | {med([t['r30'] for t in ts])} | {med([t['r60'] for t in ts])} | "
          f"{med([t['r30'] / 30 for t in ts if t['r30'] is not None], 4)} | {med([t['t+0.10'] for t in ts], 0)} s | {med([t['t+0.25'] for t in ts], 0)} s | "
          f"{med([t['t-0.10'] for t in ts], 0)} s | {med([t['t-0.25'] for t in ts], 0)} s | {pct(sum(1 for t in ts if t['t+0.10'] is not None), len(ts))} | "
          f"{pct(sum(1 for t in ts if t['t-0.10'] is not None), len(ts))} | {med(tmfe, 0)} s | {med([t['dur'] for t in ts], 0)} s |")

    # ---------------------------------------------------------------- Part 6
    p("\n### Part 6. Spread around the entry (points; 1 point = $0.01 on 0.01 lot; medians, with the 75th percentile in brackets)\n")
    p("| population | n | spread at entry | min spread first 10 s | max spread first 10 s | avg spread first 30 s | max spread first 60 s | entry spread as % of initial risk |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    def q75(xs):
        xs = sorted(x for x in xs if x is not None)
        return f"{xs[3 * len(xs) // 4]:.0f}" if xs else "n/a"
    for name, ts in (("all", trades), ("winners", winners), ("losers", losers), ("full losses", fulls), ("never +0.25R", doa), ("reached +0.50R", up50)):
        cell = lambda k: f"{med([t[k] for t in ts], 0)} ({q75([t[k] for t in ts])})"
        risk_pts = [t["sp_entry"] / (t["risk"] / (100 * t["lot"]) / 0.01) * 100 for t in ts if t["sp_entry"] is not None]
        p(f"| {name} | {len(ts)} | {cell('sp_entry')} | {cell('sp_min10')} | {cell('sp_max10')} | {cell('sp_avg30')} | {cell('sp_max60')} | {med(risk_pts, 1)}% |")
    hi = [t for t in trades if t["sp_entry"] is not None and t["sp_entry"] >= 45]
    lo = [t for t in trades if t["sp_entry"] is not None and t["sp_entry"] < 45]
    p(f"\nEntry spread ≥ 45 points (top quarter): {len(hi)} trades, full-loss rate {pct(sum(1 for t in hi if t['full']), len(hi))}, win rate "
      f"{pct(sum(1 for t in hi if t['win']), len(hi))}, expectancy {mean([t['net'] for t in hi])}; below 45: {len(lo)} trades, full-loss rate "
      f"{pct(sum(1 for t in lo if t['full']), len(lo))}, win rate {pct(sum(1 for t in lo if t['win']), len(lo))}, expectancy {mean([t['net'] for t in lo])}. "
      f"(45 points is the observed upper quartile, used only to describe the two populations.)")

    # ---------------------------------------------------------------- Part 7
    p("\n### Part 7. Existing entry features (as recorded at the time: SIGNAL log line, opening order, 09-15 report)\n")
    p("Numeric features, medians (25th–75th percentile):\n")
    p("| feature | all | winners | losers | full losses | never +0.25R |")
    p("| --- | ---: | ---: | ---: | ---: | ---: |")
    def dist(ts, k):
        xs = sorted(t[k] for t in ts if t.get(k) is not None)
        return f"{st.median(xs):.2f} ({xs[len(xs)//4]:.2f}–{xs[3*len(xs)//4]:.2f}) n={len(xs)}" if xs else "n/a"
    for label, k in (("RSI at the signal bar", "rsi"), ("RSI beyond the 35/65 trigger (points)", "rsi_excess"), ("M1 ATR at the signal", "atr_sig"),
                     ("initial risk $", "risk"), ("fill vs signal-bar close, adverse, in R", "drift_r"), ("Bollinger penetration (first 200)", "pen_val"),
                     ("entry spread (points)", "sp_entry")):
        p(f"| {label} | {dist(trades, k)} | {dist(winners, k)} | {dist(losers, k)} | {dist(fulls, k)} | {dist(doa, k)} |")
    p("\nCategorical features (share of the category that ended as a full loss / never reached +0.25R / won; expectancy $):\n")
    p("| feature | value | trades | full loss | never +0.25R | win | expectancy | half A exp (n) | half B exp (n) |")
    p("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    def rsi_bucket(t):
        x = t.get("rsi_excess")
        return None if x is None else "0–2.5" if x < 2.5 else "2.5–5" if x < 5 else "5–10" if x < 10 else "10+"
    cats = (("direction", lambda t: t["side"], ("LONG", "SHORT")), ("session", lambda t: t["sess"], ("00-07", "07-12", "12-17", "17-24")),
            ("ATR regime", lambda t: t["regime"], ("LOW", "NORMAL", "HIGH")), ("Bollinger penetration bucket", lambda t: t["pen"], ("touch", "small", "medium", "deep", "n/a")),
            ("candle pattern at the signal bar", lambda t: t.get("pattern"), None), ("RSI beyond trigger (points)", rsi_bucket, ("0–2.5", "2.5–5", "5–10", "10+")),
            ("trend filter", lambda t: t.get("trend"), ("off", "on")), ("lot", lambda t: str(t["lot"]), ("0.01", "0.02")))
    for label, keyf, order in cats:
        vals = order or sorted({keyf(t) for t in trades if keyf(t) is not None}, key=str)
        for v in vals:
            ts = [t for t in trades if keyf(t) == v]
            if not ts:
                continue
            ha = [t for t in ts if t["half"] == "A"]; hb = [t for t in ts if t["half"] == "B"]
            p(f"| {label} | {v} | {len(ts)} | {pct(sum(1 for t in ts if t['full']), len(ts))} | {pct(sum(1 for t in ts if t['grp'].startswith('A')), len(ts))} | "
              f"{pct(sum(1 for t in ts if t['win']), len(ts))} | {mean([t['net'] for t in ts])} | {mean([t['net'] for t in ha])} ({len(ha)}) | {mean([t['net'] for t in hb])} ({len(hb)}) |")

    # ---------------------------------------------------------------- Part 8
    p("\n### Part 8. First 60 seconds by session\n")
    p("| session | n | median MAE 60 s | median MFE 60 s | +0.25R within 60 s | −0.25R within 60 s | reached +0.50R (any time) | never +0.25R | full loss | expectancy | half A exp (n) | half B exp (n) |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    def sess_row(label, ts):
        ha = [t for t in ts if t["half"] == "A"]; hb = [t for t in ts if t["half"] == "B"]
        p(f"| {label} | {len(ts)} | {med([t['mae60'] for t in ts])} | {med([t['mfe60'] for t in ts])} | "
          f"{pct(sum(1 for t in ts if t['t+0.25'] is not None and t['t+0.25'] <= 60), len(ts))} | "
          f"{pct(sum(1 for t in ts if t['t-0.25'] is not None and t['t-0.25'] <= 60), len(ts))} | "
          f"{pct(sum(1 for t in ts if t['mfe'] >= 0.5 - 1e-9), len(ts))} | {pct(sum(1 for t in ts if t['grp'].startswith('A')), len(ts))} | "
          f"{pct(sum(1 for t in ts if t['full']), len(ts))} | {mean([t['net'] for t in ts])} | {mean([t['net'] for t in ha])} ({len(ha)}) | {mean([t['net'] for t in hb])} ({len(hb)}) |")
    for s_ in ("00-07", "07-12", "12-17", "17-24"):
        sess_row(s_, [t for t in trades if t["sess"] == s_])

    # ---------------------------------------------------------------- Part 9
    p("\n### Part 9. LONG versus SHORT (early path)\n")
    p("| direction | half | n | median MAE 30 s | median MAE 60 s | median MFE 60 s | median time to +0.25R | median time to −0.25R | never +0.25R | −0.25R within 30 s | full loss | win | expectancy |")
    p("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for side in ("LONG", "SHORT"):
        for half in ("all", "A", "B"):
            ts = [t for t in trades if t["side"] == side and (half == "all" or t["half"] == half)]
            p(f"| {side} | {half} | {len(ts)} | {med([t['mae30'] for t in ts])} | {med([t['mae60'] for t in ts])} | {med([t['mfe60'] for t in ts])} | "
              f"{med([t['t+0.25'] for t in ts], 0)} s | {med([t['t-0.25'] for t in ts], 0)} s | {pct(sum(1 for t in ts if t['grp'].startswith('A')), len(ts))} | "
              f"{pct(sum(1 for t in ts if t['t-0.25'] is not None and t['t-0.25'] <= 30), len(ts))} | {pct(sum(1 for t in ts if t['full']), len(ts))} | "
              f"{pct(sum(1 for t in ts if t['win']), len(ts))} | {mean([t['net'] for t in ts])} |")

    # ---------------------------------------------------------------- Part 10
    p("\n### Part 10. Half A (7–11 Sep) versus half B (14–17 Sep): the key early-path findings\n")
    p("| finding | half A | half B | overall |")
    p("| --- | ---: | ---: | ---: |")
    def both(label, f):
        a = [t for t in trades if t["half"] == "A"]; b = [t for t in trades if t["half"] == "B"]
        p(f"| {label} | {f(a)} | {f(b)} | {f(trades)} |")
    both("trades", lambda ts: str(len(ts)))
    both("expectancy $", lambda ts: mean([t["net"] for t in ts]))
    both("never +0.25R (share)", lambda ts: pct(sum(1 for t in ts if t["grp"].startswith("A")), len(ts)))
    both("full-loss rate", lambda ts: pct(sum(1 for t in ts if t["full"]), len(ts)))
    both("median MAE first 30 s", lambda ts: med([t["mae30"] for t in ts]))
    both("median MFE first 30 s", lambda ts: med([t["mfe30"] for t in ts]))
    for lv, w in ((-0.10, 10), (-0.25, 30), (-0.25, 60), (-0.33, 60)):
        both(f"reached {lv:+.2f}R within {w} s: share of trades", lambda ts, lv=lv, w=w: pct(sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w), len(ts)))
        both(f"… their full-loss rate", lambda ts, lv=lv, w=w: pct(sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w and t["full"]),
                                                                    sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w)))
    for lv, w in ((0.10, 10), (0.25, 30), (0.25, 60), (0.33, 60)):
        both(f"reached {lv:+.2f}R within {w} s: share of trades", lambda ts, lv=lv, w=w: pct(sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w), len(ts)))
        both(f"… their win rate", lambda ts, lv=lv, w=w: pct(sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w and t["win"]),
                                                              sum(1 for t in ts if t[f"t{lv:+.2f}"] is not None and t[f"t{lv:+.2f}"] <= w)))
    both("winners: median time to +0.10R (s)", lambda ts: med([t["t+0.10"] for t in ts if t["win"]], 0))
    both("full losses: median time to −0.10R (s)", lambda ts: med([t["t-0.10"] for t in ts if t["full"]], 0))
    both("entry spread ≥ 45 pts: full-loss rate", lambda ts: pct(sum(1 for t in ts if t["sp_entry"] is not None and t["sp_entry"] >= 45 and t["full"]), sum(1 for t in ts if t["sp_entry"] is not None and t["sp_entry"] >= 45)))
    both("entry spread < 45 pts: full-loss rate", lambda ts: pct(sum(1 for t in ts if t["sp_entry"] is not None and t["sp_entry"] < 45 and t["full"]), sum(1 for t in ts if t["sp_entry"] is not None and t["sp_entry"] < 45)))
    both("07-12 session expectancy $", lambda ts: mean([t["net"] for t in ts if t["sess"] == "07-12"]))
    both("LONG expectancy $ / SHORT expectancy $", lambda ts: f"{mean([t['net'] for t in ts if t['side'] == 'LONG'])} / {mean([t['net'] for t in ts if t['side'] == 'SHORT'])}")
    both("RSI beyond trigger ≥ 5: full-loss rate", lambda ts: pct(sum(1 for t in ts if t.get("rsi_excess") is not None and t["rsi_excess"] >= 5 and t["full"]), sum(1 for t in ts if t.get("rsi_excess") is not None and t["rsi_excess"] >= 5)))
    both("RSI beyond trigger < 5: full-loss rate", lambda ts: pct(sum(1 for t in ts if t.get("rsi_excess") is not None and t["rsi_excess"] < 5 and t["full"]), sum(1 for t in ts if t.get("rsi_excess") is not None and t["rsi_excess"] < 5)))

    # ---------------------------------------------------------------- Part 12
    p("\n### Part 12. Failure modes of the losing trades (path shape first, then overlays)\n")
    modes = Counter(); money = defaultdict(float); members = defaultdict(list)
    for t in losers:
        if t["mae30"] is not None and t["mae30"] <= -0.25 and (t["mfe30"] is None or t["mfe30"] < 0.10):
            m = "1 immediate adverse move (−0.25R within 30 s, never +0.10R before)"
        elif t["grp"].startswith("A"):
            m = "2 slow / no follow-through (never +0.25R, not immediate)"
        elif t["mfe"] >= 0.25 - 1e-9:
            m = "3 brief favourable move then reversal (reached +0.25R, then lost)"
        else:
            m = "9 other"
        modes[m] += 1; money[m] += t["net"]; members[m].append(t)
    p("| failure mode (mutually exclusive, path shape) | losing trades | share of losers | net $ | full losses | median MAE 30 s | median MFE | median entry spread |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for m in sorted(modes):
        ts = members[m]
        p(f"| {m} | {len(ts)} | {pct(len(ts), len(losers))} | {money[m]:+.2f} | {sum(1 for t in ts if t['full'])} | {med([t['mae30'] for t in ts])} | {med([t['mfe'] for t in ts])} | {med([t['sp_entry'] for t in ts], 0)} |")
    p("\nOverlays (a losing trade can carry several; share of losers and of all trades with that trait):\n")
    p("| overlay | losers with it | share of losers | all trades with it | loss rate among them | full-loss rate among them |")
    p("| --- | ---: | ---: | ---: | ---: | ---: |")
    overlays = (("4 spread/friction: entry spread ≥ 45 pts", lambda t: t["sp_entry"] is not None and t["sp_entry"] >= 45),
                ("5 session 07-12", lambda t: t["sess"] == "07-12"), ("6 direction LONG", lambda t: t["side"] == "LONG"),
                ("7 ATR regime LOW", lambda t: t["regime"] == "LOW"), ("7 ATR regime HIGH", lambda t: t["regime"] == "HIGH"),
                ("8 deep Bollinger penetration", lambda t: t["pen"] == "deep"), ("9 RSI ≥ 5 points beyond trigger", lambda t: t.get("rsi_excess") is not None and t["rsi_excess"] >= 5),
                ("9 filled ≥ 0.10R worse than the signal-bar close", lambda t: t.get("drift_r") is not None and t["drift_r"] >= 0.10))
    for label, f in overlays:
        allw = [t for t in trades if f(t)]; lw = [t for t in losers if f(t)]
        p(f"| {label} | {len(lw)} | {pct(len(lw), len(losers))} | {len(allw)} | {pct(len(lw), len(allw))} | {pct(sum(1 for t in allw if t['full']), len(allw))} |")
    p(f"\nBase rates: loss rate {pct(len(losers), n)}, full-loss rate {pct(len(fulls), n)}.")

    # ---------------------------------------------------------------- Part 13 numbers
    p("\n### Part 13. Direct answers (numbers)\n")
    bad30 = lambda t: (t["mae30"] is not None and t["mae30"] <= -0.25) or (t["t-0.10"] is not None and t["t-0.10"] <= 30 and (t["mfe30"] is None or t["mfe30"] < 0.10))
    p(f"* 'Looks bad within 30 s' = reached −0.25R within 30 s, or reached −0.10R within 30 s without ever reaching +0.10R in that time.")
    p(f"* Losers (net ≤ 0) that look bad within 30 s: {sum(1 for t in losers if bad30(t))} of {len(losers)} ({pct(sum(1 for t in losers if bad30(t)), len(losers))}); "
      f"full losses: {sum(1 for t in fulls if bad30(t))} of {len(fulls)} ({pct(sum(1 for t in fulls if bad30(t)), len(fulls))}).")
    p(f"* Winners that look bad within 30 s: {sum(1 for t in winners if bad30(t))} of {len(winners)} ({pct(sum(1 for t in winners if bad30(t)), len(winners))}); "
      f"large winners (≥ +0.75R): {sum(1 for t in trades if t['R'] >= 0.75 and bad30(t))} of {sum(1 for t in trades if t['R'] >= 0.75)}.")
    for w in (10, 30, 60):
        bad = [t for t in trades if t["t-0.25"] is not None and t["t-0.25"] <= w]
        good = [t for t in trades if t["t+0.25"] is not None and t["t+0.25"] <= w]
        p(f"* At {w} s: −0.25R reached by {len(bad)} trades → full-loss rate {pct(sum(1 for t in bad if t['full']), len(bad))}, win rate {pct(sum(1 for t in bad if t['win']), len(bad))}; "
          f"+0.25R reached by {len(good)} → win rate {pct(sum(1 for t in good if t['win']), len(good))}, full-loss rate {pct(sum(1 for t in good if t['full']), len(good))}; "
          f"neither yet: {n - len(set(map(id, bad)) | set(map(id, good)))} trades.")
    print("\n".join(out))


if __name__ == "__main__":
    main()
