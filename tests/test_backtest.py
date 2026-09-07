import pandas as pd
import pytest

import config
from backtest import resolve_exit, run_backtest, summarize, SimTrade


def frame(rows):
    """rows: list of (open, high, low, close)."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = pd.date_range("2026-09-07 08:00", periods=len(df), freq="5min")   # Monday, in session
    return df


class TestResolveExit:
    def test_buy_hits_tp(self):
        df = frame([(100, 101, 99, 100), (100, 106, 99.5, 105)])
        assert resolve_exit(df, 0, "BUY", 97, 105.5) == (1, 105.5, "TP")

    def test_buy_sl_wins_ties(self):
        df = frame([(100, 106, 96, 100)])
        assert resolve_exit(df, 0, "BUY", 97, 105.5) == (0, 97, "SL")

    def test_sell(self):
        df = frame([(100, 101, 99, 100), (100, 100.5, 94, 95)])
        assert resolve_exit(df, 0, "SELL", 103, 94.5) == (1, 94.5, "TP")

    def test_never_closed(self):
        df = frame([(100, 101, 99, 100)])
        assert resolve_exit(df, 0, "BUY", 90, 110) is None


@pytest.fixture
def no_filters(monkeypatch):
    monkeypatch.setattr(config, "TREND_FILTER_ENABLED", False)
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)


def test_run_backtest_end_to_end(no_filters):
    # bar 1 is a BUY signal (close on lower band, rsi 20); entry at bar 2 open = 100; atr 2 -> sl 97 tp 106
    df = frame([(100, 101, 99, 100), (99, 99.5, 88, 89), (100, 101, 99, 100), (100, 107, 99.5, 106)])
    df["atr"], df["lower_band"], df["upper_band"] = 2.0, 90.0, 110.0
    df["rsi"] = [50, 20, 50, 50]
    trades = run_backtest(df, "X", spread_price=0.0, tick_size=0.01, tick_value=0.1, lot_fn=lambda d: 0.1)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "BUY" and t.entry == 100 and t.reason == "TP"
    assert t.pnl == pytest.approx((106 - 100) / 0.01 * 0.1 * 0.1)


def test_daily_trade_cap_respected(no_filters, monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 1)
    monkeypatch.setattr(config, "MAX_CONSECUTIVE_LOSSES", 99)
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 1e9)
    rows = [(100, 101, 99, 100), (99, 99.5, 88, 89), (100, 107, 99.5, 106)] * 3
    df = frame(rows)
    df["atr"], df["lower_band"], df["upper_band"] = 2.0, 90.0, 110.0
    df["rsi"] = [50, 20, 50] * 3
    trades = run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1)
    assert len(trades) == 1


def test_summary():
    ts = [SimTrade("X", "BUY", None, 1, 0, 2, 0.1, pnl=p, reason=r)
          for p, r in [(5, "TP"), (-3, "SL"), (-3, "SL"), (7, "TP")]]
    s = summarize(ts)
    assert s["trades"] == 4 and s["wins"] == 2 and s["win_rate"] == 50.0
    assert s["net"] == 6 and s["max_drawdown"] == 6 and s["profit_factor"] == 2.0
    assert summarize([]) == {"trades": 0}


def test_resolve_exit_trails_stop_into_profit(monkeypatch):
    monkeypatch.setattr(config, "BREAKEVEN_ATR", 1.0)
    monkeypatch.setattr(config, "TRAIL_ATR", 1.0)
    # entry 100, atr 1: bar0 closes at 102 (2 ATR up -> SL trails to 101), bar1 drops to 100.5 -> trailed stop hit
    df = pd.DataFrame({"open": [100, 102], "high": [102.5, 102.2], "low": [99.5, 100.5],
                       "close": [102, 100.8], "atr": [1.0, 1.0]})
    assert resolve_exit(df, 0, "BUY", 97, 110) is None
    assert resolve_exit(df, 0, "BUY", 97, 110, entry=100, manage=True) == (1, 101.0, "TRAIL")


def test_format_report_lists_each_symbol_and_total():
    from backtest import format_report
    gold = summarize([SimTrade("XAUUSD", "BUY", None, 1, 0, 2, 0.1, pnl=5, reason="TP"),
                      SimTrade("XAUUSD", "SELL", None, 1, 2, 0, 0.1, pnl=-3, reason="SL")])
    text = format_report(180, {"XAUUSD": gold, "XAGUSD": summarize([])})
    assert "BACKTEST" in text and "180" in text
    assert "XAUUSD" in text and "XAGUSD" in text
    assert "no trades" in text
    assert "+2.00" in text                      # gold net and the total
    assert "50.0%" in text and "PF 1.67" in text


def test_history_spread_falls_back_to_current_when_bars_carry_none():
    from backtest import history_spread
    with_data = pd.DataFrame({"spread": [3, 4, 5]})
    assert history_spread(with_data, fallback_points=7, point=0.00001) == pytest.approx(0.00004)
    zeros = pd.DataFrame({"spread": [0, 0, 0]})
    assert history_spread(zeros, fallback_points=7, point=0.00001) == pytest.approx(0.00007)
    assert history_spread(pd.DataFrame({"close": [1.0]}), fallback_points=7, point=0.00001) == pytest.approx(0.00007)


def test_run_spread_override_wins_over_history():
    from backtest import run_spread
    with_data = pd.DataFrame({"spread": [3, 4, 5]})
    assert run_spread(with_data, fallback_points=7, point=0.00001, override_points=20) == pytest.approx(0.0002)
    assert run_spread(with_data, fallback_points=7, point=0.00001, override_points=None) == pytest.approx(0.00004)
    assert run_spread(with_data, fallback_points=7, point=0.00001) == pytest.approx(0.00004)


def test_run_backtest_accepts_signal_and_levels_callables(no_filters):
    from strategy import Levels
    df = frame([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 107, 99.5, 106)])
    df["atr"] = 2.0
    sig = lambda bar: "BUY" if bar["time"].minute == 5 else None            # bar 1 only
    lv = lambda side, ask, bid, bar: Levels(side, ask, ask - 3.0, ask + 6.0, 3.0)
    trades = run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, signal=sig, levels=lv)
    assert len(trades) == 1 and trades[0].tp == 106 and trades[0].reason == "TP"
    none = run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, signal=sig, levels=lambda *a: None)
    assert none == []


def test_engine_cap_and_streak_override_config(no_filters, monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 99)
    rows = [(100, 101, 99, 100), (99, 99.5, 88, 89), (100, 107, 99.5, 106)] * 3
    df = frame(rows)
    df["atr"], df["lower_band"], df["upper_band"] = 2.0, 90.0, 110.0
    df["rsi"] = [50, 20, 50] * 3
    assert len(run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, max_trades_per_day=1)) == 1


def test_format_report_names_the_engine():
    from backtest import format_report
    assert "<b>BACKTEST london</b>" in format_report(30, {}, engine_name="london")
    assert "<b>BACKTEST scalper</b>" in format_report(30, {})


def test_format_report_with_engine_profile_shows_its_own_settings():
    from backtest import format_report
    from engines import london_engine
    text = format_report(30, {}, engine=london_engine())
    lines = text.splitlines()
    assert "<b>BACKTEST london</b>" in lines[0]
    assert "candles=" not in lines[1]
    assert "trend=True" in lines[1] and "manage=False" in lines[1] and "risk $5/trade" in lines[1]


def test_london_engine_replays_one_box_break_per_day(monkeypatch):
    from engines import london_engine
    from london import add_box_columns
    for k, v in dict(LDN_BOX_START_HOUR=0, LDN_BOX_END_HOUR=10, LDN_WINDOW_END_HOUR=14, LDN_BUFFER_PIPS=0.0,
                     LDN_MAX_BOX_ATR=0.0, LDN_TREND_FILTER=False, LDN_SL_MODE="atr", LDN_SL_ATR=1.0, LDN_TP_R=2.0,
                     LDN_MAX_TRADES_PER_DAY=2, LDN_MAX_CONSECUTIVE_LOSSES=4, LDN_MANAGE_POSITIONS=False).items():
        monkeypatch.setattr(config, k, v, raising=False)
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)
    times = pd.date_range("2026-09-07 00:00", periods=24 * 12, freq="5min")     # Monday
    close = pd.Series(1.1000, index=range(len(times)))
    close[times.hour >= 10] = 1.1030                                           # break at 10:00
    close[times.hour >= 11] = 1.1080                                           # runs to the 2R target
    df = pd.DataFrame({"time": times, "open": close, "high": close + 0.0002, "low": close - 0.0002, "close": close})
    df["atr"] = 0.0010
    df = add_box_columns(df, buffer_price=0.0)
    e = london_engine()
    trades = run_backtest(df, "EURUSD", 0.0, 0.00001, 1.0, lambda d: 0.01, signal=e.signal, levels=e.levels,
                          max_trades_per_day=e.max_trades_per_day, max_consecutive_losses=e.max_consecutive_losses,
                          manage=e.manage, be_atr=e.breakeven_atr, trail_atr=e.trail_atr)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "BUY" and t.entry == pytest.approx(1.1030)
    assert t.sl == pytest.approx(1.1020) and t.tp == pytest.approx(1.1050) and t.reason == "TP"
    assert t.pnl == pytest.approx((1.1050 - 1.1030) / 0.00001 * 1.0 * 0.01)
