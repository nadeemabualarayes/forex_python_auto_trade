"""Tick-path recorder: the raw broker quote path of every open bot position, for exit research.

Observability only. It never places, modifies or closes an order, never feeds anything back into the
strategy, and never raises into the trading loop. `run()` calls `observe()` after each `Bot.tick()`
(outside the tick, with the loop's sleep shortened by the time spent here, so the loop cadence is
unchanged) and `close()` on shutdown.

What it records, per position (key: the MT5 position identifier = ticket), into
    <LOG_DIR>/paths/<SYMBOL>_<position_id>.jsonl      append-only, one JSON object per line
    <LOG_DIR>/paths/index.jsonl                       one line per open / resume / suspend / close

  open           broker-confirmed fill (opening deal), initial SL/TP (opening order), R distance,
                 terminal-priced $ per 1.0 price move per lot, the last quote at or before the fill
  tick           EVERY broker tick the terminal holds from the fill to the exit (copy_ticks_range with
                 millisecond timestamps), never polled snapshots, never interpolated
  state          broker position snapshot when SL, TP or volume changed
  sl_move / tp_move / volume_change
                 a change seen in the broker's position. Ticks with msc <= `amb_after_msc` were under the
                 old value, ticks with msc > `amb_until_msc` under the new one; ticks in between carry
                 amb=true because the value in force at that exact tick is not known.
  gap            consecutive recorded ticks more than GAP_MS apart (quiet market or missing data)
  unavailable    the terminal returned no tick data for a fetch; nothing is filled in
  suspend/resume the recorder stopped/started while the position was open; on resume the missing
                 stretch is fetched from the terminal's tick history, so the path stays continuous
  close          broker-confirmed exit deal(s), exit reason, final SL, whether the stop ever moved,
                 path start/end, tick count, gaps, the first quote after the exit (waited for briefly), and
                 whether the path is complete. Ticks written before the terminal dropped the position but
                 stamped after the exit are counted in `ticks_after_exit`; load_path leaves them out of the path.

A position that opens and closes between two passes (or that a crashed run never listed) is found by a
periodic scan of recent deal history and recorded from the terminal's tick history (found_via=deal_history);
no pass saw its stop after the fill, so its ticks carry amb=true unless the exit proves the stop never moved.

Quote side: a long is marked at the BID (the price it can be closed at), a short at the ASK.
R = marked move from the fill / |fill - initial SL|.
"""
import json
import os
import re
import time
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import MetaTrader5 as mt5

from journal import log

SCHEMA = 2                 # 2: found_via, ticks_after_exit, waiting for the quote after the exit, discovery
PATH_DIR = "paths"
GAP_MS = 30_000            # consecutive recorded ticks further apart than this are flagged as a gap
EDGE_MS = 10_000           # a complete path starts within this of the fill and ends within this of the exit
CLOSE_WAIT_S = 60          # how long to wait for the exit deal after a position disappears
AFTER_EXIT_S = 10          # the first quote after an exit is looked for within this many seconds of it
EXIT_QUOTE_WAIT_S = 10     # and waited for this long (loop clock) before the close is written without it
DISCOVER_S = 60            # how often (server clock) recent deal history is scanned for positions no pass listed
DISCOVER_WINDOW_S = 900    # the scan covers deals this recent
RECONCILE_DAYS = 7         # on start-up, finalise positions opened this recently that never got a close row
OUT_ENTRIES = (1, 2, 3)    # DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY
REASONS = {0: "manual", 1: "manual", 2: "manual", 3: "bot", 4: "SL", 5: "TP", 6: "stopout"}
COUNTERS = ("unavailable", "gaps", "max_gap", "seq", "last_msc", "n_at_last", "n", "first_tick_msc", "last_tick_msc")


# ============================================================================ pure helpers (research reuses these)
def mark_price(long: bool, bid: float, ask: float) -> float:
    """The price the position is marked at: bid for a long, ask for a short."""
    return bid if long else ask


def r_multiple(long: bool, entry: float, mark: float, stop_dist):
    """Marked move from the entry in units of the initial stop distance; None without a stop."""
    if not stop_dist or stop_dist <= 0:
        return None
    return ((mark - entry) if long else (entry - mark)) / stop_dist


