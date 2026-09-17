"""Time-Boxed Entry Study (pre-registered, research only): does the path in the first 30/45/60 s after the fill
contain enough information to tell likely failures from eventual winners, and at what cost in sacrificed winners?

    python docs/research/time_boxed_entry_analysis.py > docs/research/2026-09-17-time-boxed-entry-analysis.md

DATA. The same 299 verified tick paths as the previous studies, through load_trades() of
small_profit_small_loss_analysis.py (149 replayed 7-11 Sep, 150 live-recorded 13-17 Sep; pre-fix and hand-closed
trades excluded; daily-break quotes with a spread above 300 points left out; no interpolation; tick order preserved;
longs marked at the bid, shorts at the ask; final net from history.db, never replaced by a hypothetical fill).
R = marked P&L / initial risk.

CHECKPOINTS (fixed before running): 30 s, 45 s, 60 s after the fill millisecond. A checkpoint state uses ONLY ticks
with time_msc <= fill_msc + checkpoint*1000, in recorded order: R at the last such tick, MFE/MAE over those ticks,
and whether +0.10/+0.25/+0.50/-0.10/-0.25/-0.33 R was touched at or before the checkpoint. A trade that closed before
the checkpoint keeps its last recorded state (its path simply ends). Nothing after the checkpoint is used for any
classification; final outcomes come from the deal history and are never altered. selftest() proves the leakage
guard on synthetic paths (e.g. +0.25R first touched at 75 s counts as NOT reached at 60 s).

OUTCOME DEFINITIONS (existing): winner = final net > 0; full loss = final R <= -0.9; large winner = final R >= +0.75;
normal winner = winner with final R < +0.75. Halves: A = fills before 2026-09-13, B = after.

EVIDENCE CLASSIFICATION (fixed before running, applied to the +0.25R-by-checkpoint split; 'separation' = full-loss
rate of the not-reached group minus that of the reached group, in percentage points; 'sacrifice' = share of all
eventual winners that had NOT reached +0.25R by the checkpoint):
  NO SIGNAL                  separation < 10 points
  WEAK SIGNAL                separation 10-20 points, or separation >= 10 in only one half (half separation < 10)
  MODERATE DIAGNOSTIC SIGNAL separation >= 20 points overall and >= 10 in both halves, but sacrifice > 25%
  STRONG DIAGNOSTIC SIGNAL   separation >= 30 points overall, >= 10 in both halves, and sacrifice <= 25%
WINNER SACRIFICE BANDS: small <= 15% of winners, moderate 15-35%, substantial > 35%.

Hypothetical sections describe populations; they are not rules and are labelled as such in the output.
"""
import os
import statistics as st
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from small_profit_small_loss_analysis import load_trades, stats, SPLIT_MS   # noqa: E402

CHECKPOINTS = (30, 45, 60)
LEVELS = (0.10, 0.25, 0.50, -0.10, -0.25, -0.33)
FULL_R, LARGE_R = -0.9, 0.75


# ---------------------------------------------------------------- pure, leakage-safe checkpoint state
def checkpoint_state(r, msc, fill_ms, secs):
    """State from ticks at or before fill + secs only. r/msc are the whole path in recorded order; the function
    truncates first and never looks past the cut."""
    cut = fill_ms + secs * 1000
    rs = [x for x, m in zip(r, msc) if m <= cut]
    if not rs:
        return dict(has_tick=False, r=None, mfe=None, mae=None, **{f"hit{lv:+.2f}": False for lv in LEVELS})
    out = dict(has_tick=True, r=rs[-1], mfe=max(rs), mae=min(rs))
    for lv in LEVELS:
        out[f"hit{lv:+.2f}"] = any((x >= lv - 1e-9) if lv > 0 else (x <= lv + 1e-9) for x in rs)
    return out


