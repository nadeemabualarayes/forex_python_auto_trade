"""Replay audit of path_recorder on every real scalp-test position - read-only, into a scratch folder.

    python docs/research/path_recorder_replay_audit.py

A replay terminal is built from REAL data pulled once from the MT5 terminal: every XAUUSD tick of the
period, every deal and order of every bot position, and the stop moves the bot journaled. The recorder's
own live code path (PathRecorder.observe / close) is then driven through that history at the bot's
2-second loop cadence, exactly as run() drives it, including injected faults:
  * a bot restart while a position is open (every 10th position, index 3)
  * the bot down across a position's exit, restarting afterwards (every 10th position, index 7)
The recorder's wait timers run on replay time, and flat stretches are only skipped once the recorder's periodic
deal-history scan has had its chance after each exit, as it would live.
Every recorded file is then checked against ground truth. Nothing touches the bot, its logs or any order.
"""
import calendar
import csv
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import MetaTrader5 as real                        # noqa: E402
import path_recorder as pr                        # noqa: E402
from execution import mt5_init_args               # noqa: E402

SYMBOL, MAGIC = "XAUUSD", 998811
STEP_MS = 2000                                    # the bot's loop cadence
FIX_TIME = datetime(2026, 9, 7, 14, 26, 39)


def srv(msc):
    return datetime.fromtimestamp(msc / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ============================================================================ real data, pulled once
def load_real():
    args, kw = mt5_init_args()
    assert real.initialize(*args, **kw), real.last_error()
    real.symbol_select(SYMBOL, True)
    deals = real.history_deals_get(0, 2 ** 31 - 1) or ()
    by_pos = defaultdict(list)
    for d in deals:
        if d.symbol == SYMBOL:
            by_pos[d.position_id].append(d)
    positions = {}
    for pid, ds in by_pos.items():
        ins = sorted((d for d in ds if d.entry == 0 and d.magic == MAGIC), key=lambda d: d.time_msc)
        outs = sorted((d for d in ds if d.entry in (1, 2, 3)), key=lambda d: d.time_msc)
        if not ins or not outs:
            continue
        positions[pid] = dict(pid=pid, ins=ins, outs=outs, deals=sorted(ds, key=lambda d: d.time_msc),
                              orders=list(real.history_orders_get(position=pid) or ()),
                              fill_ms=int(ins[0].time_msc), exit_ms=int(outs[-1].time_msc))
    t0 = min(p["fill_ms"] for p in positions.values()) - 120_000
    t1 = max(p["exit_ms"] for p in positions.values()) + 120_000
    ticks = real.copy_ticks_range(SYMBOL, t0 // 1000, t1 // 1000, real.COPY_TICKS_ALL)
    info = real.symbol_info(SYMBOL)
    return positions, ticks, info


def journal():
    entries, moves = {}, defaultdict(list)
    with open(os.path.join(ROOT, "logs", "trades.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["ticket"]:
                continue
            t = int(r["ticket"])
            s = calendar.timegm(datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timetuple())
            if r["event"] == "ENTRY":
                entries[t] = s
            elif r["event"] == "SL_MOVE":
                moves[t].append((s, float(r["sl"])))
    return entries, moves


# ============================================================================ replay terminal
class ReplayTerminal:
    """What the terminal would have answered at replay time `now` (ms), from the real data."""

    def __init__(self, positions, ticks, info, sl_changes):
        self.now = 0
        self.positions, self.ticks, self.info, self.sl_changes = positions, ticks, info, sl_changes
        self.tsec = ticks["time"]
        self.tmsc = ticks["time_msc"]
        for name in ("COPY_TICKS_ALL", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "POSITION_TYPE_BUY", "POSITION_TYPE_SELL",
                     "DEAL_ENTRY_IN", "DEAL_ENTRY_OUT", "DEAL_ENTRY_INOUT", "DEAL_ENTRY_OUT_BY"):
            setattr(self, name, getattr(real, name))

    def last_error(self):
        return (1, "Success")

    def symbol_info(self, symbol):
        return self.info

    def order_calc_profit(self, *a):
        return real.order_calc_profit(*a)

    def symbol_info_tick(self, symbol):
        k = int(np.searchsorted(self.tmsc, self.now, side="right")) - 1
        if k < 0:
            return None
        r = self.ticks[k]
        return SimpleNamespace(time=int(r["time"]), time_msc=int(r["time_msc"]), bid=float(r["bid"]), ask=float(r["ask"]))

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        a = int(np.searchsorted(self.tsec, int(date_from), side="left"))
        b = int(np.searchsorted(self.tsec, int(date_to), side="right"))
        cap = int(np.searchsorted(self.tmsc, self.now, side="right"))    # only ticks that have arrived
        return self.ticks[a:min(b, cap)]

    def sl_at(self, pid, ms):
        p = self.positions[pid]
        sl = float(p["open_order"].sl)
        for t, v in self.sl_changes.get(pid, ()):
            if t <= ms:
                sl = v
        return sl

    def positions_get(self):
        out = []
        for p in self.positions.values():
            if not (p["fill_ms"] <= self.now < p["exit_ms"]):
                continue
            vol = sum(d.volume for d in p["ins"] if d.time_msc <= self.now) - \
                sum(d.volume for d in p["outs"] if d.time_msc <= self.now)
            if vol <= 1e-9:
                continue
            i0 = p["ins"][0]
            out.append(SimpleNamespace(ticket=p["pid"], identifier=p["pid"], symbol=SYMBOL, magic=i0.magic, type=i0.type,
                                       volume=round(vol, 2), price_open=i0.price, sl=self.sl_at(p["pid"], self.now),
                                       tp=float(p["open_order"].tp), time=i0.time, time_msc=i0.time_msc,
                                       profit=0.0, price_current=i0.price))
        return tuple(out)

    def history_deals_get(self, date_from=None, date_to=None, position=None):
        if position is not None:
            p = self.positions.get(position)
            return tuple(d for d in p["deals"] if d.time_msc <= self.now) if p else ()
        return tuple(d for p in self.positions.values() for d in p["deals"]
                     if int(date_from) <= d.time <= int(date_to) and d.time_msc <= self.now)

    def history_orders_get(self, position=None):
        p = self.positions.get(position)
        return tuple(p["orders"]) if p else ()


# ============================================================================ main
def main():
    t_start = time.perf_counter()
    positions, ticks, info = load_real()
    jent, jmoves = journal()
    digits, point = int(info.digits), float(info.point)

    # align journal seconds (PC clock) to broker time using the ENTRY rows
    offs = [jent[pid] - p["fill_ms"] // 1000 for pid, p in positions.items() if pid in jent]
    offset = int(np.median(offs)) if offs else 0
    sl_changes = {}
    for pid, p in positions.items():
        p["open_order"] = next((o for o in p["orders"] if int(o.ticket) == pid), p["orders"][0])
        sl_changes[pid] = sorted(((s - offset) * 1000, v) for s, v in jmoves.get(pid, ()))
    term = ReplayTerminal(positions, ticks, info, sl_changes)
    pr.mt5 = term                                  # the recorder talks to the replay terminal only
    pr.time = SimpleNamespace(time=time.time, monotonic=lambda: term.now / 1000.0)   # its waits run on replay time

    order = sorted(positions.values(), key=lambda p: p["fill_ms"])
    faults = {}
    for i, p in enumerate(order):
        dur = p["exit_ms"] - p["fill_ms"]
        if i % 10 == 3 and dur >= 12_000:
            faults[p["pid"]] = ("restart", p["fill_ms"] + dur // 2, None)
        elif i % 10 == 7 and dur >= 12_000:
            faults[p["pid"]] = ("down", p["fill_ms"] + dur // 2, p["exit_ms"] + 7_000)

    scratch = tempfile.mkdtemp(prefix="pathrec_replay_")
    magics = [MAGIC]

    def recorder():
        return pr.PathRecorder(scratch, magics, [SYMBOL])

    rec = recorder()
    scans = sorted(p["exit_ms"] + pr.DISCOVER_S * 1000 + STEP_MS for p in order)   # a live loop scans within a minute
    fault_times = sorted((f[1], pid) for pid, f in faults.items())
    fired = set()
    down_until = None
    fills = [p["fill_ms"] for p in order]
    now = order[0]["fill_ms"] + order[0]["pid"] % STEP_MS
    t_end = max(p["exit_ms"] for p in order) + 10_000
    passes = 0
    while now <= t_end or (rec is not None and rec.tracked):
        term.now = now
        for ft, pid in fault_times:
            if ft <= now and pid not in fired:
                fired.add(pid)
                kind, _, up = faults[pid]
                if rec is not None:
                    rec.close()
                rec = None if kind == "down" else recorder()
                if kind == "down":
                    down_until = up
        if rec is None and down_until is not None and now >= down_until:
            rec, down_until = recorder(), None
        if rec is not None:
            rec.observe()
            passes += 1
        # jump ahead through flat periods (the recorder has nothing to do there)
        busy = any(p["fill_ms"] <= now < p["exit_ms"] for p in order) or (rec is not None and rec.tracked)
        nxt = now + STEP_MS
        if not busy and rec is not None:
            k = int(np.searchsorted(fills, now, side="right"))
            if k < len(fills):
                target = fills[k] + order[k]["pid"] % STEP_MS
                pending = [ft for ft, pid in fault_times if pid not in fired and ft > now]
                if pending:
                    target = min(target, pending[0])
                j = int(np.searchsorted(scans, now, side="right"))
                if j < len(scans):
                    target = min(target, scans[j])
                nxt = max(nxt, target)
        elif rec is None and down_until is not None:
            nxt = max(nxt, down_until)
        now = nxt
        if now > t_end + 600_000:
            break
    if rec is not None:
        rec.close()
    replay_s = time.perf_counter() - t_start

    # ------------------------------------------------------------------ ground truth checks
    rep147 = {}
    rp = os.path.join(ROOT, "docs", "research", "2026-09-11-exit-efficiency-147-trades.txt")
    if os.path.exists(rp):
        for line in open(rp, encoding="utf-8"):
            m = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d)\s+(LONG|SHORT)\s+.*?\s(SL|TRAIL|TP)\s+\d+\s+\d\d-\d\d", line)
            if m:
                rep147[(m.group(1), m.group(2))] = m.group(3)

    results, problems = [], []
    tmsc = ticks["time_msc"]
    for p in order:
        pid = p["pid"]
        path = os.path.join(scratch, "paths", f"{SYMBOL}_{pid}.jsonl")
        row = dict(pid=pid, fill=srv(p["fill_ms"]), fault=faults.get(pid, (None,))[0])
        if not os.path.exists(path):
            row.update(ok=False, issue="no file")
            results.append(row)
            problems.append(row)
            continue
        raw = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        data = pr.load_path(path)
        o, c = data["open"], data["close"]
        tk = [r for r in raw if r["type"] == "tick"]
        a = int(np.searchsorted(tmsc, p["fill_ms"], side="left"))
        b = int(np.searchsorted(tmsc, p["exit_ms"], side="right"))
        truth = [(int(t["time_msc"]), round(float(t["bid"]), digits), round(float(t["ask"]), digits)) for t in ticks[a:b]]
        got = [(t["msc"], t["bid"], t["ask"]) for t in tk]
        seqs = [t["seq"] for t in tk]
        pre = ticks[:a]
        pre = pre[pre["time_msc"] <= p["fill_ms"]] if len(pre) else pre
        qbf_truth = (dict(msc=int(pre[-1]["time_msc"]), bid=round(float(pre[-1]["bid"]), digits),
                          ask=round(float(pre[-1]["ask"]), digits)) if len(pre) else None)
        # a tick exactly at the fill millisecond is part of the path, so "before" means at-or-before via searchsorted
        k_at = int(np.searchsorted(tmsc, p["fill_ms"], side="right")) - 1
        qbf_truth = (dict(msc=int(tmsc[k_at]), bid=round(float(ticks[k_at]["bid"]), digits),
                          ask=round(float(ticks[k_at]["ask"]), digits)) if k_at >= 0 else None)
        qae = ticks[b] if b < len(ticks) and int(ticks[b]["time"]) <= p["exit_ms"] // 1000 + pr.AFTER_EXIT_S else None
        qae_truth = dict(msc=int(qae["time_msc"]), bid=round(float(qae["bid"]), digits),
                         ask=round(float(qae["ask"]), digits)) if qae is not None else None
        sl_bad = [t for t in tk if not t["amb"] and abs(t["sl"] - term.sl_at(pid, t["msc"])) > 0.5 * point]
        n_amb = sum(1 for t in tk if t["amb"])
        code = int(p["outs"][-1].reason)
        managed = any((s - offset) * 1000 <= p["exit_ms"] for s, _ in jmoves.get(pid, ()))
        expected = ("TP" if code == 5 else "manual" if code in (0, 1, 2) else "bot" if code == 3 else
                    ("TRAIL/BE" if managed else "SL") if code == 4 else "other")
        label_ok = (c["label"] in ("TRAIL", "BE")) if expected == "TRAIL/BE" else (c["label"] == expected)
        long = o["side"] == "LONG"
        lot = sum(d.volume for d in p["ins"])
        profit = sum(d.profit for d in p["deals"])
        deal_r = profit / (o["stop_dist"] * o["usd_per_unit_lot"] * lot)
        price_r = ((c["exit_vwap"] - o["fill_price"]) if long else (o["fill_price"] - c["exit_vwap"])) / o["stop_dist"]
        minute = datetime.fromtimestamp(p["fill_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        r147 = rep147.get((minute, o["side"]))
        l147_ok = None if r147 is None or code not in (4, 5) else (
            (r147 == "TP" and c["label"] == "TP") or (r147 == "SL" and c["label"] == "SL") or
            (r147 == "TRAIL" and c["label"] in ("TRAIL", "BE")))
        row.update(
            side=o["side"], code=code, label=c["label"], expected=expected, label_ok=label_ok, r147=r147, l147_ok=l147_ok,
            n_truth=len(truth), n_rec=len(got), exact=got == truth, dup_seq=len(seqs) != len(set(seqs)),
            seq_ok=seqs == list(range(1, len(seqs) + 1)),
            qbf_ok=o["quote_before_fill"] == qbf_truth, qae_ok=c["quote_after_exit"] == qae_truth,
            qae_none=qae_truth is None,
            sl_bad=len(sl_bad), amb=n_amb, complete=c["complete"], reasons=c["incomplete_reasons"],
            tail_verified=c.get("tail_verified"), final_sl_source=c.get("final_sl_source"),
            found_via=c.get("found_via"), after_exit=c.get("ticks_after_exit"), schema=o.get("schema"),
            r_diff=abs(deal_r - price_r), down=c["closed_while_recorder_down"],
            resumed=any(r["type"] == "resume" for r in raw), suspended=any(r["type"] == "suspend" for r in raw),
            opens=sum(1 for r in raw if r["type"] == "open"), closes=sum(1 for r in raw if r["type"] == "close"),
            size=os.path.getsize(path), prefix=datetime.fromtimestamp(p["fill_ms"] / 1000, timezone.utc).replace(tzinfo=None) < FIX_TIME)
        row["ok"] = (row["exact"] and not row["dup_seq"] and row["seq_ok"] and row["qbf_ok"] and row["qae_ok"]
                     and row["sl_bad"] == 0 and row["label_ok"] and row["r_diff"] < 0.01 and row["opens"] == 1
                     and row["closes"] == 1 and (row["l147_ok"] in (None, True)))
        results.append(row)
        if not row["ok"]:
            problems.append(row)

    # ------------------------------------------------------------------ report
    n = len(results)
    ok = [r for r in results if r.get("ok")]
    cat = defaultdict(int)
    for r in results:
        cat["pre-fix (0.18 lot)" if r.get("prefix") else ("closed by hand" if r.get("code") in (0, 1, 2)
                                                             else "strategy exit")] += 1
    print("=" * 110)
    print(f"PATH RECORDER REPLAY AUDIT - every real scalp-test position   generated {datetime.now():%Y-%m-%d %H:%M}")
    print("RESEARCH / VALIDATION ONLY - replay terminal built from real data; no bot, no orders, nothing under logs/")
    print("=" * 110)
    print(f"\nreal data: {len(positions)} bot positions ({dict(cat)}), {len(ticks):,} XAUUSD ticks "
          f"{srv(int(ticks['time_msc'][0]))} -> {srv(int(ticks['time_msc'][-1]))}")
    print(f"journal stop moves aligned to broker time with a {offset:+d} s offset (median of ENTRY rows vs fills)")
    print(f"replay: {passes:,} recorder passes at a {STEP_MS} ms cadence; injected faults: "
          f"{sum(1 for f in faults.values() if f[0] == 'restart')} restarts while open, "
          f"{sum(1 for f in faults.values() if f[0] == 'down')} positions closed while the bot was down; "
          f"{replay_s:.1f} s total; scratch folder {scratch}")

    def rate(key, want=True):
        k = sum(1 for r in results if r.get(key) == want)
        return f"{k}/{n}"

    print("\nCHECKS (every position)")
    print(f"  file with exactly one open and one close row          : {sum(1 for r in results if r.get('opens') == 1 and r.get('closes') == 1)}/{n}")
    print(f"  recorded ticks == every real tick in [fill, exit]     : {rate('exact')}   "
          f"(recorded {sum(r.get('n_rec', 0) for r in results):,} vs real {sum(r.get('n_truth', 0) for r in results):,})")
    print(f"  no duplicate seq, seq continuous 1..n                 : {sum(1 for r in results if r.get('seq_ok') and not r.get('dup_seq'))}/{n}")
    print(f"  quote_before_fill == real tick at/before the fill     : {rate('qbf_ok')}")
    print(f"  quote_after_exit  == real first tick after the exit   : {rate('qae_ok')}   "
          f"(within {pr.AFTER_EXIT_S} s of it; none there: {sum(1 for r in results if r.get('qae_ok') and r.get('qae_none'))})")
    print(f"  stop on non-ambiguous ticks == stop truly in force    : {sum(1 for r in results if r.get('sl_bad') == 0)}/{n}   "
          f"(wrong ticks: {sum(r.get('sl_bad', 0) for r in results)}; ambiguous ticks: {sum(r.get('amb', 0) for r in results):,})")
    print(f"  exit label == deal reason + journal stop moves        : {rate('label_ok')}")
    l147 = [r for r in results if r.get("l147_ok") is not None]
    print(f"  exit label == 147-trade report's classification      : {sum(1 for r in l147 if r['l147_ok'])}/{len(l147)}")
    print(f"  realised R from deals == R from exit price (< 0.01R)  : {sum(1 for r in results if r.get('r_diff', 1) < 0.01)}/{n}   "
          f"(max diff {max(r.get('r_diff', 0) for r in results):.4f}R)")
    print(f"\n  ALL CHECKS PASS: {len(ok)}/{n}")

    print("\nCOMPLETENESS")
    comp = [r for r in results if r.get("complete")]
    print(f"  complete paths: {len(comp)}/{n}")
    reasons = defaultdict(int)
    for r in results:
        for x in r.get("reasons") or ():
            reasons[x] += 1
    print(f"  incomplete reasons: {dict(reasons) if reasons else 'none'}")
    for r in results:
        if not r.get("complete"):
            print(f"    #{r['pid']} {r['fill']} {r.get('side')} {r.get('label')}: {r.get('reasons')}")
    print(f"  close tail verified by the exit stop: {sum(1 for r in results if r.get('tail_verified'))}/{n}; "
          f"final stop from the broker exit comment: {sum(1 for r in results if r.get('final_sl_source') == 'exit_deal_comment')}/{n}")

    print()
    print("RECORDING ROUTE")
    via = defaultdict(int)
    for r in results:
        via[r.get("found_via")] += 1
    print(f"  schema: {sorted({r.get('schema') for r in results if r.get('schema') is not None})}; "
          f"found_via: {dict(via)}; ticks written past an exit: {sum(r.get('after_exit') or 0 for r in results)}")
    for r in results:
        if r.get("found_via") == "deal_history":
            print(f"    #{r['pid']} {r['fill']} {r.get('side')} {r.get('label')}: found in deal history, "
                  f"{r.get('n_rec')} ticks, all-checks {'PASS' if r.get('ok') else 'FAIL'}")

    print("\nINJECTED FAULTS")
    for kind in ("restart", "down"):
        rows = [r for r in results if r.get("fault") == kind]
        good = [r for r in rows if r.get("ok")]
        flag = "resumed" if kind == "restart" else "down"
        print(f"  {kind:<8}: {len(good)}/{len(rows)} pass all checks; "
              f"{sum(1 for r in rows if (r.get('resumed') if kind == 'restart' else r.get('down')))}/{len(rows)} "
              f"show the {'resume' if kind == 'restart' else 'closed_while_recorder_down'} marker")

    print("\nBY EXIT LABEL")
    by = defaultdict(list)
    for r in results:
        by[r.get("label")].append(r)
    for lab, rows in sorted(by.items(), key=lambda kv: str(kv[0])):
        print(f"  {str(lab):<8} {len(rows):>4} positions, {sum(r.get('n_rec', 0) for r in rows):>9,} ticks, "
              f"{sum(1 for r in rows if r.get('ok'))} pass")

    sizes = [r["size"] for r in results if "size" in r]
    print(f"\nSTORAGE: {sum(sizes) / 1e6:.1f} MB for {n} positions (median {np.median(sizes) / 1e3:.0f} KB, "
          f"max {max(sizes) / 1e6:.2f} MB)")

    print("\nPROBLEMS")
    if not problems:
        print("  none")
    for r in problems:
        print(f"  #{r['pid']} {r['fill']} {r.get('side')} label {r.get('label')} expected {r.get('expected')} 147:{r.get('r147')} "
              f"exact={r.get('exact')} seq_ok={r.get('seq_ok')} dup={r.get('dup_seq')} qbf={r.get('qbf_ok')} "
              f"qae={r.get('qae_ok')} sl_bad={r.get('sl_bad')} r_diff={r.get('r_diff', 0):.4f} issue={r.get('issue')}")
    real.shutdown()


if __name__ == "__main__":
    main()