def unrealized(long: bool, entry: float, mark: float, usd_per_unit_lot, volume: float):
    """Unrealised P&L from terminal pricing ($ per 1.0 move per lot); None when that is unknown."""
    if usd_per_unit_lot is None:
        return None
    return ((mark - entry) if long else (entry - mark)) * usd_per_unit_lot * volume


def new_ticks(ticks, last_msc: int, n_at_last: int):
    """The ticks not yet recorded. MT5 range queries are whole seconds, so fetches overlap; ticks sharing
    the last recorded millisecond are kept only beyond the `n_at_last` already written.
    Returns (kept, new_last_msc, new_n_at_last)."""
    if ticks is None or len(ticks) == 0:
        return (ticks[:0] if ticks is not None else np.empty(0)), last_msc, n_at_last
    msc = ticks["time_msc"]
    keep = msc > last_msc
    same = np.flatnonzero(msc == last_msc)
    if same.size > n_at_last:
        keep[same[n_at_last:]] = True
    kept = ticks[keep]
    if len(kept) == 0:
        return kept, last_msc, n_at_last
    new_last = int(kept["time_msc"][-1])
    at_last = int((kept["time_msc"] == new_last).sum())
    return kept, new_last, (n_at_last + at_last) if new_last == last_msc else at_last


def value_for_tick(msc: int, prev_anchor, prev_value, anchor, value):
    """(value in force at this tick, ambiguous).

    A snapshot is anchored at the latest tick the terminal held when the position was read. The previous
    snapshot saw `prev_value` (latest tick `prev_anchor`), this one sees `value` (latest tick `anchor`).
    If they differ, the change came after `prev_anchor` but may postdate the tick at `anchor` itself (no tick
    has to arrive between a change and the read), so only ticks AFTER `anchor` are certainly under `value`:
    (prev_anchor, anchor] is ambiguous and the previous value is reported with the flag. Nothing is guessed."""
    if anchor is None or prev_value is None or prev_value == value or msc > anchor:
        return value, False
    if prev_anchor is not None and msc <= prev_anchor:
        return prev_value, False
    return prev_value, True


def threshold_touches(rows, long: bool, entry: float, stop_dist: float, levels):
    """First millisecond each R level was touched on the marked path ({level: msc or None}).
    Positive levels are favourable (r >= level), negative levels adverse (r <= level)."""
    out = {lv: None for lv in levels}
    pending = set(levels)
    for row in rows:
        if not pending:
            break
        mark = row.get("mark")
        if mark is None:
            continue
        r = r_multiple(long, entry, mark, stop_dist)
        if r is None:
            break
        for lv in list(pending):
            if (lv > 0 and r >= lv - 1e-9) or (lv < 0 and r <= lv + 1e-9):
                out[lv] = row["msc"]
                pending.discard(lv)
    return out


def first_reached(rows, long: bool, entry: float, stop_dist: float, level_a: float, level_b: float) -> str:
    """Which of two R levels the recorded path touched first: "a", "b", "neither", or "same_tick" when both
    were first touched in the same millisecond (the recording cannot order them)."""
    t = threshold_touches(rows, long, entry, stop_dist, (level_a, level_b))
    ta, tb = t[level_a], t[level_b]
    if ta is None and tb is None:
        return "neither"
    if tb is None:
        return "a"
    if ta is None:
        return "b"
    if ta == tb:
        return "same_tick"
    return "a" if ta < tb else "b"


def quality_from(fill_msc, exit_msc, n, first, last, max_gap, gaps, unavailable,
                 edge_ms: int = EDGE_MS) -> dict:
    reasons = []
    if unavailable:
        reasons.append("tick_fetch_unavailable")
    if exit_msc is None:
        reasons.append("exit_unknown")
    start_lag = end_lag = None
    if n == 0:
        reasons.append("no_ticks")
    else:
        start_lag = first - fill_msc if fill_msc is not None else None
        if start_lag is not None and start_lag > edge_ms:
            reasons.append("late_first_tick")
        if exit_msc is not None:
            end_lag = exit_msc - last
            if end_lag > edge_ms:
                reasons.append("early_last_tick")
        if gaps:
            reasons.append("internal_gap")
    return dict(n_ticks=n, start_lag_ms=start_lag, end_lag_ms=end_lag, max_gap_ms=max_gap, gaps=gaps,
                unavailable=unavailable, complete=not reasons, incomplete_reasons=reasons)


