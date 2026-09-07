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


class TestCandleModes:
    def test_confirm_needs_setup_and_pattern(self, monkeypatch):
        monkeypatch.setattr(config, "CANDLE_MODE", "confirm")
        b = bar(95.0, rsi=40)                       # no touch on this bar
        b["buy_setup_recent"], b["bull_pattern"] = True, "hammer"
        assert raw_signal(b) == "BUY"
        b["bull_pattern"] = ""
        assert raw_signal(b) is None
        b["bull_pattern"], b["buy_setup_recent"] = "hammer", False
        assert raw_signal(b) is None

    def test_confirm_respects_pattern_whitelist(self, monkeypatch):
        monkeypatch.setattr(config, "CANDLE_MODE", "confirm")
        monkeypatch.setattr(config, "CANDLE_PATTERNS", ("bullish_engulfing",))
        b = bar(95.0, rsi=40)
        b["sell_setup_recent"], b["bear_pattern"] = True, "shooting_star"
        assert raw_signal(b) is None
        b["bear_pattern"] = "bearish_engulfing"
        assert raw_signal(b) is None               # not whitelisted for SELL either
        monkeypatch.setattr(config, "CANDLE_PATTERNS", ("bearish_engulfing",))
        assert raw_signal(b) == "SELL"

    def test_only_mode_uses_rsi_side(self, monkeypatch):
        monkeypatch.setattr(config, "CANDLE_MODE", "only")
        b = bar(95.0, rsi=40)
        b["bull_pattern"] = "morning_star"
        assert raw_signal(b) == "BUY"
        b["rsi"] = 60
        assert raw_signal(b) is None
        b["bear_pattern"] = "evening_star"
        assert raw_signal(b) == "SELL"

    def test_off_mode_ignores_patterns(self):
        b = bar(95.0, rsi=40)
        b["buy_setup_recent"], b["bull_pattern"] = True, "hammer"
        assert raw_signal(b) is None


class TestLevelMultipliers:
    def test_explicit_multipliers_override_config(self):
        lv = build_levels("BUY", ask=100.0, bid=99.9, atr=2.0, sl_mult=2.0, tp_mult=4.0)
        assert lv.sl == pytest.approx(96.0) and lv.tp == pytest.approx(108.0) and lv.sl_dist == pytest.approx(4.0)

    def test_default_multipliers_read_config_at_call_time(self, monkeypatch):
        monkeypatch.setattr(config, "SL_ATR_MULTIPLIER", 1.0)
        monkeypatch.setattr(config, "TP_ATR_MULTIPLIER", 5.0)
        lv = build_levels("SELL", ask=100.0, bid=99.9, atr=2.0)
        assert lv.sl == pytest.approx(101.9) and lv.tp == pytest.approx(89.9)


from types import SimpleNamespace  # noqa: E402

import pandas as pd  # noqa: E402

import strategy  # noqa: E402
from engines import Engine, scalper_engine, scalper_analyse  # noqa: E402


def test_trend_allows_explicit_enabled_flag(monkeypatch):
    monkeypatch.setattr(config, "TREND_FILTER_ENABLED", False)
    assert not trend_allows("BUY", 100, 110, enabled=True)
    assert trend_allows("BUY", 100, 110, enabled=False)
    assert trend_allows("BUY", 100, 110)                      # config says disabled


def _frame(n=60, close=100.0):
    return pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=n, freq="5min"),
                         "open": close, "high": close + 1, "low": close - 1, "close": close,
                         "tick_volume": 1, "spread": 3, "real_volume": 0})


def _engine(**over):
    base = dict(name="test", magic=4242, comment="T", symbols=("XAUUSD",), timeframe=5, lookback=60,
                trend_filter=False, analyse=scalper_analyse, signal=lambda bar: "BUY",
                levels=lambda side, ask, bid, bar: strategy.Levels(side, ask, ask - 1.0, ask + 2.0, 1.0),
                risk_usd=5.0, max_trades_per_day=2, max_consecutive_losses=4,
                manage=False, breakeven_atr=1.0, trail_atr=1.0)
    base.update(over)
    return Engine(**base)


@pytest.fixture
def wired(monkeypatch):
    """Stub every MT5-facing helper the trader touches; record what it asks for."""
    calls = {"positions": [], "orders": [], "skips": []}
    monkeypatch.setattr(strategy, "bot_positions", lambda symbol=None, magic=None: calls["positions"].append(magic) or [])
    monkeypatch.setattr(strategy, "spread_points", lambda symbol: 5.0)
    monkeypatch.setattr(strategy, "get_rates", lambda symbol, tf, n=120: _frame(n))
    monkeypatch.setattr(strategy, "calculate_dynamic_lot", lambda symbol, dist, risk, **kw: 0.1 if risk > 0 else 0.0)
    monkeypatch.setattr(strategy, "send_market_order",
                        lambda side, symbol, lot, price, sl, tp, engine=None: calls["orders"].append((side, engine.name, engine.magic)) or True)
    monkeypatch.setattr(strategy, "record_trade", lambda *a, **k: calls["skips"].append(k.get("note", "")))
    monkeypatch.setattr(strategy.mt5, "symbol_info_tick", lambda s: SimpleNamespace(ask=100.05, bid=100.0))
    monkeypatch.setattr(strategy.mt5, "symbol_info", lambda s: SimpleNamespace(point=0.01, digits=2))
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)
    return calls


def test_trader_defaults_to_the_scalper_profile():
    t = strategy.SymbolTrader("XAUUSD")
    assert t.engine.name == "scalper" and t.engine.magic == config.MAGIC_NUMBER


def test_trader_uses_engine_magic_cap_and_order_tag(wired):
    t = strategy.SymbolTrader("XAUUSD", _engine())
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=0)
    assert wired["positions"] == [4242]
    assert wired["orders"] == [("BUY", "test", 4242)]
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=2)       # engine cap reached
    assert len(wired["orders"]) == 1 and t.last_skip_reason == "daily trade cap 2 reached"


def test_trader_skips_when_levels_are_invalid(wired):
    t = strategy.SymbolTrader("XAUUSD", _engine(levels=lambda side, ask, bid, bar: None))
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=0)
    assert wired["orders"] == [] and wired["skips"] == ["no valid stop"]