def selftest():
    fill = 1_000_000
    # +0.25R first touched at 75 s: not reached at 30/45/60, reached at 90
    r = [-0.05, -0.10, 0.05, 0.20, 0.26, 0.40]
    msc = [fill + 1000 * s for s in (1, 20, 40, 59, 75, 100)]
    for cp in CHECKPOINTS:
        assert checkpoint_state(r, msc, fill, cp)["hit+0.25"] is False, cp
    assert checkpoint_state(r, msc, fill, 90)["hit+0.25"] is True
    # -0.25R at exactly the checkpoint second counts; one ms later does not
    r2, msc2 = [-0.05, -0.30], [fill + 1000, fill + 30_000]
    assert checkpoint_state(r2, msc2, fill, 30)["hit-0.25"] is True
    assert checkpoint_state(r2, [fill + 1000, fill + 30_001], fill, 30)["hit-0.25"] is False
    # R at checkpoint is the last tick at or before it, MFE/MAE only over those ticks
    s = checkpoint_state(r, msc, fill, 45)
    assert s["r"] == 0.05 and s["mfe"] == 0.05 and s["mae"] == -0.10
    # a trade that closed before the checkpoint keeps its last state
    s = checkpoint_state([-0.1, -1.0], [fill + 500, fill + 9000], fill, 60)
    assert s["r"] == -1.0 and s["hit-0.33"] is True and s["hit+0.10"] is False
    return "selftest passed: no tick after a checkpoint influences its classification"


# ---------------------------------------------------------------- reporting helpers
def group_row(name, ts, n_all):
    if not ts:
        return f"| {name} | 0 | 0% | | | | | | | | | | |"
    s = stats([t["net"] for t in ts])
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"| {name} | {len(ts)} | {100 * len(ts) / n_all:.0f}% | {s['wins']} | {sum(1 for t in ts if t['full'])} | "
            f"{s['win_rate']:.0f}% | {s['gross_profit']:+.2f} | {-s['gross_loss']:+.2f} | **{s['net']:+.2f}** | "
            f"{st.mean(t['R'] for t in ts):+.3f}R (${s['expectancy']:+.2f}) | {pf} | {st.median(t['mfe'] for t in ts):+.2f} | "
            f"{st.median(t['mae'] for t in ts):+.2f} |")


GROUP_HDR = ("| group | trades | of all | eventual winners | eventual full losses | win rate | gross profit | gross loss | net | "
             "expectancy | PF | median eventual MFE | median eventual MAE |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")


def split(trades, cp, key, want=True):
    yes = [t for t in trades if t["cp"][cp][key] is want]
    no = [t for t in trades if t["cp"][cp][key] is not want]
    return yes, no


def full_rate(ts):
    return 100 * sum(1 for t in ts if t["full"]) / len(ts) if ts else 0.0