def path_quality(fill_msc, exit_msc, tick_mscs, unavailable: int, gap_ms: int = GAP_MS, edge_ms: int = EDGE_MS) -> dict:
    """Completeness of a recorded path, naming every defect."""
    m = list(tick_mscs)
    diffs = [b - a for a, b in zip(m, m[1:])]
    max_gap = max(diffs) if diffs else 0
    gaps = sum(1 for d in diffs if d > gap_ms)
    return quality_from(fill_msc, exit_msc, len(m), m[0] if m else None, m[-1] if m else None,
                        max_gap, gaps, unavailable, edge_ms)


def stop_from_comment(comment):
    """('sl'|'tp', level) from a broker exit-deal comment such as '[sl 4351.43]'; None otherwise."""
    if not comment:
        return None
    m = re.search(r"\[(sl|tp)\s+([0-9]+(?:\.[0-9]+)?)\]", str(comment))
    return (m.group(1), float(m.group(2))) if m else None


def reason_name(code) -> str:
    if code is None:
        return "unknown"
    return REASONS.get(int(code), "other")


def exit_label(code, long: bool, entry: float, sl0, final_sl, tol: float = 1e-6) -> str:
    """Broker reason refined by where the stop was: a stop hit is SL, BE (stop at entry) or TRAIL (in profit)."""
    if code is None:
        return "unknown"
    if int(code) == 5:
        return "TP"
    if int(code) == 4:
        if final_sl is None or sl0 is None or abs(final_sl - sl0) <= tol:
            return "SL"
        if abs(final_sl - entry) <= tol:
            return "BE"
        if (long and final_sl > entry) or (not long and final_sl < entry):
            return "TRAIL"
        return "SL"
    return reason_name(code)


def load_path(path: str) -> dict:
    """Read one position file: {open, close, ticks (deduplicated by seq, up to the exit), after_exit (ticks written
    before the terminal dropped the position but stamped after its exit), events (everything else)}."""
    out = dict(open=None, close=None, ticks=[], after_exit=[], events=[])
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = row.get("type")
            if kind == "open":
                out["open"] = out["open"] or row
            elif kind == "close":
                out["close"] = row
            elif kind == "tick":
                if row.get("seq") in seen:
                    continue
                seen.add(row.get("seq"))
                out["ticks"].append(row)
            else:
                out["events"].append(row)
    exit_msc = (out["close"] or {}).get("exit_msc")
    if exit_msc is not None:
        out["after_exit"] = [t for t in out["ticks"] if t["msc"] > exit_msc]
        out["ticks"] = [t for t in out["ticks"] if t["msc"] <= exit_msc]
    return out


