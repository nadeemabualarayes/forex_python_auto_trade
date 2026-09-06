from datetime import datetime

import pytest

import config
from strategy import in_session, raw_signal, trend_allows, generate_signal, build_levels


def bar(close, lower=90.0, upper=110.0, rsi=50.0, trend_ema=None):
    b = {"close": close, "lower_band": lower, "upper_band": upper, "rsi": rsi}
    if trend_ema is not None:
        b["trend_ema"] = trend_ema
    return b


@pytest.fixture
def window_7_20(monkeypatch):
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_START_HOUR", 7)
    monkeypatch.setattr(config, "SESSION_END_HOUR", 20)


class TestSession:
    def test_inside_window_weekday(self, window_7_20):
        assert in_session(datetime(2026, 9, 7, 7, 0))          # Monday 07:00
        assert in_session(datetime(2026, 9, 7, 19, 59))

    def test_edges_and_weekend(self, window_7_20):
        assert not in_session(datetime(2026, 9, 7, 6, 59))
        assert not in_session(datetime(2026, 9, 7, 20, 0))     # end is exclusive
        assert not in_session(datetime(2026, 9, 5, 12, 0))     # Saturday

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)
        assert in_session(datetime(2026, 9, 5, 3, 0))


class TestRawSignal:
    def test_buy_needs_band_and_rsi(self):
        assert raw_signal(bar(89.0, rsi=25)) == "BUY"
        assert raw_signal(bar(89.0, rsi=35)) is None
        assert raw_signal(bar(95.0, rsi=25)) is None

    def test_sell(self):
        assert raw_signal(bar(111.0, rsi=75)) == "SELL"
        assert raw_signal(bar(111.0, rsi=65)) is None


class TestTrend:
    def test_gates_direction(self):
        assert trend_allows("BUY", 100, 90)
        assert not trend_allows("BUY", 100, 110)
        assert trend_allows("SELL", 100, 110)
        assert not trend_allows("SELL", 100, 90)

    def test_missing_or_nan_blocks(self):
        assert not trend_allows("BUY", 100, None)
        assert not trend_allows("BUY", 100, float("nan"))

    def test_disabled_passes(self, monkeypatch):
        monkeypatch.setattr(config, "TREND_FILTER_ENABLED", False)
        assert trend_allows("BUY", 100, 110)

    def test_generate_signal_combined(self):
        assert generate_signal(bar(89.0, rsi=25, trend_ema=80.0)) == "BUY"
        assert generate_signal(bar(89.0, rsi=25, trend_ema=95.0)) is None
        assert generate_signal(bar(89.0, rsi=25)) is None            # no ema -> blocked


class TestLevels:
    def test_buy_levels(self):
        lv = build_levels("BUY", ask=100.0, bid=99.9, atr=2.0)
        assert lv.entry == 100.0
        assert lv.sl == pytest.approx(100.0 - 2.0 * config.SL_ATR_MULTIPLIER)
        assert lv.tp == pytest.approx(100.0 + 2.0 * config.TP_ATR_MULTIPLIER)

    def test_sell_levels(self):
        lv = build_levels("SELL", ask=100.0, bid=99.9, atr=2.0)
        assert lv.entry == 99.9
        assert lv.sl > lv.entry > lv.tp