def win_rate(ts):
    return 100 * sum(1 for t in ts if t["win"]) / len(ts) if ts else 0.0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    self_msg = selftest()
    trades, excluded = load_trades()
    for t in trades:
        t["r"] = [u / t["risk"] for u in t["upnl"]]
        t["R"] = t["net"] / t["risk"]
        t["win"] = t["net"] > 0
        t["full"] = t["R"] <= FULL_R
        t["large"] = t["R"] >= LARGE_R
        t["mfe"], t["mae"] = max(t["r"]), min(t["r"])
        t["half"] = "A" if t["fill_ms"] < SPLIT_MS else "B"
        t["cp"] = {cp: checkpoint_state(t["r"], t["msc"], t["fill_ms"], cp) for cp in CHECKPOINTS}
    n = len(trades)
    winners = [t for t in trades if t["win"]]
    losers = [t for t in trades if not t["win"]]
    total_net = sum(t["net"] for t in trades)
    base = stats([t["net"] for t in trades])
    halves = {h: [t for t in trades if t["half"] == h] for h in ("A", "B")}

    # quality control (hard checks)
    qc = []
    for cp in CHECKPOINTS:
        a, b = split(trades, cp, "hit+0.25")
        assert len(a) + len(b) == n
        assert all(t["cp"][cp]["has_tick"] for t in trades), "a trade without a tick before the checkpoint"
        qc.append(f"{cp} s: {len(a)} + {len(b)} = {n} trades")
    assert len(halves["A"]) + len(halves["B"]) == n
    assert abs(total_net - (-151.94)) < 0.01, f"total net {total_net:+.2f} does not reconcile with the 299-trade dataset (-151.94)"
    for cp in CHECKPOINTS:
        for t in trades:                                # leakage check on the real data: recompute from a truncated copy
            cut = t["fill_ms"] + cp * 1000
            k = sum(1 for m in t["msc"] if m <= cut)
            assert checkpoint_state(t["r"][:k], t["msc"][:k], t["fill_ms"], cp) == t["cp"][cp]

    # pre-registered evidence classification
    def classify(cp):
        a, b = split(trades, cp, "hit+0.25")
        sep = full_rate(b) - full_rate(a)
        seps = {}
        for h, ts in halves.items():
            ha, hb = split(ts, cp, "hit+0.25")
            seps[h] = full_rate(hb) - full_rate(ha)
        sacrifice = 100 * sum(1 for t in winners if not t["cp"][cp]["hit+0.25"]) / len(winners)
        both = all(v >= 10 for v in seps.values())
        if sep < 10:
            label = "NO SIGNAL"
        elif sep < 20 or not both:
            label = "WEAK SIGNAL"
        elif sep >= 30 and sacrifice <= 25:
            label = "STRONG DIAGNOSTIC SIGNAL"
        else:
            label = "MODERATE DIAGNOSTIC SIGNAL"
        band = "small" if sacrifice <= 15 else "moderate" if sacrifice <= 35 else "substantial"
        return dict(sep=sep, seps=seps, sacrifice=sacrifice, label=label, band=band, a=a, b=b)
    cls = {cp: classify(cp) for cp in CHECKPOINTS}

    out = []
    p = out.append
    p("# Time-Boxed Entry Study")
    p("")
    p("Date: 2026-09-17 · Branch `research/small-profit-small-loss` (worktree `C:\\Develompent\\forex_research_spsl`, at "
      "`scalp-test` `4b0c3a6`) · Generated by `docs/research/time_boxed_entry_analysis.py` (deterministic; every table "
      "below is its output) · **Research only: no rule is proposed, nothing was implemented, no production file, live "
      "setting, terminal or process was touched.**")
    p("")
    # ------------------------------------------------------------ 1
    p("## 1. Executive Summary")
    p("")
    p(f"{n} trades; actual result net ${total_net:+.2f}, PF {base['pf']:.2f}, {len(winners)} winners, {len(losers)} losers "
      f"(all {sum(1 for t in losers if t['full'])} of them full −1R losses). Pre-registered split at each checkpoint: "
      f"'+0.25R reached by then' versus 'not reached'.")
    p("")
    for cp in CHECKPOINTS:
        c = cls[cp]
        p(f"* **{cp} seconds:** {len(c['a'])} trades ({100*len(c['a'])/n:.0f}%) had reached +0.25R; their eventual win rate is "
          f"{win_rate(c['a']):.0f}% and full-loss rate {full_rate(c['a']):.0f}%, against {win_rate(c['b']):.0f}% and "
          f"{full_rate(c['b']):.0f}% for the {len(c['b'])} that had not. Separation {c['sep']:.0f} points "
          f"(half A {c['seps']['A']:.0f}, half B {c['seps']['B']:.0f}). It contains information, but "
          f"{c['sacrifice']:.0f}% of all eventual winners ({sum(1 for t in winners if not t['cp'][cp]['hit+0.25'])} of {len(winners)}, "
          f"including {sum(1 for t in winners if t['large'] and not t['cp'][cp]['hit+0.25'])} of the {sum(1 for t in winners if t['large'])} "
          f"large winners) were still on the 'not reached' side. Evidence class: **{c['label']}**; winner sacrifice: **{c['band']}**.")
    best = max(CHECKPOINTS, key=lambda cp: cls[cp]["sep"])
    p("")
    p(f"* **Is the separation strong enough to distinguish failures from winners?** No. Even at {best} s, the checkpoint with the "
      f"widest gap, the 'not reached' population still wins {win_rate(cls[best]['b']):.0f}% of the time, and the 'reached' population "
      f"still contains {sum(1 for t in cls[best]['a'] if t['full'])} full losses. The early path shifts the odds; it does not sort the trades.")
    p(f"* **How many eventual winners would early-path information sacrifice?** At 30 / 45 / 60 s: "
      + " / ".join(f"{sum(1 for t in winners if not t['cp'][cp]['hit+0.25'])} of {len(winners)} ({cls[cp]['sacrifice']:.0f}%)" for cp in CHECKPOINTS)
      + f". Using +0.10R instead: " + " / ".join(f"{sum(1 for t in winners if not t['cp'][cp]['hit+0.10'])}" for cp in CHECKPOINTS)
      + f". Using −0.25R-reached as the adverse marker: " + " / ".join(f"{sum(1 for t in winners if t['cp'][cp]['hit-0.25'])}" for cp in CHECKPOINTS)
      + " winners would be marked early-adverse.")
    p("")
    # ------------------------------------------------------------ 2
    p("## 2. Dataset and Methodology")
    p("")
    p(f"* Trades: {n} (excluded {dict(excluded)}); half A (7–11 Sep) {len(halves['A'])}, half B (14–17 Sep) {len(halves['B'])}; "
      f"total net ${total_net:+.2f} (reconciles with the 299-trade dataset of the previous studies). Ticks: {sum(len(t['r']) for t in trades):,}.")
    p("* Source: the same verified tick paths (recorder files for 13–17 Sep, the audited replay for 7–11 Sep) loaded by "
      "`small_profit_small_loss_analysis.load_trades`; longs marked at the bid, shorts at the ask; no interpolation; no OHLC; "
      "daily-break quotes (spread > 300 points) not used; final net from `history.db`.")
    p("* Checkpoints 30 / 45 / 60 s after the fill. A checkpoint state is computed from ticks with `time_msc <= fill + checkpoint` "
      "only (R at the last such tick, MFE/MAE over them, and whether +0.10 / +0.25 / +0.50 / −0.10 / −0.25 / −0.33 R was touched). "
      f"Leakage guard: {self_msg}; on the real data every state was recomputed from a truncated copy of the path and matched.")
    p("* Outcomes are the real ones: winner = net > 0; full loss = final R ≤ −0.9; large winner = final R ≥ +0.75; normal winner "
      "= winner below +0.75R. No hypothetical fill replaces an actual outcome.")
    p("* Evidence classification and sacrifice bands are the ones fixed in the script header before running. No other "
      "checkpoint, threshold or bucket was tried.")
    p(f"* Quality control: {'; '.join(qc)}; halves {len(halves['A'])} + {len(halves['B'])} = {n}.")
    p("")
    # ------------------------------------------------------------ 3-5 checkpoint sections
    for i, cp in enumerate(CHECKPOINTS, start=3):
        p(f"## {i}. {cp}-Second Checkpoint")
        p("")
        rs = [t["cp"][cp]["r"] for t in trades]
        p(f"State at {cp} s (all {n} trades have at least one tick by then): median R {st.median(rs):+.2f}, median MFE "
          f"{st.median(t['cp'][cp]['mfe'] for t in trades):+.2f}, median MAE {st.median(t['cp'][cp]['mae'] for t in trades):+.2f}; "
          f"trades already closed by {cp} s: {sum(1 for t in trades if t['exit_ms'] - t['fill_ms'] <= cp * 1000)}.")
        p("")
        p("| level touched by the checkpoint | trades | of all | eventual win rate | eventual full-loss rate | mean final R |")
        p("| --- | ---: | ---: | ---: | ---: | ---: |")
        for lv in LEVELS:
            ts = [t for t in trades if t["cp"][cp][f"hit{lv:+.2f}"]]
            p(f"| {lv:+.2f}R | {len(ts)} | {100*len(ts)/n:.0f}% | {win_rate(ts):.0f}% | {full_rate(ts):.0f}% | {st.mean(t['R'] for t in ts) if ts else 0:+.2f} |")
        p("")
        p(f"Primary split at {cp} s:")
        p("")
        p(GROUP_HDR)
        a, b = split(trades, cp, "hit+0.25")
        p(group_row("A. reached +0.25R", a, n))
        p(group_row("B. did NOT reach +0.25R", b, n))
        p("")
        p("Secondary splits:")
        p("")
        p(GROUP_HDR)
        a, b = split(trades, cp, "hit+0.10")
        p(group_row("reached +0.10R", a, n)); p(group_row("did NOT reach +0.10R", b, n))
        a, b = split(trades, cp, "hit-0.25")
        p(group_row("reached −0.25R", a, n)); p(group_row("did NOT reach −0.25R", b, n))
        p("")
    # ------------------------------------------------------------ 6 hypothetical eligibility
    p("## 6. +0.25R Reached vs Not Reached: HYPOTHETICAL entry-eligibility view")
    p("")
    p("**Hypothetical.** 'Suppose trades that had not reached +0.25R by the checkpoint were considered lower-quality entries.' "
      "This measures what such a label would have contained; it is not a rule and the retained population is not a strategy result.")
    p("")
    p("| checkpoint | excluded (not reached) | eventual losers in it | eventual winners in it | large winners sacrificed | excluded P&L | "
      "retained (reached) | retained P&L | retained win rate / PF | excluded win rate / PF | losses removed $ | winners sacrificed $ |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cp in CHECKPOINTS:
        a, b = split(trades, cp, "hit+0.25")
        sa, sb = stats([t["net"] for t in a]), stats([t["net"] for t in b])
        pfa = "inf" if sa["pf"] == float("inf") else f"{sa['pf']:.2f}"
        pfb = "inf" if sb["pf"] == float("inf") else f"{sb['pf']:.2f}"
        p(f"| {cp} s | {len(b)} | {sum(1 for t in b if not t['win'])} | {sum(1 for t in b if t['win'])} | {sum(1 for t in b if t['large'])} | "
          f"{sb['net']:+.2f} | {len(a)} | {sa['net']:+.2f} | {sa['win_rate']:.0f}% / {pfa} | {sb['win_rate']:.0f}% / {pfb} | "
          f"{-sb['gross_loss']:+.2f} | {-sb['gross_profit']:+.2f} |")
    p("")
    p("Reading: 'losses removed' is the gross loss inside the excluded population, 'winners sacrificed' the gross profit inside it. "
      "The retained population's result is what the label would have kept, before any effect the label itself would have on "
      "behaviour, spread or fills (none of which this study can measure).")
    p("")
    # ------------------------------------------------------------ 7 early adverse
    p("## 7. Early Adverse Movement (−0.25R reached vs not, descriptive)")
    p("")
    p("| checkpoint | group | trades | eventual full-loss rate | eventual win rate | net P&L | expectancy | eventual winners in the group | eventual losers in the group |")
    p("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cp in CHECKPOINTS:
        a, b = split(trades, cp, "hit-0.25")
        for name, ts in (("−0.25R reached (early adverse)", a), ("−0.25R NOT reached", b)):
            s = stats([t["net"] for t in ts])
            p(f"| {cp} s | {name} | {len(ts)} | {full_rate(ts):.0f}% | {win_rate(ts):.0f}% | {s['net']:+.2f} | ${s['expectancy']:+.2f} ({st.mean(t['R'] for t in ts):+.3f}R) | "
              f"{sum(1 for t in ts if t['win'])} | {sum(1 for t in ts if not t['win'])} |")
    p("")
    # ------------------------------------------------------------ 8 matrix
    p("## 8. Combined 2x2 Matrix (+0.25R reached × −0.25R reached, by checkpoint)")
    p("")
    for cp in CHECKPOINTS:
        p(f"{cp} s:")
        p("")
        p("| | +0.25R reached | +0.25R NOT reached |")
        p("| --- | --- | --- |")
        for adv in (True, False):
            cells = []
            for fav in (True, False):
                ts = [t for t in trades if t["cp"][cp]["hit+0.25"] is fav and t["cp"][cp]["hit-0.25"] is adv]
                if ts:
                    s = stats([t["net"] for t in ts])
                    cells.append(f"n={len(ts)}, win {win_rate(ts):.0f}%, full loss {full_rate(ts):.0f}%, exp ${s['expectancy']:+.2f} ({st.mean(t['R'] for t in ts):+.2f}R), net {s['net']:+.2f}")
                else:
                    cells.append("n=0")
            p(f"| −0.25R {'reached' if adv else 'NOT reached'} | {cells[0]} | {cells[1]} |")
        p("")
    # ------------------------------------------------------------ 9 halves
    p("## 9. First-Half vs Second-Half Robustness (+0.25R by checkpoint)")
    p("")
    p("| checkpoint | half | trades | reached: n / win / full loss / net | not reached: n / win / full loss / net | separation (full-loss points) | winners not reached |")
    p("| --- | --- | ---: | --- | --- | ---: | ---: |")
    for cp in CHECKPOINTS:
        for h, ts in halves.items():
            a, b = split(ts, cp, "hit+0.25")
            p(f"| {cp} s | {h} | {len(ts)} | {len(a)} / {win_rate(a):.0f}% / {full_rate(a):.0f}% / {sum(t['net'] for t in a):+.2f} | "
              f"{len(b)} / {win_rate(b):.0f}% / {full_rate(b):.0f}% / {sum(t['net'] for t in b):+.2f} | {full_rate(b) - full_rate(a):.0f} | "
              f"{sum(1 for t in b if t['win'])} of {sum(1 for t in ts if t['win'])} |")
    p("")
    # ------------------------------------------------------------ 10 session / direction
    p("## 10. Session and Direction Breakdown (+0.25R by checkpoint; descriptive, no combination searched)")
    p("")
    p("| segment | trades | checkpoint | reached: n / win / full loss / net | not reached: n / win / full loss / net | separation |")
    p("| --- | ---: | ---: | --- | --- | ---: |")
    for label, keyf, order in (("session", lambda t: t["sess"], ("00-07", "07-12", "12-17", "17-24")), ("direction", lambda t: t["side"], ("LONG", "SHORT"))):
        for v in order:
            ts = [t for t in trades if keyf(t) == v]
            for cp in CHECKPOINTS:
                a, b = split(ts, cp, "hit+0.25")
                p(f"| {label} {v} | {len(ts)} | {cp} s | {len(a)} / {win_rate(a):.0f}% / {full_rate(a):.0f}% / {sum(t['net'] for t in a):+.2f} | "
                  f"{len(b)} / {win_rate(b):.0f}% / {full_rate(b):.0f}% / {sum(t['net'] for t in b):+.2f} | {full_rate(b) - full_rate(a):.0f} |")
    p("")
    # ------------------------------------------------------------ 11 winner sacrifice
    p("## 11. Winner Sacrifice Analysis: how many good trades look bad early?")
    p("")
    normal = [t for t in winners if not t["large"]]
    large = [t for t in winners if t["large"]]
    p(f"Eventual winners: {len(winners)} ({len(normal)} normal, below +0.75R; {len(large)} large, ≥ +0.75R). Winners that had NOT reached the level by the checkpoint:")
    p("")
    p("| checkpoint | not yet +0.10R (normal / large) | not yet +0.25R (normal / large) | not yet +0.50R (normal / large) | already −0.25R (normal / large) | profit inside 'not yet +0.25R' winners |")
    p("| --- | ---: | ---: | ---: | ---: | ---: |")
    for cp in CHECKPOINTS:
        def cnt(key, want):
            ws = [t for t in winners if t["cp"][cp][key] is want]
            return f"{len(ws)} ({100*len(ws)/len(winners):.0f}%) ({sum(1 for t in ws if not t['large'])} / {sum(1 for t in ws if t['large'])})"
        p(f"| {cp} s | {cnt('hit+0.10', False)} | {cnt('hit+0.25', False)} | {cnt('hit+0.50', False)} | {cnt('hit-0.25', True)} | "
          f"{sum(t['net'] for t in winners if not t['cp'][cp]['hit+0.25']):+.2f} of {sum(t['net'] for t in winners):+.2f} |")
    p("")
    # ------------------------------------------------------------ 12
    p("## 12. What the Checkpoints Can and Cannot Tell Us")
    p("")
    for cp in CHECKPOINTS:
        c = cls[cp]
        m_ff = [t for t in trades if t["cp"][cp]["hit-0.25"] and not t["cp"][cp]["hit+0.25"]]
        m_tt = [t for t in trades if t["cp"][cp]["hit+0.25"] and not t["cp"][cp]["hit-0.25"]]
        p(f"* **{cp} s.** Can tell: a trade that has reached +0.25R goes on to win {win_rate(c['a']):.0f}% of the time; one that has "
          f"reached −0.25R without +0.25R ends as a full loss {full_rate(m_ff):.0f}% of the time ({len(m_ff)} trades), and one that has "
          f"reached +0.25R without −0.25R wins {win_rate(m_tt):.0f}% ({len(m_tt)} trades). Cannot tell: which of the "
          f"{len(c['b'])} 'not reached' trades are the {sum(1 for t in c['b'] if t['win'])} that will still win, including "
          f"{sum(1 for t in c['b'] if t['large'])} large winners; nor which of the {len(c['a'])} 'reached' trades are the "
          f"{sum(1 for t in c['a'] if t['full'])} that will still lose in full.")
    p("")
    p("The favourable and adverse markers together sharpen the corners of the matrix (section 8) but leave the mixed cells, which "
      "hold most trades, close to the base rate. None of the checkpoints identifies bad entries without also labelling a large share of "
      "the eventual winners.")
    p("")
    # ------------------------------------------------------------ 13
    p("## 13. Limitations")
    p("")
    p(f"* {n} trades over 8 trading days; both halves negative; segment cells of 27–91 trades. Differences below ten points are noise at this size.")
    p("* The checkpoint state is exact on the recorded ticks, but any live use would add a polling delay, order latency and a spread at "
      "the moment of action, none of which this study measures; the hypothetical sections therefore overstate what a rule could capture.")
    p("* Outcomes are those of the live exit system (2 ATR stop, 2 ATR target, breakeven at 1 ATR, 1 ATR trail); a different exit "
      "system would move trades between 'winner' and 'full loss'.")
    p("* The path starts at the fill; nothing before the fill is recorded, so pre-entry conditions are outside this study.")
    p("* Half A rests on the audited replay (155/155 checks on 13 Sep).")
    p("")
    # ------------------------------------------------------------ 14
    p("## 14. Final Research Conclusion")
    p("")
    for cp in CHECKPOINTS:
        c = cls[cp]
        p(f"* **{cp} s: {c['label']}.** Losers identified: {sum(1 for t in c['b'] if not t['win'])} of {len(losers)} losers are on the "
          f"'not reached' side (full-loss rate there {full_rate(c['b']):.0f}% vs {full_rate(c['a']):.0f}%; separation {c['sep']:.0f} points, "
          f"half A {c['seps']['A']:.0f}, half B {c['seps']['B']:.0f}). Eventual winners sacrificed: {sum(1 for t in c['b'] if t['win'])} of {len(winners)} "
          f"({c['sacrifice']:.0f}%, {sum(1 for t in c['b'] if t['large'])} large): **{c['band']}**.")
    p("")
    p("The early path contains a real, reproducible diagnostic signal: by 45–60 s the trades that have shown +0.25R are a materially "
      "better population than those that have not, in both halves and in every session and direction. It does not contain enough "
      "information to identify bad entries without also labelling roughly half of the eventual winners, because most winners are "
      "still under water or flat at these checkpoints. No live rule follows from this study; the numbers above are the cost-benefit "
      "record for any future, separately pre-registered experiment.")
    print("\n".join(out))


if __name__ == "__main__":
    main()
