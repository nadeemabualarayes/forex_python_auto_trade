"""Profit-protection research (read-only): does protecting part of the open profit after a trade has moved in our
favour reduce the large givebacks without destroying the larger winners?  Research branch only; touches no bot,
terminal or config. Reuses the 299 verified tick paths and loader of small_profit_small_loss_analysis.py.

    python docs/research/profit_protection_analysis.py > out.md

Pre-registered before running: thresholds 0.25/0.33/0.50/0.75/1.00 R; models A (arm +0.50R; floor -0.25/0/+0.10 R),
B (arm +0.75R; floor 0/+0.25/+0.50 R), C (arm +1.00R; floor +0.25/+0.50/+0.75 R); halves A/B; the decision rule in
DECISION below. No other levels are searched.

No look-ahead: a model arms at the first tick whose marked R is at or above the arming level, in recorded tick
order; from the NEXT tick on, the trade exits at the first tick whose marked R is at or below the floor, at that
tick's quote. Anything else keeps the real exit (which already includes the live breakeven/trail).
"""
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from small_profit_small_loss_analysis import load_trades, stats, SPLIT_MS, SCALP, ROOT   # noqa: E402
import path_recorder as pr                                                                # noqa: E402

THRESHOLDS = (0.25, 0.33, 0.50, 0.75, 1.00)
MODELS = (("A1", 0.50, -0.25), ("A2", 0.50, 0.00), ("A3", 0.50, 0.10),
          ("B1", 0.75, 0.00), ("B2", 0.75, 0.25), ("B3", 0.75, 0.50),
          ("C1", 1.00, 0.25), ("C2", 1.00, 0.50), ("C3", 1.00, 0.75))
LARGE_WIN_R, LARGE_LOSS_R, SIG_LOSS_R = 0.75, -0.75, -0.50
DECISION = ("PROMISING only if: (1) >= 5 large losses (<= -0.75R) prevented AND >= $20 of giveback prevented; "
            "(2) fewer than half of the large winners (>= +0.75R) are cut AND $ forfeited < $ prevented; "
            "(3) expectancy better than the actual exits; (4) net AND expectancy better than the actual exits in BOTH halves; "
            "(5) the overall improvement stays positive after removing the single best session bucket and the single best "
            "direction bucket. REJECTED if (3) fails or both halves fail. INCONCLUSIVE otherwise.")


def first_at(r, level):
    for i, v in enumerate(r):
        if v >= level - 1e-9:
            return i
    return None


def protect(t, arm, floor):
    """(pnl $, outcome) for one trade under 'arm at +arm R, then exit at the first later tick at or below floor R'."""
    r = t["r"]
    i = first_at(r, arm)
    if i is None:
        return t["net"], "not armed"
    for j in range(i + 1, len(r)):
        if r[j] <= floor + 1e-9:
            return round(r[j] * t["risk"], 2), "protected"
    return t["net"], "armed, real exit"


