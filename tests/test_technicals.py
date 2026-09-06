import numpy as np
import pandas as pd

import config
from technicals import compute_indicators, compute_trend, attach_trend


def test_indicators_columns_and_warmup():
    n = 60
    df = pd.DataFrame({
        "time": pd.date_range("2026-09-01", periods=n, freq="5min"),
        "open": np.linspace(100, 110, n), "high": np.linspace(101, 111, n),
        "low": np.linspace(99, 109, n), "close": np.linspace(100, 110, n),
    })
    out = compute_indicators(df)
    for c in ("atr", "sma", "upper_band", "lower_band", "rsi"):
        assert c in out
    assert np.isnan(out["atr"].iloc[config.ATR_PERIOD - 2])
    assert not np.isnan(out["atr"].iloc[-1])
    assert out["rsi"].iloc[-1] > 90                        # monotonic rise


def test_attach_trend_uses_previous_closed_htf_bar():
    htf = pd.DataFrame({"time": pd.date_range("2026-09-01 00:00", periods=4, freq="1h"),
                        "close": [1.0, 2.0, 3.0, 4.0]})
    htf = compute_trend(htf)
    ema = htf["trend_ema"].tolist()
    ltf = pd.DataFrame({"time": pd.to_datetime([
        "2026-09-01 01:00", "2026-09-01 01:30", "2026-09-01 02:05", "2026-09-01 03:55"])})
    out = attach_trend(ltf, htf)
    # bars inside the 01:00 H1 candle see the EMA of the 00:00 candle, etc.
    got = out["trend_ema"].tolist()
    assert got[0] == ema[0]
    assert got[1] == ema[0]
    assert got[2] == ema[1]
    assert got[3] == ema[2]
