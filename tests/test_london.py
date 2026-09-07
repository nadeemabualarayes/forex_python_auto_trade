"""London-open range breakout: box edges, first break per day, levels. Pure, no MT5."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import config
from london import pip_size, add_box_columns, london_signal, london_levels, london_analyse


@pytest.fixture(autouse=True)
def ldn_defaults(monkeypatch):
    for k, v in dict(LDN_BOX_START_HOUR=0, LDN_BOX_END_HOUR=10, LDN_WINDOW_END_HOUR=14, LDN_BUFFER_PIPS=0.0,
                     LDN_MAX_BOX_ATR=0.0, LDN_TREND_FILTER=False, LDN_SL_MODE="atr", LDN_SL_ATR=1.5,
                     LDN_TP_R=2.0).items():
        monkeypatch.setattr(config, k, v, raising=False)


def day_frame(day="2026-09-07", box=(1.1000, 1.1020), after=None, step_min=5):
    """One server day of M5 bars: the box hours trade inside `box`; `after` maps hour -> close."""
    times = pd.date_range(f"{day} 00:00", periods=24 * 60 // step_min, freq=f"{step_min}min")
    lo, hi = box
    closes = []
    for t in times:
        h = t.hour + t.minute / 60
        if h < 10:
            closes.append(lo + (hi - lo) * ((t.minute // 5) % 2))       # alternate within the box
        else:
            closes.append((after or {}).get(t.hour, (lo + hi) / 2))
    df = pd.DataFrame({"time": times, "close": closes})
    df["open"] = df["close"]
    df["high"] = df["close"] + 0.0001
    df["low"] = df["close"] - 0.0001
    df["atr"] = 0.0003
    return df


def test_pip_size():
    assert pip_size(0.00001, 5) == pytest.approx(0.0001)
    assert pip_size(0.001, 3) == pytest.approx(0.01)
    assert pip_size(0.01, 2) == pytest.approx(0.01)


def test_box_edges_and_single_first_break():
    df = add_box_columns(day_frame(after={10: 1.1030, 11: 1.1035, 12: 1.0990}), buffer_price=0.0)
    assert not df.loc[df["time"].dt.hour < 10, "first_break"].any()   # never fires inside the box hours
    window = df[df["time"].dt.hour >= 10]
    assert window["box_high"].iloc[0] == pytest.approx(1.1021)      # box high includes the bar wick
    assert window["box_low"].iloc[0] == pytest.approx(1.0999)
    breaks = df[df["first_break"]]
    assert len(breaks) == 1 and breaks.iloc[0]["time"] == pd.Timestamp("2026-09-07 10:00")
    assert breaks.iloc[0]["box_break"] == "BUY"
    assert (df.loc[df["time"].dt.hour == 12, "box_break"] == "").all()   # later reverse break ignored


def test_buffer_and_window_end_are_respected():
    df = add_box_columns(day_frame(after={10: 1.1022, 13: 1.1040, 14: 1.1050}), buffer_price=0.0005)
    breaks = df[df["first_break"]]
    assert len(breaks) == 1 and breaks.iloc[0]["time"].hour == 13      # 10:00 close is inside the buffer
    late = add_box_columns(day_frame(after={15: 1.1050}), buffer_price=0.0)
    assert not late["first_break"].any()                                # window closed at 14:00


def test_width_filter_skips_wide_boxes(monkeypatch):
    monkeypatch.setattr(config, "LDN_MAX_BOX_ATR", 3.0)               # 3 x 0.0003 = 0.0009 < box 0.0022
    df = add_box_columns(day_frame(after={10: 1.1030}), buffer_price=0.0)
    assert not df["first_break"].any()


def test_day_with_no_box_bars_leaves_edges_nan_and_never_breaks():
    # Bars start at 10:30: none fall in the [0, 10) box hours, so the day has no box at all.
    times = pd.date_range("2026-09-07 10:30", "2026-09-07 23:55", freq="5min")
    close = pd.Series(5.0, index=range(len(times)))          # far above any plausible box
    df = pd.DataFrame({"time": times, "close": close})
    df["open"] = df["close"]
    df["high"] = df["close"] + 0.0001
    df["low"] = df["close"] - 0.0001
    df["atr"] = 0.0003
    out = add_box_columns(df, buffer_price=0.0)
    assert out["box_high"].isna().all()
    assert out["box_low"].isna().all()
    assert not out["first_break"].any()


def test_first_break_is_per_day():
    a = day_frame("2026-09-07", after={10: 1.1030})
    b = day_frame("2026-09-08", after={11: 1.0980})
    df = add_box_columns(pd.concat([a, b], ignore_index=True), buffer_price=0.0)
    assert list(df.loc[df["first_break"], "box_break"]) == ["BUY", "SELL"]


def test_signal_gates_on_engine_trend_flag(monkeypatch):
    bar = {"box_break": "BUY", "close": 1.1030, "trend_ema": 1.1100}
    assert london_signal(bar) == "BUY"
    monkeypatch.setattr(config, "LDN_TREND_FILTER", True)
    assert london_signal(bar) is None
    assert london_signal({"box_break": "", "close": 1.1, "trend_ema": 1.0}) is None


def test_levels_atr_mode():
    lv = london_levels("BUY", 1.1030, 1.1028, {"atr": 0.0004, "box_high": 1.1020, "box_low": 1.1000})
    assert lv.entry == 1.1030 and lv.sl == pytest.approx(1.1024) and lv.tp == pytest.approx(1.1042)
    assert lv.sl_dist == pytest.approx(0.0006)


def test_levels_box_modes(monkeypatch):
    bar = {"atr": 0.0004, "box_high": 1.1020, "box_low": 1.1000}
    monkeypatch.setattr(config, "LDN_SL_MODE", "box_opposite")
    lv = london_levels("SELL", 1.0992, 1.0990, bar)
    assert lv.entry == 1.0990 and lv.sl == pytest.approx(1.1020) and lv.tp == pytest.approx(1.0990 - 2 * 0.0030)
    monkeypatch.setattr(config, "LDN_SL_MODE", "box_mid")
    lv = london_levels("BUY", 1.1030, 1.1028, bar)
    assert lv.sl == pytest.approx(1.1010) and lv.sl_dist == pytest.approx(0.0020)
    assert london_levels("BUY", 1.1005, 1.1003, bar) is None            # entry below the midpoint
    assert london_levels("BUY", 1.1030, 1.1028, {"atr": 0.0004, "box_high": np.nan, "box_low": np.nan}) is None


def test_analyse_builds_columns_with_symbol_pip():
    from types import SimpleNamespace
    raw = day_frame(after={10: 1.1030}).drop(columns=["atr"])
    raw["tick_volume"], raw["spread"], raw["real_volume"] = 1, 3, 0
    out = london_analyse(raw, None, SimpleNamespace(point=0.00001, digits=5))
    for col in ("atr", "box_high", "box_low", "first_break", "box_break"):
        assert col in out
