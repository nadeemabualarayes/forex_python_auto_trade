"""Small-profit / small-loss research (phase 1, read-only): tick-accurate excursion and envelope analysis of every
post-sizing-fix XAUUSD scalp-test trade. Research branch only; nothing here touches a bot, a terminal or config.

    python docs/research/small_profit_small_loss_analysis.py > out.md

Data (files only, no MT5 attach):
  * live tick paths      C:\\Develompent\\forex_scalp_test\\logs\\paths\\XAUUSD_<pid>.jsonl      (recorder, since 2026-09-13)
  * replayed tick paths  logs/replay_paths_2026-09-07_11/XAUUSD_<pid>.jsonl                 (09-13 audit, verified 155/155)
  * trade net incl. commission/swap   C:\\Develompent\\forex_scalp_test\\logs\\history.db
  * order price at entry (slippage)   C:\\Develompent\\forex_scalp_test\\logs\\trades.csv
  * ATR regime / Bollinger penetration for trades to 2026-09-15 07:42: docs/research/forward_validation_2026-09-15.txt

Pre-registered, fixed before running: the four $ thresholds, the five envelopes, the two-half robustness split and
the decision rule. No other thresholds are searched.
"""
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCALP = r"C:\Develompent\forex_scalp_test"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCALP)                              # path_recorder.load_path, history, analytics (same code as HEAD)
os.chdir(SCALP)
import config                                          # noqa: E402
import path_recorder as pr                             # noqa: E402
from history import TradeStore                         # noqa: E402
from analytics import pair_trades                      # noqa: E402

FIX_MS = int(datetime(2026, 9, 7, 11, 26, 39, tzinfo=timezone.utc).timestamp() * 1000)   # 14:26:39 server (UTC+3)
SPLIT_MS = int(datetime(2026, 9, 13, tzinfo=timezone.utc).timestamp() * 1000)            # half A: 09-07..09-11, half B: 09-14..
THRESHOLDS = (0.5, 1.0, 1.5, 2.0)
ENVELOPES = ((0.5, 1.0), (1.0, 1.0), (1.0, 2.0), (1.5, 2.0), (2.0, 2.0))                  # (+profit $, -loss $)
ATR_LOW, ATR_HIGH = 1.647, 2.343                                                          # terciles from the 09-15 report
SLIP = (0.02, 0.05)                                                                        # exit-slippage allowances, $/trade
MAX_SPREAD_PTS = 300                                                                       # wider quotes = daily-break junk, not used
dropped_ticks = {}


def srv(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=None)


def session(h):
    return "00-07" if h < 7 else "07-12" if h < 12 else "12-17" if h < 17 else "17-24"


