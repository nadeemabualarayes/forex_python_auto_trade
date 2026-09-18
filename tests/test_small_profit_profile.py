"""The small-profit instance profile (branch small-profit): frequent gold entries, fixed-dollar exits, small losses."""
import MetaTrader5 as mt5

import config
from engines import build_engines, dollar_levels


def test_gold_only_on_m1_with_its_own_magic():
    assert config.SYMBOLS == ["XAUUSD"]
    assert config.TIMEFRAME == mt5.TIMEFRAME_M1
    assert config.MAGIC_NUMBER not in (998877, 998888, 998811)     # evaluation scalper, london, scalp-test


def test_only_the_scalper_engine_runs_with_dollar_exits():
    engines = build_engines()
    assert [e.name for e in engines] == ["scalper"]
    assert config.EXIT_MODE == "usd" and engines[0].levels is dollar_levels


def test_losses_are_small_and_no_bigger_than_the_research_envelope():
    assert 0 < config.EXIT_TP_USD <= config.EXIT_SL_USD <= 2.0
    assert build_engines()[0].risk_usd == config.EXIT_SL_USD
    assert config.MANAGE_POSITIONS is False                          # the broker-side TP/SL is the whole exit


def test_entries_stay_frequent_and_may_stack():
    assert config.CANDLE_MODE == "off"
    assert not config.TREND_FILTER_ENABLED and not config.NEWS_FILTER_ENABLED
    assert (config.RSI_OVERSOLD, config.RSI_OVERBOUGHT) == (35, 65)
    assert config.MAX_TRADES_PER_DAY >= 100
    assert 2 <= config.MAX_OPEN_POSITIONS <= 5


def test_the_two_entry_filters_that_survived_both_halves_are_on():
    assert config.SESSION_BLOCKED_HOURS == (7, 8, 9, 10, 11)
    assert config.spread_limit("XAUUSD") == 45


def test_a_bad_day_is_cut_short():
    worst_cluster = config.MAX_OPEN_POSITIONS * config.EXIT_SL_USD
    assert worst_cluster <= 10.0
    assert config.MAX_DAILY_LOSS_USD <= 20.0
    assert config.MAX_CONSECUTIVE_LOSSES <= 10


def test_instance_cannot_collide_with_the_evaluation_bot():
    assert config.WEB_PORT != 8080
    assert config.PAGES_PUBLISH_ENABLED is False
