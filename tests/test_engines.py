"""Engine profiles are plain data built from config; the scalper profile mirrors today's settings."""
import pandas as pd
import pytest

import config
from engines import Engine, scalper_engine, build_engines, engine_names, scalper_analyse, scalper_levels
from strategy import generate_signal


def test_scalper_profile_mirrors_config(monkeypatch):
    monkeypatch.setattr(config, "RISK_USD_PER_TRADE", 7.5)
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 3)
    e = scalper_engine()
    assert isinstance(e, Engine)
    assert e.name == "scalper" and e.magic == config.MAGIC_NUMBER and e.comment == "AlgoBot"
    assert e.symbols == tuple(config.SYMBOLS)
    assert e.timeframe == config.TIMEFRAME and e.lookback == config.RATES_LOOKBACK
    assert e.trend_filter == config.TREND_FILTER_ENABLED
    assert e.risk_usd == 7.5 and e.max_trades_per_day == 3
    assert e.max_consecutive_losses == config.MAX_CONSECUTIVE_LOSSES
    assert e.manage == config.MANAGE_POSITIONS
    assert (e.breakeven_atr, e.trail_atr) == (config.BREAKEVEN_ATR, config.TRAIL_ATR)
    assert e.signal is generate_signal and e.analyse is scalper_analyse and e.levels is scalper_levels


def test_profiles_are_immutable():
    e = scalper_engine()
    with pytest.raises(Exception):
        e.magic = 1


def test_build_engines_is_scalper_only_by_default(monkeypatch):
    monkeypatch.setattr(config, "LDN_ENABLED", False, raising=False)
    names = [e.name for e in build_engines()]
    assert names == ["scalper"]
    assert engine_names(build_engines()) == {config.MAGIC_NUMBER: "scalper"}


def test_scalper_analyse_attaches_trend_only_with_htf():
    df = pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=60, freq="5min"),
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    out = scalper_analyse(df.copy())
    assert "atr" in out and "rsi" in out and "trend_ema" not in out
    htf = pd.DataFrame({"time": pd.date_range("2026-09-01", periods=300, freq="1h"), "close": 100.0})
    out = scalper_analyse(df.copy(), htf)
    assert "trend_ema" in out


def test_scalper_levels_use_bar_atr_and_config_multipliers():
    lv = scalper_levels("BUY", 100.0, 99.9, {"atr": 2.0})
    assert lv.entry == 100.0
    assert lv.sl == pytest.approx(100.0 - 2.0 * config.SL_ATR_MULTIPLIER)
