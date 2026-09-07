"""The scalp-test instance profile (branch scalp-test): what makes it different from the evaluation bot."""
import MetaTrader5 as mt5

import config
from engines import build_engines


def test_gold_only_on_m1_with_its_own_magic():
    assert config.SYMBOLS == ["XAUUSD"]
    assert config.TIMEFRAME == mt5.TIMEFRAME_M1
    assert config.MAGIC_NUMBER == 998811 != 998877


def test_only_the_scalper_engine_runs():
    assert [e.name for e in build_engines()] == ["scalper"]


def test_filters_are_relaxed_for_signal_frequency():
    assert config.CANDLE_MODE == "off"
    assert not config.TREND_FILTER_ENABLED and not config.NEWS_FILTER_ENABLED
    assert (config.RSI_OVERSOLD, config.RSI_OVERBOUGHT) == (35, 65)
    assert config.spread_limit("XAUUSD") == 100


def test_breakers_allow_many_test_trades_but_still_exist():
    assert config.MAX_TRADES_PER_DAY >= 50
    assert config.MAX_CONSECUTIVE_LOSSES >= 20
    assert 100.0 <= config.MAX_DAILY_LOSS_USD <= 300.0
    assert config.RISK_USD_PER_TRADE <= 10.0


def test_instance_cannot_collide_with_the_evaluation_bot():
    assert config.WEB_PORT != 8080
    assert config.PAGES_PUBLISH_ENABLED is False
    assert config.MANAGE_POSITIONS is True
