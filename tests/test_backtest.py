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
