"""London-open range breakout, pure functions (no MT5).

Box = high/low of the server day's bars between LDN_BOX_START_HOUR and LDN_BOX_END_HOUR.
Signal = the first closed bar of the day inside [LDN_BOX_END_HOUR, LDN_WINDOW_END_HOUR) whose close
is beyond an edge by the buffer. Exactly one such bar exists per day, so a restart cannot re-enter.
"""
import numpy as np
import pandas as pd

import config
from strategy import Levels, build_levels, trend_allows
from technicals import compute_indicators, compute_trend, attach_trend


def pip_size(point: float, digits: int) -> float:
    """One pip in price units: 10 points on 3- and 5-digit symbols, one point otherwise."""
    return point * 10 if digits in (3, 5) else point


def add_box_columns(df: pd.DataFrame, buffer_price: float) -> pd.DataFrame:
    """Add box_high, box_low, in_window, first_break, box_break. Edges are NaN on days without box bars."""
    t = df["time"]
    day = t.dt.date
    hour = t.dt.hour + t.dt.minute / 60
    in_box = (hour >= config.LDN_BOX_START_HOUR) & (hour < config.LDN_BOX_END_HOUR)
    in_window = (hour >= config.LDN_BOX_END_HOUR) & (hour < config.LDN_WINDOW_END_HOUR)
    df["box_high"] = df["high"].where(in_box).groupby(day).transform("max")
    df["box_low"] = df["low"].where(in_box).groupby(day).transform("min")
    df["in_window"] = in_window
    ok = in_window & df["box_high"].notna() & df["box_low"].notna()
    if config.LDN_MAX_BOX_ATR:
        ok &= (df["box_high"] - df["box_low"]) <= config.LDN_MAX_BOX_ATR * df["atr"]
    up = ok & (df["close"] > df["box_high"] + buffer_price)
    down = ok & (df["close"] < df["box_low"] - buffer_price)
    any_break = up | down
    first = any_break & (any_break.groupby(day).cumsum() == 1)
    df["first_break"] = first
    df["box_break"] = np.where(first & up, "BUY", np.where(first & down, "SELL", ""))
    return df


def london_signal(bar) -> str | None:
    """The day's first break, gated by the H1 trend when LDN_TREND_FILTER is on."""
    side = bar.get("box_break") or ""
    if side not in ("BUY", "SELL"):
        return None
    return side if trend_allows(side, bar["close"], bar.get("trend_ema"), enabled=config.LDN_TREND_FILTER) else None


def london_levels(side: str, ask: float, bid: float, bar) -> Levels | None:
    """Stop by LDN_SL_MODE, target at LDN_TP_R times the stop distance. None when no valid stop exists."""
    atr = float(bar["atr"])
    if config.LDN_SL_MODE == "atr":
        return build_levels(side, ask, bid, atr, config.LDN_SL_ATR, config.LDN_SL_ATR * config.LDN_TP_R)
    hi, lo = float(bar["box_high"]), float(bar["box_low"])
    if np.isnan(hi) or np.isnan(lo):
        return None
    entry = ask if side == "BUY" else bid
    if config.LDN_SL_MODE == "box_opposite":
        sl = lo if side == "BUY" else hi
    else:                                               # "box_mid"
        sl = (hi + lo) / 2
    dist = (entry - sl) if side == "BUY" else (sl - entry)
    if not dist > 0:
        return None
    tp = entry + config.LDN_TP_R * dist if side == "BUY" else entry - config.LDN_TP_R * dist
    return Levels(side, entry, sl, tp, dist)


def london_analyse(df: pd.DataFrame, htf=None, info=None) -> pd.DataFrame:
    """Indicators + box columns (+ H1 EMA when the series is given). `info` supplies point/digits."""
    pip = pip_size(info.point, info.digits) if info is not None else 0.0001
    df = compute_indicators(df)
    df = add_box_columns(df, config.LDN_BUFFER_PIPS * pip)
    if htf is not None:
        df = attach_trend(df, compute_trend(htf))
    return df