# ---------------------------------------------------------------- load
def load_trades():
    files = {}
    for p in glob.glob(os.path.join(ROOT, "logs", "replay_paths_2026-09-07_11", "XAUUSD_*.jsonl")):
        files[int(re.search(r"_(\d+)\.jsonl$", p).group(1))] = ("replay", p)
    for p in glob.glob(os.path.join(SCALP, "logs", "paths", "XAUUSD_*.jsonl")):
        files[int(re.search(r"_(\d+)\.jsonl$", p).group(1))] = ("live", p)                 # live wins on overlap
    store = TradeStore(os.path.join(config.LOG_DIR, config.HISTORY_DB))
    nets = {t.position_id: t for t in pair_trades(store.deals())}
    order_px = {}
    with open(os.path.join(SCALP, "logs", "trades.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["event"] == "ENTRY" and r["ticket"]:
                order_px[int(r["ticket"])] = float(r["price"])
    ctx = {}
    rp = os.path.join(ROOT, "docs", "research", "forward_validation_2026-09-15.txt")
    if os.path.exists(rp):
        pat = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d)\s+(LONG|SHORT)\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[+-][\d.]+\s+"
                         r"[+-][\d.]+\s+\S+\s+(?:terminal|field \(pre-fix\))\s+([\d.]+)\s+(LOW|NORMAL|HIGH)\s+([\d.]+)\s+(touch|small|medium|deep)")
        for line in open(rp, encoding="utf-8"):
            m = pat.match(line)
            if m:
                ctx[(m.group(1), m.group(2), float(m.group(3)))] = dict(atr=float(m.group(4)), regime=m.group(5),
                                                                        pen=float(m.group(6)), pen_bucket=m.group(7))
    trades, excluded = [], Counter()
    for pid, (src, p) in sorted(files.items()):
        d = pr.load_path(p)
        o, c = d["open"], d["close"]
        if c is None:
            excluded["still open"] += 1
            continue
        if o["fill_msc"] < FIX_MS or o["volume"] >= 0.1:
            excluded["pre-fix"] += 1
            continue
        if c["reason"] == "manual":
            excluded["closed by hand"] += 1
            continue
        raw_ticks = [t for t in d["ticks"] if t.get("upnl") is not None]
        # Quotes with a spread above MAX_SPREAD_PTS (10x the normal 30) are the broker's daily-break quotes (bid/ask
        # thousands of points apart); they are not tradeable prices and are left out of the marking. Nothing is
        # interpolated in their place: the path simply has no usable quote at those milliseconds.
        ticks = [t for t in raw_ticks if t.get("spread_pts") is None or t["spread_pts"] <= MAX_SPREAD_PTS]
        dropped_ticks[pid] = len(raw_ticks) - len(ticks)
        if not ticks:
            excluded["no ticks"] += 1
            continue
        h = nets.get(pid)
        net = round(h.net, 2) if h else round(sum(x["profit"] for x in c["deals"]), 2)
        fill = srv(o["fill_msc"])
        key = (fill.strftime("%Y-%m-%d %H:%M"), o["side"], round(o["fill_price"], 2))
        cx = ctx.get(key)
        atr = cx["atr"] if cx else round(o["stop_dist"] / config.SL_ATR_MULTIPLIER, 2)
        regime = cx["regime"] if cx else ("LOW" if atr < ATR_LOW else "HIGH" if atr >= ATR_HIGH else "NORMAL")
        q = o["quote_before_fill"]
        spread_usd = round((q["ask"] - q["bid"]) * o["usd_per_unit_lot"] * o["volume"], 3) if q else None
        risk = round(o["stop_dist"] * o["usd_per_unit_lot"] * o["volume"], 2)
        op = order_px.get(pid)
        slip = None if op is None else round(((o["fill_price"] - op) if o["side"] == "LONG" else (op - o["fill_price"])) * o["usd_per_unit_lot"] * o["volume"], 3)
        trades.append(dict(pid=pid, src=src, fill=fill, fill_ms=o["fill_msc"], exit_ms=c["exit_msc"], side=o["side"],
                           lot=o["volume"], entry=o["fill_price"], risk=risk, atr=atr, regime=regime,
                           pen=cx["pen_bucket"] if cx else "n/a", sess=session(fill.hour), label=c["label"],
                           net=net, upnl=[t["upnl"] for t in ticks], msc=[t["msc"] for t in ticks],
                           complete=c["complete"], spread_usd=spread_usd, slip_usd=slip, exit_price=c["exit_vwap"]))
    trades.sort(key=lambda t: t["fill_ms"])
    return trades, excluded


# ---------------------------------------------------------------- pure analysis
def first_at(upnl, level):
    """Index of the first tick at or beyond `level` (>= for positive levels, <= for negative); None if never."""
    for i, v in enumerate(upnl):
        if (level > 0 and v >= level - 1e-9) or (level < 0 and v <= level + 1e-9):
            return i
    return None


def envelope(t, profit, loss):
    """(pnl, outcome) under exit-at-first-touch of +profit / -loss on the marked tick path; unresolved trades keep
    their real exit. Exit price = the marked quote of the touching tick (gaps count against the trade both ways)."""
    ip, il = first_at(t["upnl"], profit), first_at(t["upnl"], -loss)
    if ip is None and il is None:
        return t["net"], "unresolved"
    if il is None or (ip is not None and ip <= il):
        return round(t["upnl"][ip], 2), "target"
    return round(t["upnl"][il], 2), "stop"


def stats(pnls):
    n = len(pnls)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gp, gl = sum(wins), -sum(losses)
    peak = dd = cum = 0.0
    streak = best = 0
    for x in pnls:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    return dict(n=n, wins=len(wins), losses=len(losses), win_rate=100 * len(wins) / n if n else 0, gross_profit=gp,
                gross_loss=gl, net=gp - gl, expectancy=(gp - gl) / n if n else 0, pf=(gp / gl) if gl else float("inf"),
                max_dd=dd, streak=best)


