"""Japanese candlestick pattern detection on a closed-bar OHLC frame (pure pandas, no MT5).

add_patterns(df) appends two string columns, `bull_pattern` and `bear_pattern`, holding the
name of the reversal pattern completed on each bar ("" when none). Multi-bar patterns are
attributed to their final bar, so the live bot can act on the last closed candle.

Definitions (body = |close-open|, rng = high-low, shadows measured from the body):
  doji                 body <= 10% of range
  hammer / hanging_man lower shadow >= 2x body and >= 50% of range, upper shadow <= 20% of range
  inverted_hammer / shooting_star   mirror image (long upper shadow)
  bullish/bearish_engulfing  opposite-colour body that covers the previous body
  bullish/bearish_harami     body inside the previous (large) body; a doji inside = harami cross
  piercing / dark_cloud      opens beyond the previous close, closes past the previous midpoint
  morning/evening_star       large body, small body, then a body closing past the first midpoint
  tweezer_bottom/top         two opposite-colour bars with equal lows / highs (within 10% ATR)
  three_white_soldiers / three_black_crows   three same-colour bars with rising / falling opens and closes
"""
import numpy as np
import pandas as pd

BULL_PATTERNS = ("bullish_engulfing", "morning_star", "piercing", "hammer", "inverted_hammer",
                 "bullish_harami", "tweezer_bottom", "three_white_soldiers", "doji")
BEAR_PATTERNS = ("bearish_engulfing", "evening_star", "dark_cloud", "shooting_star", "hanging_man",
                 "bearish_harami", "tweezer_top", "three_black_crows", "doji")

DOJI_BODY = 0.10            # body / range
PIN_SHADOW_BODY = 2.0       # long shadow / body
PIN_SHADOW_RANGE = 0.50     # long shadow / range
PIN_OTHER_SHADOW = 0.20     # short shadow / range
STAR_BODY = 0.30            # middle star body / first body
TWEEZER_ATR = 0.10          # equal-extreme tolerance in ATR
AVG_BODY_WINDOW = 10


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    bull, bear = c > o, c < o
    avg_body = body.rolling(AVG_BODY_WINDOW, min_periods=3).mean()
    atr = df["atr"].astype(float) if "atr" in df else rng.rolling(14).mean()

    o1, c1, h1, l1, body1 = (s.shift(1) for s in (o, c, h, l, body))
    o2, c2, body2 = (s.shift(2) for s in (o, c, body))
    bull1, bear1, bull2, bear2 = (s.shift(k).fillna(False).astype(bool)
                                  for s, k in ((bull, 1), (bear, 1), (bull, 2), (bear, 2)))

    doji = body <= DOJI_BODY * rng
    pin_low = ((lower >= PIN_SHADOW_BODY * body) & (lower >= PIN_SHADOW_RANGE * rng)
               & (upper <= PIN_OTHER_SHADOW * rng))
    pin_high = ((upper >= PIN_SHADOW_BODY * body) & (upper >= PIN_SHADOW_RANGE * rng)
                & (lower <= PIN_OTHER_SHADOW * rng))
    engulf_bull = bear1 & bull & (o <= c1) & (c >= o1) & (body > body1)
    engulf_bear = bull1 & bear & (o >= c1) & (c <= o1) & (body > body1)
    big1 = body1 >= avg_body
    harami_bull = bear1 & big1 & (np.maximum(o, c) <= o1) & (np.minimum(o, c) >= c1) & (body < body1)
    harami_bear = bull1 & big1 & (np.maximum(o, c) <= c1) & (np.minimum(o, c) >= o1) & (body < body1)
    mid1 = (o1 + c1) / 2
    piercing = bear1 & bull & (o < c1) & (c > mid1) & (c < o1)
    dark_cloud = bull1 & bear & (o > c1) & (c < mid1) & (c > o1)
    mid2 = (o2 + c2) / 2
    morning = bear2 & (body2 >= avg_body.shift(2)) & (body1 <= STAR_BODY * body2) & bull & (c > mid2)
    evening = bull2 & (body2 >= avg_body.shift(2)) & (body1 <= STAR_BODY * body2) & bear & (c < mid2)
    tol = TWEEZER_ATR * atr
    tweezer_bottom = bear1 & bull & ((l - l1).abs() <= tol)
    tweezer_top = bull1 & bear & ((h - h1).abs() <= tol)
    min_body = 0.5 * avg_body
    soldiers = (bull & bull1 & bull2 & (c > c1) & (c1 > c2) & (o > o1) & (o1 > o2)
                & (body >= min_body) & (body1 >= min_body))
    crows = (bear & bear1 & bear2 & (c < c1) & (c1 < c2) & (o < o1) & (o1 < o2)
             & (body >= min_body) & (body1 >= min_body))

    def pick(conds, names):
        conds = [cnd.fillna(False).astype(bool).values for cnd in conds]
        return np.select(conds, names, default="")

    df["bull_pattern"] = pick([engulf_bull, morning, piercing, pin_low, pin_high, harami_bull,
                               tweezer_bottom, soldiers, doji], BULL_PATTERNS)
    df["bear_pattern"] = pick([engulf_bear, evening, dark_cloud, pin_high, pin_low, harami_bear,
                               tweezer_top, crows, doji], BEAR_PATTERNS)
    return df