def fmt(s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"{s['n']} | {s['wins']} | {s['losses']} | {s['win_rate']:.1f}% | {s['gross_profit']:+.2f} | {-s['gross_loss']:+.2f} | "
            f"**{s['net']:+.2f}** | {s['expectancy']:+.3f} | {pf} | {s['max_dd']:.2f} | {s['streak']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    trades, excluded = load_trades()
    for t in trades:
        t["r"] = [u / t["risk"] for u in t["upnl"]]
        t["R"] = t["net"] / t["risk"]
        src = os.path.join(SCALP, "logs", "paths") if t["src"] == "live" else os.path.join(ROOT, "logs", "replay_paths_2026-09-07_11")
        d = pr.load_path(os.path.join(src, f"XAUUSD_{t['pid']}.jsonl"))
        long = t["side"] == "LONG"
        moves = [e for e in d["events"] if e["type"] == "sl_move" and e.get("to") is not None]
        t["be_moved"] = any((e["to"] >= t["entry"] - 1e-9) if long else (e["to"] <= t["entry"] + 1e-9) for e in moves)
        t["sl_moves"] = len(moves)
    n = len(trades)
    out = []
    p = out.append
    base = stats([t["net"] for t in trades])
    p(f"Trades: **{n}** (the same 299 verified tick paths; excluded {dict(excluded)}); half A {sum(1 for t in trades if t['fill_ms'] < SPLIT_MS)}, "
      f"half B {sum(1 for t in trades if t['fill_ms'] >= SPLIT_MS)}. Actual exits: net {base['net']:+.2f}, PF {base['pf']:.2f}, "
      f"max DD {base['max_dd']:.2f}, expectancy {base['expectancy']:+.3f}/trade. Mean initial risk ${sum(t['risk'] for t in trades)/n:.2f}. "
      f"Large winners (actual >= +0.75R): {sum(1 for t in trades if t['R'] >= LARGE_WIN_R)}; large losses (<= -0.75R): "
      f"{sum(1 for t in trades if t['R'] <= LARGE_LOSS_R)}; significant losses (<= -0.50R): {sum(1 for t in trades if t['R'] <= SIG_LOSS_R)}.")

    # thresholds
    p("\n### Threshold statistics (first touch in tick order)\n")
    p("| threshold | touched | of all | later won | full loss (≤ −0.9R) | significant loss (≤ −0.5R) | mean final R | median final R | mean MFE (whole trade) | mean MAE after touch | worst MAE after touch | median time touch→exit | live BE fired on those |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    touched = {}
    for th in THRESHOLDS:
        rows = []
        for t in trades:
            i = first_at(t["r"], th)
            if i is not None:
                rows.append((t, i))
        touched[th] = rows
        if not rows:
            continue
        finals = sorted(t["R"] for t, _ in rows)
        maes = [min(t["r"][i:]) for t, i in rows]
        times = sorted((t["exit_ms"] - t["msc"][i]) / 1000 for t, i in rows)
        p(f"| +{th:.2f}R | {len(rows)} | {100*len(rows)/n:.0f}% | {sum(1 for t, _ in rows if t['net'] > 0)} | "
          f"{sum(1 for x in finals if x <= -0.9)} | {sum(1 for x in finals if x <= SIG_LOSS_R)} | {sum(finals)/len(finals):+.2f} | "
          f"{finals[len(finals)//2]:+.2f} | {sum(max(t['r']) for t, _ in rows)/len(rows):+.2f} | {sum(maes)/len(maes):+.2f} | "
          f"{min(maes):+.2f} | {times[len(times)//2]:.0f} s | {sum(1 for t, _ in rows if t['be_moved'])} |")
    never = [t for t in trades if first_at(t["r"], 0.25) is None]
    p(f"\nNever reached +0.25R: {len(never)} trades ({100*len(never)/n:.0f}%), net {sum(t['net'] for t in never):+.2f}, "
      f"all {dict(Counter(t['label'] for t in never))}.")

    # givebacks
    p("\n### Givebacks: touched a threshold, then closed at a significant loss (≤ −0.50R)\n")
    p("| touched | then full loss (≤ −0.9R) | then significant loss (≤ −0.5R) | their net $ | of which also touched +0.50R | of which the live breakeven had fired |")
    p("| --- | ---: | ---: | ---: | ---: | ---: |")
    for th in (0.25, 0.33, 0.50, 0.75):
        rows = [(t, i) for t, i in touched[th] if t["R"] <= SIG_LOSS_R]
        p(f"| +{th:.2f}R | {sum(1 for t, _ in rows if t['R'] <= -0.9)} | {len(rows)} | {sum(t['net'] for t, _ in rows):+.2f} | "
          f"{sum(1 for t, _ in rows if first_at(t['r'], 0.5) is not None)} | {sum(1 for t, _ in rows if t['be_moved'])} |")
    gb = [(t, i) for t, i in touched[0.50] if t["R"] <= SIG_LOSS_R]
    p("\nTrades that touched +0.50R and still closed at a significant loss:\n")
    p("| fill | side | risk $ | MFE R | +0.50R after | live SL moves | BE fired | final R | final $ | exit |")
    p("| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |")
    for t, i in gb:
        p(f"| {t['fill']:%m-%d %H:%M} | {t['side']} | {t['risk']:.2f} | {max(t['r']):+.2f} | {(t['msc'][i]-t['fill_ms'])/1000:.0f} s | "
          f"{t['sl_moves']} | {'yes' if t['be_moved'] else 'no'} | {t['R']:+.2f} | {t['net']:+.2f} | {t['label']} |")
    touched_half = [t for t, _ in touched[0.50]]
    p(f"\nLive breakeven check: of the {len(touched_half)} trades that touched +0.50R tick-exactly, the live stop was moved to "
      f"breakeven or better on {sum(1 for t in touched_half if t['be_moved'])}; of the {len(touched[0.75])} that touched +0.75R, "
      f"on {sum(1 for t, _ in touched[0.75] if t['be_moved'])}. (The live rule needs 1 *live* ATR at a 2-second poll, not 0.5R tick-exact.)")

    # models
    hdr = "| model | arm | floor | armed | protected (affected) | trades | wins | losses | win% | gross profit | gross loss | net | expectancy | PF | max DD | longest losing streak | large winners cut | $ forfeited on them | large losses prevented | $ giveback prevented | $ new losses caused (winners cut below their real exit) |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    p("\n### Predefined protection models (on top of the real exits)\n")
    p(hdr); p(sep)
    p(f"| actual | | | | | {fmt(base)} | | | | | |")
    results = {}
    for name, arm, floor in MODELS:
        res = [protect(t, arm, floor) for t in trades]
        results[name] = (arm, floor, res)
        s = stats([x for x, _ in res])
        armed = sum(1 for _, o in res if o != "not armed")
        prot = [(x, t) for (x, o), t in zip(res, trades) if o == "protected"]
        lw_cut = [(x, t) for x, t in prot if t["R"] >= LARGE_WIN_R and x < t["net"]]
        ll_prev = [(x, t) for x, t in prot if t["R"] <= LARGE_LOSS_R and x > t["net"]]
        prevented = sum(x - t["net"] for x, t in prot if x > t["net"])
        caused = sum(x - t["net"] for x, t in prot if x < t["net"])
        p(f"| {name} | +{arm:.2f}R | {floor:+.2f}R | {armed} | {len(prot)} | {fmt(s)} | {len(lw_cut)} | "
          f"{sum(x - t['net'] for x, t in lw_cut):+.2f} | {len(ll_prev)} | {prevented:+.2f} | {caused:+.2f} |")
    p("\nA floor at or below the level where the live breakeven/trail already sits changes little: the real exit "
      "arrives first. 'Protected' counts only trades whose exit the model actually changed.")

    # halves + decision
    p("\n### Robustness: halves and the decision rule\n")
    p(f"Rule: {DECISION}\n")
    p("| model | half A net (exp, PF) | half B net (exp, PF) | overall net (exp, PF) | (1) givebacks | (2) winners kept | (3) expectancy | (4) both halves | (5) not one bucket | verdict |")
    p("| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |")
    halves = [[t["fill_ms"] < SPLIT_MS for t in trades], [t["fill_ms"] >= SPLIT_MS for t in trades]]
    bh = [stats([t["net"] for t, m in zip(trades, h) if m]) for h in halves]
    p(f"| actual | {bh[0]['net']:+.2f} ({bh[0]['expectancy']:+.3f}, {bh[0]['pf']:.2f}) | {bh[1]['net']:+.2f} ({bh[1]['expectancy']:+.3f}, {bh[1]['pf']:.2f}) | "
      f"{base['net']:+.2f} ({base['expectancy']:+.3f}, {base['pf']:.2f}) | | | | | | |")
    verdicts = {}
    for name, (arm, floor, res) in results.items():
        pn = [x for x, _ in res]
        so = stats(pn)
        sh = [stats([x for x, m in zip(pn, h) if m]) for h in halves]
        prot = [(x, t) for (x, o), t in zip(res, trades) if o == "protected"]
        ll_prev = sum(1 for x, t in prot if t["R"] <= LARGE_LOSS_R and x > t["net"])
        prevented = sum(x - t["net"] for x, t in prot if x > t["net"])
        forfeited = -sum(x - t["net"] for x, t in prot if x < t["net"])
        n_lw = sum(1 for t in trades if t["R"] >= LARGE_WIN_R)
        lw_cut = sum(1 for x, t in prot if t["R"] >= LARGE_WIN_R and x < t["net"])
        c1 = ll_prev >= 5 and prevented >= 20
        c2 = lw_cut < n_lw / 2 and forfeited < prevented
        c3 = so["expectancy"] > base["expectancy"]
        c4 = all(sh[k]["net"] > bh[k]["net"] and sh[k]["expectancy"] > bh[k]["expectancy"] for k in (0, 1))
        improvement = so["net"] - base["net"]
        def bucket_gain(keyf):
            g = defaultdict(float)
            for x, t in zip(pn, trades):
                g[keyf(t)] += x - t["net"]
            return max(g.values()) if g else 0.0
        best_sess, best_side = bucket_gain(lambda t: t["sess"]), bucket_gain(lambda t: t["side"])
        c5 = (improvement - best_sess) > 0 and (improvement - best_side) > 0
        if not c3 or not any(sh[k]["net"] > bh[k]["net"] for k in (0, 1)):
            v = "REJECTED"
        elif c1 and c2 and c3 and c4 and c5:
            v = "PROMISING"
        else:
            v = "INCONCLUSIVE"
        verdicts[name] = v
        yn = lambda b: "yes" if b else "no"
        p(f"| {name} | {sh[0]['net']:+.2f} ({sh[0]['expectancy']:+.3f}, {sh[0]['pf']:.2f}) | {sh[1]['net']:+.2f} ({sh[1]['expectancy']:+.3f}, {sh[1]['pf']:.2f}) | "
          f"{so['net']:+.2f} ({so['expectancy']:+.3f}, {so['pf']:.2f}) | {yn(c1)} ({ll_prev} prevented, {prevented:+.2f}) | "
          f"{yn(c2)} ({lw_cut}/{n_lw} cut, {-forfeited:+.2f}) | {yn(c3)} | {yn(c4)} | {yn(c5)} (best session {best_sess:+.2f}, best side {best_side:+.2f}) | **{v}** |")

    # segments
    def breakdown(title, keyf, order):
        p(f"\n### By {title}\n")
        p("| " + title + " | n | actual net (exp, PF) | " + " | ".join(f"{m} net (exp, PF)" for m, _, _ in MODELS) + " |")
        p("| --- | ---: | ---: | " + " | ".join("---:" for _ in MODELS) + " |")
        groups = defaultdict(list)
        for i, t in enumerate(trades):
            groups[keyf(t)].append(i)
        for g in order:
            idx = groups.get(g)
            if not idx:
                continue
            cells = []
            s = stats([trades[i]["net"] for i in idx])
            cells.append(f"{s['net']:+.2f} ({s['expectancy']:+.2f}, {s['pf']:.2f})")
            for m, _, _ in MODELS:
                s = stats([results[m][2][i][0] for i in idx])
                cells.append(f"{s['net']:+.2f} ({s['expectancy']:+.2f}, {s['pf']:.2f})")
            p(f"| {g} | {len(idx)} | " + " | ".join(cells) + " |")

    breakdown("session", lambda t: t["sess"], ("00-07", "07-12", "12-17", "17-24"))
    breakdown("direction", lambda t: t["side"], ("LONG", "SHORT"))
    breakdown("ATR regime", lambda t: t["regime"], ("LOW", "NORMAL", "HIGH"))
    p("\nVerdicts: " + ", ".join(f"{k} {v}" for k, v in verdicts.items()) + ".")
    print("\n".join(out))


if __name__ == "__main__":
    main()