def fmt_stats(s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"{s['n']} | {s['wins']} | {s['losses']} | {s['win_rate']:.1f}% | {s['gross_profit']:+.2f} | {-s['gross_loss']:+.2f} | "
            f"**{s['net']:+.2f}** | {s['expectancy']:+.3f} | {pf} | {s['max_dd']:.2f} | {s['streak']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")      # the tables use ≤ / − / ≥; the Windows console default is cp1252
    trades, excluded = load_trades()
    n = len(trades)
    a = [t for t in trades if t["fill_ms"] < SPLIT_MS]
    b = [t for t in trades if t["fill_ms"] >= SPLIT_MS]
    out = []
    p = out.append
    p(f"Trades analysed: **{n}** strategy trades with a tick path, fills {trades[0]['fill']:%Y-%m-%d %H:%M} -> "
      f"{trades[-1]['fill']:%Y-%m-%d %H:%M} server; excluded: {dict(excluded)}. "
      f"Half A (replayed ticks, 09-07..09-11): {len(a)}; half B (live recorder, 09-14..): {len(b)}. "
      f"Incomplete paths kept: {sum(1 for t in trades if not t['complete'])}. "
      f"Ticks: {sum(len(t['upnl']) for t in trades):,}. Lots: {dict(Counter(t['lot'] for t in trades))}. "
      f"Penetration known for {sum(1 for t in trades if t['pen'] != 'n/a')} trades (from the 09-15 report). "
      f"Ticks with a spread above {MAX_SPREAD_PTS} points (daily-break quotes) left out of the marking: "
      f"{sum(dropped_ticks.values())} ticks in {sum(1 for v in dropped_ticks.values() if v)} trade(s): "
      f"{ {k: v for k, v in dropped_ticks.items() if v} }.")
    risk = [t["risk"] for t in trades]
    spreads = [t["spread_usd"] for t in trades if t["spread_usd"] is not None]
    slips = [t["slip_usd"] for t in trades if t["slip_usd"] is not None]
    spreads_s, slips_s = sorted(spreads), sorted(slips)
    p(f"\nRisk at the initial stop: mean ${sum(risk)/n:.2f}, min ${min(risk):.2f}, max ${max(risk):.2f}. "
      f"Spread at the fill (bid/ask x lot): mean ${sum(spreads)/len(spreads):.3f}, median ${spreads_s[len(spreads_s)//2]:.3f}, "
      f"max ${max(spreads):.3f}. Entry slippage vs the order price (+ = worse): mean ${sum(slips)/len(slips):+.3f}, "
      f"median ${slips_s[len(slips_s)//2]:+.3f}, worst ${max(slips):+.2f}, best ${min(slips):+.2f} ({len(slips)} matched).")

    # baseline
    base = stats([t["net"] for t in trades])
    hdr = "| scenario | trades | wins | losses | win% | gross profit | gross loss | net | expectancy | PF | max DD | longest losing streak |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    p("\n## Baseline: what actually happened (same trades)\n")
    p(hdr); p(sep); p(f"| actual exits (SL 2 ATR / TP 2 ATR / BE+trail) | {fmt_stats(base)} |")
    p(f"\nActual net by exit label: " + ", ".join(f"{k} {v}x {sum(t['net'] for t in trades if t['label'] == k):+.2f}"
                                                    for k, v in Counter(t["label"] for t in trades).most_common()) + ".")

    # thresholds
    p("\n## 1–3. Trades that reached +$0.50 / +$1.00 / +$1.50 / +$2.00 before closing\n")
    p("| threshold | reached | of all | later won | later lost | mean final P&L of those | median | final ≤ −$2.50 (full stop) | final ≤ −$3.50 | mean MAE after the touch | worst MAE after touch | median time to touch | exits |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    reached_sets = {}
    for th in THRESHOLDS:
        rs = []
        for t in trades:
            i = first_at(t["upnl"], th)
            if i is not None:
                rs.append((t, i, min(t["upnl"][i:]), (t["msc"][i] - t["fill_ms"]) / 1000))
        reached_sets[th] = rs
        if not rs:
            p(f"| +${th:.2f} | 0 | 0% | | | | | | | | | | |")
            continue
        finals = sorted(t["net"] for t, _, _, _ in rs)
        won = sum(1 for t, *_ in rs if t["net"] > 0)
        maes = [m for _, _, m, _ in rs]
        times = sorted(x for *_, x in rs)
        labels = ", ".join(f"{k} {v}" for k, v in Counter(t["label"] for t, *_ in rs).most_common())
        p(f"| +${th:.2f} | {len(rs)} | {100*len(rs)/n:.0f}% | {won} | {len(rs)-won} | {sum(finals)/len(finals):+.2f} | "
          f"{finals[len(finals)//2]:+.2f} | {sum(1 for x in finals if x <= -2.5)} | {sum(1 for x in finals if x <= -3.5)} | "
          f"{sum(maes)/len(maes):+.2f} | {min(maes):+.2f} | {times[len(times)//2]:.0f} s | {labels} |")
    p("\nMAE after the touch = the lowest marked P&L between the first touch of the threshold and the exit "
      "(a mean of −2.00 means that, on average, these trades later fell to −$2.00 before closing).")
    never = [t for t in trades if first_at(t["upnl"], 0.5) is None]
    p(f"\nNever reached +$0.50: {len(never)} trades ({100*len(never)/n:.0f}%), net {sum(t['net'] for t in never):+.2f}, "
      f"exits {dict(Counter(t['label'] for t in never))}.")

    p("\n### 3. Trades that reached +$1.00 and then closed at a full loss (≤ −$3.50)\n")
    bad = [(t, i, m) for t, i, m, _ in reached_sets[1.0] if t["net"] <= -3.5]
    p(f"{len(bad)} of the {len(reached_sets[1.0])} trades that touched +$1.00 (of {n}) ended at −$3.50 or worse; "
      f"their net {sum(t['net'] for t, _, _ in bad):+.2f}. "
      f"With ≤ −$2.50 as the cut: {sum(1 for t, *_ in reached_sets[1.0] if t['net'] <= -2.5)} trades.")
    p("\n| fill (server) | side | lot | risk $ | MFE $ | touched +$1 after | final $ | exit | how |")
    p("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for t, i, m in bad:
        mfe = max(t["upnl"])
        p(f"| {t['fill']:%m-%d %H:%M} | {t['side']} | {t['lot']} | {t['risk']:.2f} | {mfe:+.2f} | {(t['msc'][i]-t['fill_ms'])/1000:.0f} s | "
          f"{t['net']:+.2f} | {t['label']} | peaked at {100*mfe/t['risk']:.0f}% of 1R, stop never moved (breakeven needs ~+50% of 1R) |")

    # envelopes
    p("\n## 4. Pre-registered envelopes (exit at the first tick at or beyond +profit / −loss, entries unchanged)\n")
    p(hdr.replace("| scenario |", "| envelope |") + " unresolved | mean overshoot at target | mean overshoot at stop |")
    p(sep + " ---: | ---: | ---: |")
    p(f"| baseline (actual) | {fmt_stats(base)} | | | |")
    env_results = {}
    for profit, loss in ENVELOPES:
        res = [envelope(t, profit, loss) for t in trades]
        env_results[(profit, loss)] = res
        s = stats([x for x, _ in res])
        unres = sum(1 for _, o in res if o == "unresolved")
        ot = [x - profit for x, o in res if o == "target"]
        os_ = [x + loss for x, o in res if o == "stop"]
        p(f"| +${profit:.2f} / −${loss:.2f} | {fmt_stats(s)} | {unres} | {sum(ot)/len(ot) if ot else 0:+.3f} | {sum(os_)/len(os_) if os_ else 0:+.3f} |")
    p("\n### Spread and slippage")
    p("\n| envelope | net | net − $0.02/trade exit slippage | net − $0.05/trade | spread at fill as % of the target | trades resolved by target / stop / unresolved |")
    p("| --- | ---: | ---: | ---: | ---: | --- |")
    mean_spread = sum(spreads) / len(spreads)
    for (profit, loss), res in env_results.items():
        net = sum(x for x, _ in res)
        c = Counter(o for _, o in res)
        p(f"| +${profit:.2f} / −${loss:.2f} | {net:+.2f} | {net - SLIP[0]*n:+.2f} | {net - SLIP[1]*n:+.2f} | "
          f"{100*mean_spread/profit:.0f}% | {c['target']} / {c['stop']} / {c['unresolved']} |")
    p(f"\nThe marked path already pays the spread (a long is marked at the bid, a short at the ask), so every envelope "
      f"result includes the ${mean_spread:.2f} average spread at entry. Entry slippage is real (the recorded fill). The "
      f"two extra columns charge an assumed market-order exit slippage of $0.02 and $0.05 per trade (observed entry "
      f"slippage: median ${slips_s[len(slips_s)//2]:+.3f}, mean ${sum(slips)/len(slips):+.3f}). Overshoot = how far past "
      f"the level the touching tick already was (positive at the target helps, negative at the stop hurts); a real "
      f"take-profit order would fill at the level or better, a real stop at the level, so both are conservative.")

    # robustness split + decision
    p("\n### Robustness: the two halves (pre-registered rule: an envelope is *supported* only if its net beats the "
      "baseline AND its PF > 1.0 in BOTH halves)\n")
    p("| envelope | half A net (PF) | half B net (PF) | overall net (PF) | verdict |")
    p("| --- | ---: | ---: | ---: | --- |")
    ba, bb = stats([t["net"] for t in a]), stats([t["net"] for t in b])
    p(f"| baseline (actual) | {ba['net']:+.2f} ({ba['pf']:.2f}) | {bb['net']:+.2f} ({bb['pf']:.2f}) | {base['net']:+.2f} ({base['pf']:.2f}) | |")
    for (profit, loss), res in env_results.items():
        sa = stats([x for (x, _), t in zip(res, trades) if t["fill_ms"] < SPLIT_MS])
        sb = stats([x for (x, _), t in zip(res, trades) if t["fill_ms"] >= SPLIT_MS])
        so = stats([x for x, _ in res])
        ok = sa["net"] > ba["net"] and sa["pf"] > 1 and sb["net"] > bb["net"] and sb["pf"] > 1
        partial = so["net"] > base["net"]
        p(f"| +${profit:.2f} / −${loss:.2f} | {sa['net']:+.2f} ({sa['pf']:.2f}) | {sb['net']:+.2f} ({sb['pf']:.2f}) | "
          f"{so['net']:+.2f} ({so['pf']:.2f}) | {'SUPPORTED' if ok else 'better than baseline overall but not in both halves' if partial else 'NOT SUPPORTED'} |")

    # decomposition: what a $1 target does to the winners
    p("\n### Where the difference comes from (envelope minus actual, per trade)\n")
    p("| envelope | winners capped (actual > envelope) | forfeited $ | losers cut short | saved $ | actual winners turned into envelope losses | cost $ | unresolved (kept real exit) | net change |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for (profit, loss), res in env_results.items():
        capped = forf = cut = saved = flipped = cost = unres = 0
        for (x, o), t in zip(res, trades):
            if o == "unresolved":
                unres += 1
            elif o == "target":
                if t["net"] > x:
                    capped += 1; forf += t["net"] - x
                elif t["net"] <= 0:
                    saved += x - t["net"]; cut += 1
            else:  # stop
                if t["net"] > 0:
                    flipped += 1; cost += t["net"] - x
                elif t["net"] < x:
                    cut += 1; saved += x - t["net"]
                else:
                    cost += t["net"] - x
        p(f"| +${profit:.2f} / −${loss:.2f} | {capped} | {-forf:+.2f} | {cut} | {saved:+.2f} | {flipped} | {-cost:+.2f} | {unres} | "
          f"{sum(x for x, _ in res) - base['net']:+.2f} |")

    # breakdowns
    def breakdown(title, keyf, order):
        p(f"\n### By {title}\n")
        cols = ["baseline"] + [f"+{pr_}/−{ls}" for pr_, ls in ENVELOPES]
        p("| " + title + " | n | " + " | ".join(f"{c} net (PF, win%)" for c in cols) + " |")
        p("| --- | ---: | " + " | ".join("---:" for _ in cols) + " |")
        groups = defaultdict(list)
        for i, t in enumerate(trades):
            groups[keyf(t)].append(i)
        for g in order:
            idx = groups.get(g)
            if not idx:
                continue
            cells = []
            for c in cols:
                if c == "baseline":
                    s = stats([trades[i]["net"] for i in idx])
                else:
                    pr_, ls = [e for e in ENVELOPES if f"+{e[0]}/−{e[1]}" == c][0]
                    s = stats([env_results[(pr_, ls)][i][0] for i in idx])
                pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
                cells.append(f"{s['net']:+.2f} ({pf}, {s['win_rate']:.0f}%)")
            p(f"| {g} | {len(idx)} | " + " | ".join(cells) + " |")

    breakdown("session (server hour of the fill)", lambda t: t["sess"], ("00-07", "07-12", "12-17", "17-24"))
    breakdown("direction", lambda t: t["side"], ("LONG", "SHORT"))
    breakdown("ATR regime (M1 ATR at the signal; LOW < 1.647, HIGH ≥ 2.343)", lambda t: t["regime"], ("LOW", "NORMAL", "HIGH"))
    breakdown("Bollinger penetration (known for the first 200 trades only)", lambda t: t["pen"], ("touch", "small", "medium", "deep", "n/a"))

    # sizes of the thresholds in R terms
    p(f"\nFor scale: with the current 2 ATR stop the mean risk per trade is ${sum(risk)/n:.2f}, so +$1.00 is on average "
      f"{100/(sum(risk)/n):.0f}% of 1R and −$2.00 is {200/(sum(risk)/n):.0f}% of 1R; the live breakeven move happens at "
      f"1 ATR = 50% of 1R (about +${0.5*sum(risk)/n:.2f} on average).")
    print("\n".join(out))


if __name__ == "__main__":
    main()