# ============================================================================ recorder
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class _Pos:
    """In-memory state of one recorded position."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class PathRecorder:
    def __init__(self, log_dir: str, magics, symbols=()):
        self.dir = os.path.join(log_dir, PATH_DIR)
        self.magics = {int(m) for m in magics}
        self.symbols = list(symbols)             # the server clock for the deal-history scan (none: no scan)
        self.tracked: dict = {}
        self.finished: set = set()               # closed in this run: never recorded again
        self.reconciled = False
        self.discovered_at = None
        self._warned: set = set()

    # -- public ------------------------------------------------------------------------------
    def observe(self) -> None:
        """Record new ticks for open positions and finalise closed ones. Never raises."""
        try:
            self._observe()
        except Exception as exc:
            self._warn(f"path recorder: {type(exc).__name__}: {exc}")

    def close(self) -> None:
        """Shutdown: mark every open position suspended (it resumes on the next start). Never raises."""
        for pid, st in list(self.tracked.items()):
            try:
                if st.missing_since is None:
                    row = dict(type="suspend", pid=pid, symbol=st.symbol, last_msc=st.last_tick_msc,
                               anchor_msc=st.anchor, sl=st.sl, tp=st.tp, volume=st.vol, local=_now_iso())
                    self._write(st, [row])
                    self._index(row)
            except Exception as exc:
                self._warn(f"path recorder close: {type(exc).__name__}: {exc}")
        self.tracked.clear()

    # -- loop ------------------------------------------------------------------------------
    def _observe(self) -> None:
        positions = mt5.positions_get()
        if positions is None:                      # failed read: never infer a close from it
            return
        ours = {int(p.ticket): p for p in positions if int(p.magic) in self.magics}
        if not self.reconciled:
            self._reconcile(ours)
            self.reconciled = True
        for pid, p in ours.items():
            if pid in self.finished:
                continue
            try:
                st = self.tracked.get(pid)
                if st is None:
                    st = self._start(p)
                    if st is None:                 # its file already holds a close: never append a second life
                        self.finished.add(pid)
                        continue
                    self.tracked[pid] = st
                st.missing_since = None
                self._capture(st, p)
            except Exception as exc:
                self._warn(f"path recorder #{pid}: {type(exc).__name__}: {exc}")
        for pid in [k for k in self.tracked if k not in ours]:
            try:
                self._maybe_finalise(self.tracked[pid])
            except Exception as exc:
                self._warn(f"path recorder close #{pid}: {type(exc).__name__}: {exc}")
        try:
            self._maybe_discover(ours)
        except Exception as exc:
            self._warn(f"path recorder discovery: {type(exc).__name__}: {exc}")

    # -- lifecycle -------------------------------------------------------------------------
    def _start(self, p, found_via: str = "positions"):
        """Open (or resume) a position's file. None when the file already holds its close."""
        pid, symbol = int(p.ticket), p.symbol
        path = self._file(symbol, pid)
        if os.path.exists(path):
            st, closed = self._load_state(path)
            if closed:
                return None
            if st is not None:
                row = dict(type="resume", pid=pid, symbol=symbol, last_msc=st.last_tick_msc, reason="recorder_restart",
                           local=_now_iso())
                self._write(st, [row])
                self._index(row)
                return st
        long = int(p.type) == 0
        deals = mt5.history_deals_get(position=pid) or ()
        ins = sorted((d for d in deals if int(d.entry) == 0), key=lambda d: d.time_msc)
        if ins:
            fill_msc, entry, vol0, fill_src = int(ins[0].time_msc), float(ins[0].price), float(ins[0].volume), "deal"
        else:
            fill_msc, entry, vol0, fill_src = int(p.time_msc), float(p.price_open), float(p.volume), "position"
        orders = mt5.history_orders_get(position=pid) or ()
        opening = [o for o in orders if int(o.ticket) == pid] or sorted(
            (o for o in orders if int(o.type) in (0, 1)), key=lambda o: getattr(o, "time_setup_msc", 0))
        if opening and float(opening[0].sl) > 0:
            sl0, tp0, sl_src = float(opening[0].sl), float(opening[0].tp), "order"
        else:
            sl0, tp0, sl_src = float(p.sl), float(p.tp), "position_first_seen"
        info = mt5.symbol_info(symbol)
        digits = int(info.digits) if info is not None else None
        point = float(info.point) if info is not None else None
        value = None
        calc = getattr(mt5, "order_calc_profit", None)
        if callable(calc):
            v = calc(mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL, symbol, 1.0, entry,
                     entry + 1.0 if long else entry - 1.0)
            value = float(v) if v is not None and v > 0 else None
        quote = None
        pre = mt5.copy_ticks_range(symbol, fill_msc // 1000 - 10, fill_msc // 1000 + 1, mt5.COPY_TICKS_ALL)
        if pre is not None and len(pre):
            pre = pre[pre["time_msc"] <= fill_msc]
            if len(pre):
                quote = dict(msc=int(pre[-1]["time_msc"]), bid=self._rnd(float(pre[-1]["bid"]), digits),
                             ask=self._rnd(float(pre[-1]["ask"]), digits))
        st = _Pos(pid=pid, symbol=symbol, long=long, magic=int(p.magic), fill_msc=fill_msc, entry=entry, sl0=sl0,
                  tp0=tp0, stop=abs(entry - sl0) if sl0 > 0 else None, value=value, digits=digits, point=point,
                  path=path, seq=0, last_msc=fill_msc - 1, n_at_last=0, anchor=fill_msc, sl=sl0, tp=tp0, vol=vol0,
                  prev_anchor=None, prev_sl=None, prev_tp=None, prev_vol=None, n=0, first_tick_msc=None,
                  last_tick_msc=None, max_gap=0, gaps=0, unavailable=0, moves=0, missing_since=None, down=False,
                  found_via=found_via)
        header = dict(type="open", schema=SCHEMA, pid=pid, symbol=symbol, side="LONG" if long else "SHORT",
                      magic=st.magic, volume=vol0, fill_msc=fill_msc, fill_price=entry, fill_source=fill_src,
                      sl0=sl0, tp0=tp0, sl0_source=sl_src, stop_dist=st.stop, usd_per_unit_lot=value,
                      quote_before_fill=quote, gap_ms=GAP_MS, found_via=found_via, recorded_local=_now_iso())
        state = dict(type="state", pid=pid, anchor_msc=fill_msc, prev_anchor_msc=None, sl=sl0, tp=tp0, volume=vol0,
                     broker_profit=None, price_current=None, note="at_fill", local=_now_iso())
        self._write(st, [header, state])
        self._index(header)
        return st

    def _capture(self, st: _Pos, p) -> None:
        """One snapshot + the ticks since the last one. State advances only after the rows are on disk, so a
        failed write is retried from the same point next loop instead of silently skipping ticks."""
        tick = mt5.symbol_info_tick(st.symbol)
        anchor = int(tick.time_msc) if tick is not None and getattr(tick, "time_msc", 0) else None
        sl, tp, vol = float(p.sl), float(p.tp), float(p.volume)
        snap = dict(prev_anchor=st.anchor, prev_sl=st.sl, prev_tp=st.tp, prev_vol=st.vol,
                    anchor=anchor, sl=sl, tp=tp, vol=vol, moves=st.moves)
        events = []
        tol = 0.5 * st.point if st.point else 1e-9
        for kind, old, new in (("sl_move", st.sl, sl), ("tp_move", st.tp, tp), ("volume_change", st.vol, vol)):
            if old is None or abs(old - new) > (tol if kind != "volume_change" else 1e-9):
                events.append(dict(type=kind, pid=st.pid, **{"from": old, "to": new}, amb_after_msc=st.anchor,
                                   amb_until_msc=anchor, local=_now_iso()))
                if kind == "sl_move":
                    snap["moves"] += 1
        if events:
            events.append(dict(type="state", pid=st.pid, anchor_msc=anchor, prev_anchor_msc=st.anchor, sl=sl,
                               tp=tp, volume=vol, broker_profit=float(getattr(p, "profit", 0.0)),
                               price_current=float(getattr(p, "price_current", 0.0)), local=_now_iso()))
        view = _Pos(**{**st.__dict__, **snap})
        rows, _ = self._fetch_rows(view, None, tick_anchor=anchor if anchor is not None else float("inf"))
        if anchor is None and view.last_tick_msc is not None:
            snap["anchor"] = view.last_tick_msc
        self._write(st, events + rows)
        st.__dict__.update(snap)
        st.__dict__.update({k: getattr(view, k) for k in COUNTERS})

    def _maybe_finalise(self, st: _Pos) -> None:
        deals = mt5.history_deals_get(position=st.pid)
        outs = sorted((d for d in (deals or ()) if int(d.entry) in OUT_ENTRIES), key=lambda d: d.time_msc)
        if st.missing_since is None:
            st.missing_since = time.monotonic()
        waited = time.monotonic() - st.missing_since
        if not outs and waited < CLOSE_WAIT_S:
            return
        self._finalise(st, outs, patient=waited < EXIT_QUOTE_WAIT_S)

    def _finalise(self, st: _Pos, outs, patient: bool = False) -> None:
        """Write the close. While `patient`, a close whose tail or first quote after the exit has not arrived (or
        could not be read) is left for the next pass; nothing is written or committed until then."""
        exit_msc = int(outs[-1].time_msc) if outs else None
        code = int(outs[-1].reason) if outs else None
        tol = 0.5 * st.point if st.point else 1e-6
        fired = stop_from_comment(getattr(outs[-1], "comment", None)) if outs else None
        if fired is not None and fired[0] == "sl" and code == 4:
            final_sl, sl_source = fired[1], "exit_deal_comment"   # the broker's own record of the stop that fired
            # stops only ever tighten, so an exit stop equal to the last one seen proves it never moved after that
            tail_verified = st.sl is not None and abs(final_sl - st.sl) <= tol
        else:
            final_sl, sl_source, tail_verified = st.sl, "last_snapshot", False
        events = []
        if fired is not None and fired[0] == "sl" and code == 4 and not tail_verified:
            events.append(dict(type="sl_move", pid=st.pid, **{"from": st.sl, "to": final_sl},
                               amb_after_msc=st.anchor, amb_until_msc=exit_msc, note="seen_only_in_exit_deal",
                               local=_now_iso()))
        # Ticks after the last snapshot have no later snapshot to confirm the stop: unless the exit proves it did not
        # move, they are ambiguous (the value last seen is reported with amb=true).
        view = _Pos(**st.__dict__)                       # counters commit only once the close is on disk
        unverified = object()
        view.prev_anchor, view.prev_sl, view.prev_tp, view.prev_vol = st.anchor, st.sl, st.tp, st.vol
        if not tail_verified:
            view.sl, view.tp = unverified, unverified
        over = []
        if exit_msc is not None and st.last_tick_msc is not None and st.last_tick_msc > exit_msc:
            # the terminal still listed the position after ticks past its exit had arrived: those are already on disk
            written = load_path(st.path)["ticks"]
            inside = [t["msc"] for t in written if t["msc"] <= exit_msc]
            over = [t for t in written if t["msc"] > exit_msc]
            rows, after = [], (dict(msc=over[0]["msc"], bid=over[0]["bid"], ask=over[0]["ask"]) if over else None)
            quality = path_quality(st.fill_msc, exit_msc, inside, st.unavailable)
            path_start, path_end = (inside[0], inside[-1]) if inside else (None, None)
        else:
            rows, after = ([], None)
            if exit_msc is not None:
                rows, after = self._fetch_rows(view, exit_msc, tick_anchor=float("inf"))
                if patient and after is None:
                    return
            quality = quality_from(st.fill_msc, exit_msc, view.n, view.first_tick_msc, view.last_tick_msc,
                                   view.max_gap, view.gaps, view.unavailable)
            path_start, path_end = view.first_tick_msc, view.last_tick_msc
        vol_sum = sum(float(d.volume) for d in outs)
        close = dict(
            type="close", pid=st.pid, symbol=st.symbol, side="LONG" if st.long else "SHORT",
            exit_msc=exit_msc, exit_price=float(outs[-1].price) if outs else None,
            exit_vwap=(sum(float(d.price) * float(d.volume) for d in outs) / vol_sum) if vol_sum else None,
            reason_code=code, reason=reason_name(code),
            label=exit_label(code, st.long, st.entry, st.sl0, final_sl, tol),
            final_sl=final_sl, final_sl_source=sl_source, final_sl_observed=st.sl,
            sl_moved=bool(st.moves) or (st.sl0 is not None and final_sl is not None and abs(final_sl - st.sl0) > tol),
            tail_after_msc=st.anchor, tail_verified=tail_verified,
            deals=[dict(ticket=int(d.ticket), entry=int(d.entry), reason=int(d.reason), time_msc=int(d.time_msc),
                        price=float(d.price), volume=float(d.volume), profit=float(getattr(d, "profit", 0.0)),
                        comment=str(getattr(d, "comment", "") or ""))
                   for d in outs],
            path_start_msc=path_start, path_end_msc=path_end, ticks_after_exit=len(over),
            quote_after_exit=after, closed_while_recorder_down=bool(st.down), found_via=st.found_via,
            local=_now_iso(), **quality)
        self._write(st, events + rows + [close])
        self.tracked.pop(st.pid, None)                   # the file now holds the close: never write it twice
        self.finished.add(st.pid)
        try:
            self._index(close)
        except OSError as exc:
            self._warn(f"path recorder index #{st.pid}: {exc}")

    def _reconcile(self, ours: dict) -> None:
        """Positions opened before the recorder last stopped and never closed in the log: finalise them."""
        index = os.path.join(self.dir, "index.jsonl")
        if not os.path.exists(index):
            return
        opened, closed = {}, set()
        horizon = time.time() - RECONCILE_DAYS * 86400
        with open(index, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") == "open":
                    try:
                        if datetime.fromisoformat(row["recorded_local"]).timestamp() < horizon:
                            continue
                    except (KeyError, ValueError):
                        pass
                    opened[int(row["pid"])] = row
                elif row.get("type") == "close":
                    closed.add(int(row["pid"]))
        for pid, row in opened.items():
            if pid in closed or pid in ours or pid in self.tracked:
                continue
            st, _ = self._load_state(self._file(row["symbol"], pid))
            if st is None:
                continue
            st.down = True
            st.missing_since = time.monotonic()
            self.tracked[pid] = st
            self._maybe_finalise(st)

    def _maybe_discover(self, ours: dict) -> None:
        """Every DISCOVER_S of server time, look through recent deal history for bot positions that no pass ever
        listed (opened and closed between two passes, or lost to a crash) and record them from tick history."""
        if not self.symbols:
            return
        clock = self._server_clock_msc()
        if clock is None or (self.discovered_at is not None and clock - self.discovered_at < DISCOVER_S * 1000):
            return
        deals = mt5.history_deals_get(clock // 1000 - DISCOVER_WINDOW_S, clock // 1000 + 3600)
        if deals is None:                          # failed read: scan again on the next pass
            return
        self.discovered_at = clock
        candidates = {}
        for d in deals:
            if int(d.magic) in self.magics:
                candidates.setdefault(int(d.position_id), d.symbol)
        for pid, symbol in candidates.items():
            if pid in ours or pid in self.tracked or pid in self.finished or os.path.exists(self._file(symbol, pid)):
                continue
            try:
                self._discover(pid)
            except Exception as exc:
                self._warn(f"path recorder discovery #{pid}: {type(exc).__name__}: {exc}")

    def _discover(self, pid: int) -> None:
        deals = mt5.history_deals_get(position=pid) or ()
        ins = sorted((d for d in deals if int(d.entry) == 0 and int(d.magic) in self.magics), key=lambda d: d.time_msc)
        outs = [d for d in deals if int(d.entry) in OUT_ENTRIES]
        if not ins or sum(float(d.volume) for d in outs) + 1e-9 < sum(float(d.volume) for d in ins):
            return                                 # not opened by the bot, or still open: a pass will list it
        first = ins[0]
        p = SimpleNamespace(ticket=pid, symbol=first.symbol, magic=int(first.magic), type=int(first.type),
                            volume=float(first.volume), price_open=float(first.price), time_msc=int(first.time_msc),
                            sl=0.0, tp=0.0)       # sl/tp come from the opening order; 0 means none was set
        st = self._start(p, found_via="deal_history")
        if st is None:
            self.finished.add(pid)
            return
        self.tracked[pid] = st
        self._maybe_finalise(st)

    def _server_clock_msc(self):
        """The latest tick time over the recorder's symbols: the terminal's own clock, which stops with the market."""
        latest = None
        for s in self.symbols:
            t = mt5.symbol_info_tick(s)
            msc = int(getattr(t, "time_msc", 0) or 0) if t is not None else 0
            if msc and (latest is None or msc > latest):
                latest = msc
        return latest

    # -- ticks ------------------------------------------------------------------------------
    def _fetch_rows(self, st: _Pos, upto_msc, tick_anchor):
        """Tick rows since the last recorded tick (up to `upto_msc` when closing) and the first tick after it."""
        frm = max(0, st.last_msc // 1000)
        to = int(time.time()) + 86400 if upto_msc is None else upto_msc // 1000 + AFTER_EXIT_S
        raw = mt5.copy_ticks_range(st.symbol, frm, to, mt5.COPY_TICKS_ALL)
        if raw is None:
            st.unavailable += 1
            err = mt5.last_error() if callable(getattr(mt5, "last_error", None)) else None
            return [dict(type="unavailable", pid=st.pid, from_msc=st.last_msc, to_msc=upto_msc, error=str(err),
                         local=_now_iso())], None
        kept, _, _ = new_ticks(raw, st.last_msc, st.n_at_last)
        after = None
        if upto_msc is not None and len(kept):
            cut = int(np.searchsorted(kept["time_msc"], upto_msc, side="right"))
            if cut < len(kept):
                a = kept[cut]
                after = dict(msc=int(a["time_msc"]), bid=self._rnd(float(a["bid"]), st.digits),
                             ask=self._rnd(float(a["ask"]), st.digits))
            kept = kept[:cut]
        rows = []
        d = st.digits
        for tk in kept:
            msc = int(tk["time_msc"])
            bid, ask = float(tk["bid"]), float(tk["ask"])
            if st.last_tick_msc is not None and msc - st.last_tick_msc > GAP_MS:
                st.gaps += 1
                rows.append(dict(type="gap", pid=st.pid, from_msc=st.last_tick_msc, to_msc=msc, ms=msc - st.last_tick_msc))
            if st.last_tick_msc is not None:
                st.max_gap = max(st.max_gap, msc - st.last_tick_msc)
            sl, a1 = value_for_tick(msc, st.prev_anchor, st.prev_sl, tick_anchor, st.sl)
            tp, a2 = value_for_tick(msc, st.prev_anchor, st.prev_tp, tick_anchor, st.tp)
            vol, a3 = value_for_tick(msc, st.prev_anchor, st.prev_vol, tick_anchor, st.vol)
            valid = bid > 0 and ask > 0
            mark = mark_price(st.long, bid, ask) if valid else None
            upnl = unrealized(st.long, st.entry, mark, st.value, vol) if valid else None
            r = r_multiple(st.long, st.entry, mark, st.stop) if valid else None
            st.seq += 1
            rows.append(dict(
                type="tick", pid=st.pid, seq=st.seq, msc=msc, bid=self._rnd(bid, d), ask=self._rnd(ask, d),
                spread_pts=round((ask - bid) / st.point, 1) if valid and st.point else None, flags=int(tk["flags"]),
                symbol=st.symbol, side="LONG" if st.long else "SHORT", volume=vol, entry=st.entry, sl0=st.sl0,
                sl=sl, tp=tp, amb=bool(a1 or a2 or a3), mark=self._rnd(mark, d) if mark is not None else None,
                upnl=round(upnl, 4) if upnl is not None else None, r=round(r, 4) if r is not None else None))
            if msc == st.last_msc:
                st.n_at_last += 1
            else:
                st.last_msc, st.n_at_last = msc, 1
            st.n += 1
            if st.first_tick_msc is None:
                st.first_tick_msc = msc
            st.last_tick_msc = msc
        return rows, after

    # -- files ------------------------------------------------------------------------------
    def _file(self, symbol: str, pid: int) -> str:
        return os.path.join(self.dir, f"{symbol}_{pid}.jsonl")

    def _write(self, st: _Pos, rows) -> None:
        if not rows:
            return
        os.makedirs(self.dir, exist_ok=True)
        with open(st.path, "a", encoding="utf-8", newline="\n") as f:
            f.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))

    def _index(self, row: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        slim = {k: v for k, v in row.items() if k not in ("deals",)}
        with open(os.path.join(self.dir, "index.jsonl"), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(slim, separators=(",", ":")) + "\n")

    def _load_state(self, path: str):
        """Rebuild a position's recorder state from its file (resume / reconcile): (state, closed). The state is None
        when the file already holds a close or has no readable header."""
        data = load_path(path)
        h = data["open"]
        if data["close"] is not None:
            return None, True
        if h is None:
            return None, False
        st = _Pos(pid=int(h["pid"]), symbol=h["symbol"], long=h["side"] == "LONG", magic=int(h["magic"]),
                  fill_msc=int(h["fill_msc"]), entry=float(h["fill_price"]), sl0=h["sl0"], tp0=h["tp0"],
                  stop=h["stop_dist"], value=h["usd_per_unit_lot"], digits=None, point=None, path=path, seq=0,
                  last_msc=int(h["fill_msc"]) - 1, n_at_last=0, anchor=int(h["fill_msc"]), sl=h["sl0"], tp=h["tp0"],
                  vol=float(h["volume"]), prev_anchor=None, prev_sl=None, prev_tp=None, prev_vol=None, n=0,
                  first_tick_msc=None, last_tick_msc=None, max_gap=0, gaps=0, unavailable=0, moves=0,
                  missing_since=None, down=False, found_via=h.get("found_via", "positions"))
        info = mt5.symbol_info(st.symbol)
        if info is not None:
            st.digits, st.point = int(info.digits), float(info.point)
        for t in data["ticks"]:
            msc = int(t["msc"])
            st.seq = max(st.seq, int(t["seq"]))
            if st.last_tick_msc is not None:
                gap = msc - st.last_tick_msc
                st.max_gap = max(st.max_gap, gap)
                st.gaps += gap > GAP_MS
            if msc == st.last_msc:
                st.n_at_last += 1
            else:
                st.last_msc, st.n_at_last = msc, 1
            st.first_tick_msc = st.first_tick_msc if st.first_tick_msc is not None else msc
            st.last_tick_msc = msc
            st.n += 1
        for e in data["events"]:
            kind = e.get("type")
            if kind in ("state", "suspend") and e.get("anchor_msc") is not None:
                st.anchor, st.sl, st.tp, st.vol = int(e["anchor_msc"]), e["sl"], e["tp"], float(e["volume"])
            elif kind == "unavailable":
                st.unavailable += 1
            elif kind == "sl_move":
                st.moves += 1
        return st, False

    @staticmethod
    def _rnd(x, digits):
        return round(x, digits) if digits is not None else x

    def _warn(self, text: str) -> None:
        if text not in self._warned:
            self._warned.add(text)
            log.warning(text)
