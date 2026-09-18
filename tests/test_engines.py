"""Engine profiles are plain data built from config; the scalper profile mirrors today's settings."""
import pandas as pd
import pytest

import config
from engines import Engine, scalper_engine, build_engines, engine_names, scalper_analyse, scalper_levels
from strategy import generate_signal


def test_scalper_profile_mirrors_config(monkeypatch):
    monkeypatch.setattr(config, "EXIT_MODE", "atr")
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


def test_usd_exit_mode_swaps_in_the_dollar_adapters_and_budgets_the_stop(monkeypatch):
    from engines import dollar_analyse, dollar_levels
    monkeypatch.setattr(config, "EXIT_MODE", "usd")
    monkeypatch.setattr(config, "EXIT_SL_USD", 2.0)
    monkeypatch.setattr(config, "RISK_USD_PER_TRADE", 5.0)
    e = scalper_engine()
    assert e.analyse is dollar_analyse and e.levels is dollar_levels and e.signal is generate_signal
    assert e.risk_usd == 2.0                        # the dollar stop IS the risk budget: minimum lot only


def test_dollar_analyse_prices_a_price_move_for_the_levels(monkeypatch):
    import engines
    from types import SimpleNamespace
    info = SimpleNamespace(name="XAUUSD", point=0.01, trade_stops_level=20)
    monkeypatch.setattr(engines, "usd_per_price_unit", lambda symbol, i: 1.0 if symbol == "XAUUSD" else None)
    df = pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=60, freq="1min"),
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    out = engines.dollar_analyse(df.copy(), None, info)
    assert "atr" in out and "rsi" in out
    bar = out.iloc[-2]
    assert bar["usd_per_unit"] == 1.0 and bar["point"] == 0.01 and bar["stops_dist"] == pytest.approx(0.20)


def test_dollar_analyse_without_a_terminal_price_leaves_the_move_unpriced(monkeypatch):
    import engines
    monkeypatch.setattr(engines, "usd_per_price_unit", lambda symbol, i: None)
    df = pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=60, freq="1min"),
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    bar = engines.dollar_analyse(df.copy(), None, None).iloc[-2]
    assert pd.isna(bar["usd_per_unit"])
    assert engines.dollar_levels("BUY", 100.0, 99.9, bar) is None


def test_dollar_levels_use_the_bar_pricing_and_config_amounts(monkeypatch):
    from engines import dollar_levels
    monkeypatch.setattr(config, "EXIT_SL_USD", 2.0)
    monkeypatch.setattr(config, "EXIT_TP_USD", 1.5)
    lv = dollar_levels("SELL", 4300.50, 4300.18, {"usd_per_unit": 1.0, "point": 0.01, "stops_dist": 0.0})
    assert lv.entry == 4300.18 and lv.sl == pytest.approx(4302.18) and lv.tp == pytest.approx(4298.68)


def test_scalper_levels_use_bar_atr_and_config_multipliers():
    lv = scalper_levels("BUY", 100.0, 99.9, {"atr": 2.0})
    assert lv.entry == 100.0
    assert lv.sl == pytest.approx(100.0 - 2.0 * config.SL_ATR_MULTIPLIER)


def test_london_profile_reads_its_own_config(monkeypatch):
    from engines import london_engine
    from london import london_analyse, london_signal, london_levels
    monkeypatch.setattr(config, "LDN_RISK_USD", 3.0, raising=False)
    e = london_engine()
    assert e.name == "london" and e.magic == config.LDN_MAGIC_NUMBER and e.comment == "LDN"
    assert e.symbols == tuple(config.LDN_SYMBOLS) and e.timeframe == config.LDN_TIMEFRAME
    assert e.lookback == config.LDN_RATES_LOOKBACK and e.trend_filter == config.LDN_TREND_FILTER
    assert e.analyse is london_analyse and e.signal is london_signal and e.levels is london_levels
    assert e.risk_usd == 3.0 and e.max_trades_per_day == config.LDN_MAX_TRADES_PER_DAY
    assert e.max_consecutive_losses == config.LDN_MAX_CONSECUTIVE_LOSSES
    assert (e.manage, e.breakeven_atr, e.trail_atr) == (config.LDN_MANAGE_POSITIONS, config.LDN_BREAKEVEN_ATR, config.LDN_TRAIL_ATR)


def test_build_engines_includes_london_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "LDN_ENABLED", True, raising=False)
    engines = build_engines()
    assert [e.name for e in engines] == ["scalper", "london"]
    assert engine_names(engines) == {config.MAGIC_NUMBER: "scalper", config.LDN_MAGIC_NUMBER: "london"}
