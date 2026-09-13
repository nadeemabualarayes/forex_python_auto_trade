"""Tick-path recorder: raw broker ticks per open bot position, for exit research. Observability only."""
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

import path_recorder as pr
from path_recorder import (PathRecorder, first_reached, load_path, mark_price, new_ticks, path_quality,
                           r_multiple, threshold_touches, unrealized, value_for_tick)

MAGIC = 998811
TICK_DTYPE = [("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("last", "<f8"), ("volume", "<u8"),
              ("time_msc", "<i8"), ("flags", "<u4"), ("volume_real", "<f8")]


def ticks(rows):
    """rows: (msc, bid, ask)."""
    return np.array([(m // 1000, b, a, 0.0, 0, m, 6, 0.0) for m, b, a in rows], dtype=TICK_DTYPE)


# ============================================================================ pure helpers
class TestMarking:
    def test_long_marks_at_bid_short_marks_at_ask(self):
        assert mark_price(True, 100.0, 100.4) == 100.0
        assert mark_price(False, 100.0, 100.4) == 100.4

    def test_r_multiple_uses_the_initial_stop_distance(self):
        # long entry 100, initial SL 98 -> R = 2.0; bid 101 is +0.5R, bid 97 is -1.5R
        assert r_multiple(True, 100.0, 101.0, 2.0) == pytest.approx(0.5)
        assert r_multiple(True, 100.0, 97.0, 2.0) == pytest.approx(-1.5)
        # short entry 100, initial SL 102 -> R = 2.0; ask 99 is +0.5R, ask 103 is -1.5R
        assert r_multiple(False, 100.0, 99.0, 2.0) == pytest.approx(0.5)
        assert r_multiple(False, 100.0, 103.0, 2.0) == pytest.approx(-1.5)
        assert r_multiple(True, 100.0, 101.0, 0.0) is None
        assert r_multiple(True, 100.0, 101.0, None) is None

    def test_unrealized_uses_terminal_pricing_and_never_guesses(self):
        # XAUUSD: the terminal prices a 1.0 move on 1 lot at $100
        assert unrealized(True, 100.0, 101.5, 100.0, 0.02) == pytest.approx(3.0)
        assert unrealized(False, 100.0, 101.5, 100.0, 0.01) == pytest.approx(-1.5)
        assert unrealized(True, 100.0, 101.5, None, 0.01) is None


class TestNewTicks:
    def test_keeps_only_ticks_not_already_recorded(self):
        t = ticks([(1000, 1, 1.1), (2000, 2, 2.1), (3000, 3, 3.1)])
        kept, last, n = new_ticks(t, 2000, 1)
        assert list(kept["time_msc"]) == [3000] and (last, n) == (3000, 1)

    def test_same_millisecond_ticks_are_neither_lost_nor_duplicated(self):
        t = ticks([(2000, 2, 2.1), (2000, 2.01, 2.11), (2000, 2.02, 2.12), (2500, 3, 3.1)])
        kept, last, n = new_ticks(t, 2000, 1)              # one tick at 2000 already written
        assert [float(x) for x in kept["bid"]] == [2.01, 2.02, 3.0] and (last, n) == (2500, 1)
        kept2, last2, n2 = new_ticks(t[:3], 2000, 1)       # the later fetch only has more at 2000
        assert len(kept2) == 2 and (last2, n2) == (2000, 3)
        kept3, last3, n3 = new_ticks(t[:3], 2000, 3)
        assert len(kept3) == 0 and (last3, n3) == (2000, 3)

    def test_empty_or_missing_input(self):
        kept, last, n = new_ticks(None, 5, 0)
        assert len(kept) == 0 and (last, n) == (5, 0)


class TestThresholdOrdering:
    ROWS = [dict(msc=1, mark=100.0), dict(msc=2, mark=100.6), dict(msc=3, mark=98.9),
            dict(msc=4, mark=101.6), dict(msc=5, mark=102.1)]

    def test_touch_times_in_r_for_a_long(self):
        # entry 100, R 2: +0.25R=100.5 at msc 2, -0.5R=99 at msc 3, +0.75R=101.5 at msc 4, +1R=102 at msc 5
        t = threshold_touches(self.ROWS, True, 100.0, 2.0, (0.25, -0.5, 0.75, 1.0, -1.0))
        assert t == {0.25: 2, -0.5: 3, 0.75: 4, 1.0: 5, -1.0: None}

    def test_which_level_came_first(self):
        assert first_reached(self.ROWS, True, 100.0, 2.0, 0.25, -0.5) == "a"
        assert first_reached(self.ROWS, True, 100.0, 2.0, 0.5, -0.5) == "b"     # +0.5R=101 only at msc 4
        assert first_reached(self.ROWS, True, 100.0, 2.0, 0.75, -0.5) == "b"
        assert first_reached(self.ROWS, True, 100.0, 2.0, 1.0, -1.0) == "a"
        assert first_reached(self.ROWS, True, 100.0, 2.0, 2.0, -2.0) == "neither"

    def test_short_side_uses_the_ask_path(self):
        rows = [dict(msc=1, mark=100.0), dict(msc=2, mark=101.1), dict(msc=3, mark=98.4)]
        # short entry 100, R 2: -0.5R is an ask of 101 (msc 2), +0.75R is an ask of 98.5 (msc 3)
        assert first_reached(rows, False, 100.0, 2.0, 0.75, -0.5) == "b"
        assert threshold_touches(rows, False, 100.0, 2.0, (0.75,)) == {0.75: 3}

    def test_same_millisecond_is_reported_not_resolved(self):
        rows = [dict(msc=7, mark=101.0), dict(msc=7, mark=99.0)]
        assert first_reached(rows, True, 100.0, 2.0, 0.5, -0.5) == "same_tick"


class TestValueForTick:
    def test_known_ambiguous_and_after(self):
        # the snapshot whose latest tick was msc 1000 saw SL 90; the one whose latest tick was msc 3000 sees SL 95.
        # The change can postdate the tick at 3000 (no tick need arrive between a change and the snapshot), so
        # only ticks AFTER 3000 are certainly under 95; (1000, 3000] is ambiguous.
        assert value_for_tick(500, 1000, 90.0, 3000, 95.0) == (90.0, False)
        assert value_for_tick(1000, 1000, 90.0, 3000, 95.0) == (90.0, False)
        assert value_for_tick(2000, 1000, 90.0, 3000, 95.0) == (90.0, True)
        assert value_for_tick(3000, 1000, 90.0, 3000, 95.0) == (90.0, True)
        assert value_for_tick(3001, 1000, 90.0, 3000, 95.0) == (95.0, False)
        assert value_for_tick(2000, 1000, 95.0, 3000, 95.0) == (95.0, False)   # unchanged: never ambiguous
        assert value_for_tick(2000, None, None, None, 95.0) == (95.0, False)


class TestPathQuality:
    def test_complete_path(self):
        q = path_quality(1000, 60_000, [1000, 1500, 30_000, 59_000], 0)
        assert q["complete"] and q["n_ticks"] == 4 and q["incomplete_reasons"] == []

    def test_each_defect_is_named(self):
        q = path_quality(1000, 200_000, [20_000, 25_000, 150_000], 2)
        assert not q["complete"]
        assert set(q["incomplete_reasons"]) == {"tick_fetch_unavailable", "late_first_tick", "early_last_tick",
                                               "internal_gap"}
        assert q["max_gap_ms"] == 125_000 and q["gaps"] == 1

    def test_no_ticks_at_all(self):
        q = path_quality(1000, 5000, [], 0)
        assert not q["complete"] and "no_ticks" in q["incomplete_reasons"]


# ============================================================================ recorder with a fake terminal
class FakeTerminal:
    """Just enough of the MetaTrader5 module: ticks 'arrive' as now_msc advances."""
    COPY_TICKS_ALL = -1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3

    def __init__(self, tick_rows):
        self.all = ticks(tick_rows)
        self.now_msc = 0
        self.positions = {}
        self.deals = {}
        self.orders = {}
        self.fail_ticks = False
        self.fail_positions = False
        self.raise_everything = False
        self.fetches = []

    def _guard(self):
        if self.raise_everything:
            raise RuntimeError("terminal exploded")

    def last_error(self):
        return (-1, "fake error")

    def symbol_info(self, symbol):
        return SimpleNamespace(digits=2, point=0.01)

    def symbol_info_tick(self, symbol):
        self._guard()
        arrived = self.all[self.all["time_msc"] <= self.now_msc]
        if not len(arrived):
            return None
        r = arrived[-1]
        return SimpleNamespace(time=int(r["time"]), time_msc=int(r["time_msc"]), bid=float(r["bid"]), ask=float(r["ask"]))

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        self._guard()
        self.fetches.append((date_from, date_to))
        if self.fail_ticks:
            return None
        sel = (self.all["time"] >= int(date_from)) & (self.all["time"] <= int(date_to)) & (self.all["time_msc"] <= self.now_msc)
        return self.all[sel]

    def positions_get(self):
        self._guard()
        if self.fail_positions:
            return None
        return tuple(self.positions.values())

    def history_deals_get(self, position=None):
        self._guard()
        return tuple(self.deals.get(position, ()))

    def history_orders_get(self, position=None):
        self._guard()
        return tuple(self.orders.get(position, ()))

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        move = (price_close - price_open) if order_type == 0 else (price_open - price_close)
        return move * 100.0 * volume

    # scenario helpers ---------------------------------------------------------------
    def open_position(self, pid, long, fill_msc, price, sl, tp, volume=0.01, magic=MAGIC, symbol="XAUUSD"):
        self.positions[pid] = SimpleNamespace(ticket=pid, identifier=pid, symbol=symbol, magic=magic,
                                              type=0 if long else 1, volume=volume, price_open=price, sl=sl, tp=tp,
                                              time=fill_msc // 1000, time_msc=fill_msc, profit=0.0, price_current=price)
        self.deals[pid] = [SimpleNamespace(ticket=pid * 10, entry=0, reason=3, time_msc=fill_msc, price=price,
                                           volume=volume, profit=0.0, type=0 if long else 1, magic=magic)]
        self.orders[pid] = [SimpleNamespace(ticket=pid, type=0 if long else 1, sl=sl, tp=tp)]

    def close_position(self, pid, exit_msc, price, reason, volume=None, profit=0.0):
        p = self.positions[pid]
        vol = p.volume if volume is None else volume
        self.deals[pid].append(SimpleNamespace(ticket=pid * 10 + len(self.deals[pid]), entry=1, reason=reason,
                                               time_msc=exit_msc, price=price, volume=vol, profit=profit,
                                               type=1 if p.type == 0 else 0, magic=0 if reason in (0, 1, 2) else MAGIC))
        if volume is None or abs(p.volume - volume) < 1e-9:
            del self.positions[pid]
        else:
            p.volume = round(p.volume - volume, 2)


def rows_of(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
def market(monkeypatch):
    # a long at 4000.00 (SL 3996.00, TP 4004.00, R = 4.0), ticks every 500 ms
    base = 1_700_000_000_000
    rows = [(base - 300, 3999.70, 4000.00)]                    # the quote the fill executed against
    prices = [4000.4, 4001.2, 4000.5, 3998.9, 4001.9, 4002.6, 4003.4, 4004.1, 4004.3]
    for i, b in enumerate(prices):
        rows.append((base + 500 * (i + 1), b, b + 0.3))
    fake = FakeTerminal(rows)
    monkeypatch.setattr(pr, "mt5", fake)
    return fake, base


def test_recorder_captures_the_path_from_fill_to_exit(market, tmp_path):
    fake, base = market
    fake.open_position(101, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])

    fake.now_msc = base + 1600                                  # ticks at +500, +1000, +1500 have arrived
    rec.observe()
    fake.positions[101].sl = 4000.00                            # the bot moved the stop to breakeven
    fake.now_msc = base + 3100
    rec.observe()
    fake.close_position(101, base + 4000, 4004.10, reason=5)    # TP; the +4500 tick is after the exit
    fake.now_msc = base + 6000
    rec.observe()

    data = load_path(os.path.join(tmp_path, "paths", "XAUUSD_101.jsonl"))
    op, cl, tk = data["open"], data["close"], data["ticks"]
    assert op["side"] == "LONG" and op["fill_msc"] == base and op["fill_price"] == 4000.0
    assert op["sl0"] == 3996.0 and op["tp0"] == 4004.0 and op["stop_dist"] == pytest.approx(4.0)
    assert op["quote_before_fill"] == {"msc": base - 300, "bid": 3999.7, "ask": 4000.0}
    assert [t["msc"] for t in tk] == [base + 500 * i for i in range(1, 9)]     # fill..exit, nothing after
    assert [t["seq"] for t in tk] == list(range(1, 9))
    first = tk[0]
    assert first["mark"] == first["bid"] == 4000.4 and first["r"] == pytest.approx(0.1)
    assert first["upnl"] == pytest.approx(0.4) and first["spread_pts"] == pytest.approx(30.0)
    assert all(t["pid"] == 101 and t["entry"] == 4000.0 and t["sl0"] == 3996.0 and t["tp"] == 4004.0 for t in tk)
    moves = [e for e in data["events"] if e["type"] == "sl_move"]
    assert len(moves) == 1 and moves[0]["from"] == 3996.0 and moves[0]["to"] == 4000.0
    assert moves[0]["amb_after_msc"] == base + 1500 and moves[0]["amb_until_msc"] == base + 3000
    by_msc = {t["msc"]: t for t in tk}
    assert by_msc[base + 1500]["sl"] == 3996.0 and not by_msc[base + 1500]["amb"]      # before the bracket
    assert by_msc[base + 3000]["amb"] and by_msc[base + 2000]["amb"]                   # inside (1500, 3000]
    assert by_msc[base + 3500]["sl"] == 4000.0 and not by_msc[base + 3500]["amb"]      # after the bracket
    assert cl["exit_msc"] == base + 4000 and cl["exit_price"] == 4004.1 and cl["reason"] == "TP"
    assert cl["final_sl"] == 4000.0 and cl["sl_moved"] is True
    assert cl["n_ticks"] == 8 and cl["path_start_msc"] == base + 500 and cl["path_end_msc"] == base + 4000
    assert cl["complete"] is True and cl["incomplete_reasons"] == []
    assert cl["quote_after_exit"]["msc"] == base + 4500
    index = rows_of(os.path.join(tmp_path, "paths", "index.jsonl"))
    assert [r["type"] for r in index] == ["open", "close"] and all(r["pid"] == 101 for r in index)
    # the recorded path answers ordering questions directly
    assert first_reached(tk, True, 4000.0, 4.0, 0.25, -0.5) == "a"     # +0.25R (4001.0) at +1000 before -0.5R
    assert first_reached(tk, True, 4000.0, 4.0, 0.75, -0.25) == "b"    # -0.25R (3999.0) at +2000 first


def test_rows_are_paired_by_position_id_and_shorts_mark_at_the_ask(market, tmp_path):
    fake, base = market
    fake.open_position(201, True, base, 4000.00, 3996.00, 4004.00)
    fake.open_position(202, False, base + 400, 4000.30, 4004.30, 3996.30, volume=0.02)
    fake.positions[303] = SimpleNamespace(ticket=303, identifier=303, symbol="XAUUSD", magic=0, type=0, volume=0.05,
                                          price_open=4000.0, sl=0.0, tp=0.0, time=base // 1000, time_msc=base,
                                          profit=0.0, price_current=4000.0)          # manual trade: not ours
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 2100
    rec.observe()
    fake.close_position(202, base + 2600, 4001.20, reason=4)
    fake.now_msc = base + 3100
    rec.observe()

    d201 = load_path(os.path.join(tmp_path, "paths", "XAUUSD_201.jsonl"))
    d202 = load_path(os.path.join(tmp_path, "paths", "XAUUSD_202.jsonl"))
    assert not os.path.exists(os.path.join(tmp_path, "paths", "XAUUSD_303.jsonl"))
    assert d201["close"] is None and d202["close"]["pid"] == 202
    assert all(t["pid"] == 201 for t in d201["ticks"]) and all(t["pid"] == 202 for t in d202["ticks"])
    short_tick = d202["ticks"][0]                                # +500: bid 4000.4 ask 4000.7
    assert short_tick["mark"] == short_tick["ask"] == 4000.7
    assert short_tick["r"] == pytest.approx((4000.30 - 4000.70) / 4.0)
    assert short_tick["upnl"] == pytest.approx(-0.4 * 100 * 0.02)
    assert d202["close"]["label"] == "SL" and d202["close"]["exit_price"] == 4001.2


def test_partial_close_keeps_the_same_position_id(market, tmp_path):
    fake, base = market
    fake.open_position(401, True, base, 4000.00, 3996.00, 4004.00, volume=0.02)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()
    fake.close_position(401, base + 1400, 4000.50, reason=3, volume=0.01)      # half closed, still open
    fake.now_msc = base + 2100
    rec.observe()
    fake.close_position(401, base + 2400, 4000.40, reason=3)
    fake.now_msc = base + 3100
    rec.observe()
    d = load_path(os.path.join(tmp_path, "paths", "XAUUSD_401.jsonl"))
    vc = [e for e in d["events"] if e["type"] == "volume_change"]
    assert len(vc) == 1 and (vc[0]["from"], vc[0]["to"]) == (0.02, 0.01)
    assert d["close"]["pid"] == 401 and len(d["close"]["deals"]) == 2
    assert d["close"]["exit_msc"] == base + 2400
    assert d["close"]["exit_vwap"] == pytest.approx((4000.50 + 4000.40) / 2)
    # volume change seen between snapshots anchored at +1000 and +2000; the exit at +2400 comes before the next tick
    assert [(t["volume"], t["amb"]) for t in d["ticks"] if t["msc"] <= base + 1000] == [(0.02, False), (0.02, False)]
    assert [t["amb"] for t in d["ticks"] if base + 1000 < t["msc"] <= base + 2000] == [True, True]
    assert [t for t in d["ticks"] if t["msc"] > base + 2000] == []


def test_close_writes_suspend_and_a_restart_resumes_without_duplicates(market, tmp_path):
    fake, base = market
    fake.open_position(501, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1600
    rec.observe()
    rec.close()                                                  # shutdown while the position is open
    rec.close()                                                  # idempotent
    path = os.path.join(tmp_path, "paths", "XAUUSD_501.jsonl")
    assert [r["type"] for r in rows_of(path)][-1] == "suspend"

    fake.now_msc = base + 3100                                  # bot down for a while; ticks kept arriving
    rec2 = PathRecorder(str(tmp_path), [MAGIC])
    rec2.observe()
    d = load_path(path)
    mscs = [t["msc"] for t in d["ticks"]]
    assert mscs == sorted(set(mscs)) == [base + 500 * i for i in range(1, 7)]   # backfilled, no duplicates
    assert [t["seq"] for t in d["ticks"]] == list(range(1, 7))
    assert any(e["type"] == "resume" for e in d["events"])
    assert d["open"]["sl0"] == 3996.0


def test_unavailable_tick_data_is_logged_and_never_fabricated(market, tmp_path):
    fake, base = market
    fake.open_position(601, True, base, 4000.00, 3996.00, 4004.00)
    fake.fail_ticks = True
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 2100
    rec.observe()
    fake.close_position(601, base + 2500, 3996.00, reason=4)
    fake.now_msc = base + 3100
    rec.observe()
    d = load_path(os.path.join(tmp_path, "paths", "XAUUSD_601.jsonl"))
    assert d["ticks"] == []
    assert any(e["type"] == "unavailable" for e in d["events"])
    assert d["close"]["complete"] is False
    assert {"tick_fetch_unavailable", "no_ticks"} <= set(d["close"]["incomplete_reasons"])


def test_a_failed_positions_call_is_not_mistaken_for_a_close(market, tmp_path):
    fake, base = market
    fake.open_position(701, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()
    fake.fail_positions = True
    fake.now_msc = base + 2100
    rec.observe()
    d = load_path(os.path.join(tmp_path, "paths", "XAUUSD_701.jsonl"))
    assert d["close"] is None


def test_observe_and_close_never_raise(market, tmp_path):
    fake, base = market
    fake.open_position(801, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.raise_everything = True
    rec.observe()
    rec.close()


def test_a_position_closed_while_the_recorder_was_down_is_finalised(market, tmp_path):
    fake, base = market
    fake.open_position(901, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()
    rec.close()
    fake.close_position(901, base + 3200, 3999.90, reason=3)    # closed by the bot while the recorder was off
    fake.now_msc = base + 5000
    PathRecorder(str(tmp_path), [MAGIC]).observe()
    d = load_path(os.path.join(tmp_path, "paths", "XAUUSD_901.jsonl"))
    assert d["close"] is not None and d["close"]["closed_while_recorder_down"] is True
    assert [t["msc"] for t in d["ticks"]] == [base + 500 * i for i in range(1, 7)]
    index = rows_of(os.path.join(tmp_path, "paths", "index.jsonl"))
    assert [r["type"] for r in index].count("close") == 1


def test_waits_for_the_exit_deal_before_closing(market, tmp_path):
    fake, base = market
    fake.open_position(951, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()
    del fake.positions[951]                                      # gone, but the deal has not synced yet
    fake.now_msc = base + 2100
    rec.observe()
    assert load_path(os.path.join(tmp_path, "paths", "XAUUSD_951.jsonl"))["close"] is None
    fake.deals[951].append(SimpleNamespace(ticket=9999, entry=1, reason=4, time_msc=base + 1900, price=3996.0,
                                           volume=0.01, profit=-4.0, type=1, magic=MAGIC))
    fake.now_msc = base + 3100
    rec.observe()
    cl = load_path(os.path.join(tmp_path, "paths", "XAUUSD_951.jsonl"))["close"]
    assert cl is not None and cl["exit_msc"] == base + 1900 and cl["label"] == "SL"


def test_trail_and_breakeven_labels_come_from_the_final_stop():
    assert pr.exit_label(4, True, 100.0, 98.0, 98.0) == "SL"
    assert pr.exit_label(4, True, 100.0, 98.0, 100.0) == "BE"
    assert pr.exit_label(4, True, 100.0, 98.0, 100.6) == "TRAIL"
    assert pr.exit_label(4, False, 100.0, 102.0, 99.4) == "TRAIL"
    assert pr.exit_label(5, True, 100.0, 98.0, 100.6) == "TP"
    assert pr.exit_label(1, True, 100.0, 98.0, 98.0) == "manual"
    assert pr.exit_label(3, True, 100.0, 98.0, 98.0) == "bot"
    assert pr.exit_label(None, True, 100.0, 98.0, 98.0) == "unknown"


def test_a_failed_write_is_retried_without_losing_or_duplicating_ticks(market, tmp_path, monkeypatch):
    fake, base = market
    fake.open_position(961, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()                                                # ticks +500, +1000 written
    real_write = rec._write
    failures = {"left": 1}

    def flaky(st, rows):
        if failures["left"] and any(r["type"] == "tick" for r in rows):
            failures["left"] -= 1
            raise OSError("disk full")
        real_write(st, rows)

    monkeypatch.setattr(rec, "_write", flaky)
    fake.positions[961].sl = 4000.00
    fake.now_msc = base + 2100
    rec.observe()                                                # this batch fails to write
    fake.now_msc = base + 3100
    rec.observe()                                                # retried from the same point
    d = load_path(os.path.join(tmp_path, "paths", "XAUUSD_961.jsonl"))
    assert [t["msc"] for t in d["ticks"]] == [base + 500 * i for i in range(1, 7)]
    assert [t["seq"] for t in d["ticks"]] == list(range(1, 7))
    assert len([e for e in d["events"] if e["type"] == "sl_move"]) == 1


def test_a_close_is_written_once_even_if_the_index_write_fails(market, tmp_path, monkeypatch):
    fake, base = market
    fake.open_position(971, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()
    real_index = rec._index
    monkeypatch.setattr(rec, "_index", lambda row: (_ for _ in ()).throw(OSError("locked"))
                        if row["type"] == "close" else real_index(row))
    fake.close_position(971, base + 1400, 3996.00, reason=4)
    fake.now_msc = base + 2100
    rec.observe()
    rec.observe()
    rows = rows_of(os.path.join(tmp_path, "paths", "XAUUSD_971.jsonl"))
    assert [r["type"] for r in rows].count("close") == 1


def test_final_stop_comes_from_the_exit_deal_when_the_move_was_never_observed(market, tmp_path):
    """E.g. the stop trailed while the recorder was down: the broker's '[sl X]' exit comment is authoritative."""
    fake, base = market
    fake.open_position(981, True, base, 4000.00, 3996.00, 4004.00)
    rec = PathRecorder(str(tmp_path), [MAGIC])
    fake.now_msc = base + 1100
    rec.observe()                                                # only ever saw the initial stop
    fake.close_position(981, base + 1900, 4000.50, reason=4)
    fake.deals[981][-1].comment = "[sl 4000.50]"
    fake.now_msc = base + 2600
    rec.observe()
    cl = load_path(os.path.join(tmp_path, "paths", "XAUUSD_981.jsonl"))["close"]
    assert cl["final_sl"] == 4000.5 and cl["final_sl_source"] == "exit_deal_comment"
    assert cl["final_sl_observed"] == 3996.0
    assert cl["label"] == "TRAIL" and cl["sl_moved"] is True


def test_parse_exit_stop_comment():
    assert pr.stop_from_comment("[sl 4351.43]") == ("sl", 4351.43)
    assert pr.stop_from_comment("[tp 4350.89]") == ("tp", 4350.89)
    assert pr.stop_from_comment("") is None and pr.stop_from_comment(None) is None
    assert pr.stop_from_comment("AlgoBot-XAUUSD") is None
