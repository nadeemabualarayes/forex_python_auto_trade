import pytest
from position_manager import next_stop

ATR, MIN = 2.0, 0.05


class TestBuy:
    def test_no_move_before_breakeven(self):
        assert next_stop("BUY", 100, 97, 101.9, ATR, 1.0, 1.0, MIN) is None

    def test_breakeven_at_one_atr(self):
        assert next_stop("BUY", 100, 97, 102.0, ATR, 1.0, 1.0, MIN) == pytest.approx(100.0)

    def test_trails_behind_price(self):
        assert next_stop("BUY", 100, 100, 105.0, ATR, 1.0, 1.0, MIN) == pytest.approx(103.0)

    def test_never_loosens(self):
        assert next_stop("BUY", 100, 103, 104.0, ATR, 1.0, 1.0, MIN) is None

    def test_ignores_tiny_improvement(self):
        assert next_stop("BUY", 100, 103, 105.02, ATR, 1.0, 1.0, MIN) is None

    def test_zero_sl_treated_as_unset(self):
        assert next_stop("BUY", 100, 0, 102.0, ATR, 1.0, 1.0, MIN) == pytest.approx(100.0)


class TestSell:
    def test_breakeven(self):
        assert next_stop("SELL", 100, 103, 98.0, ATR, 1.0, 1.0, MIN) == pytest.approx(100.0)

    def test_trail(self):
        assert next_stop("SELL", 100, 100, 95.0, ATR, 1.0, 1.0, MIN) == pytest.approx(97.0)

    def test_never_loosens(self):
        assert next_stop("SELL", 100, 96, 95.5, ATR, 1.0, 1.0, MIN) is None


def test_bad_atr():
    assert next_stop("BUY", 100, 97, 110, 0.0, 1.0, 1.0, MIN) is None
    assert next_stop("BUY", 100, 97, 110, float("nan"), 1.0, 1.0, MIN) is None


from types import SimpleNamespace  # noqa: E402

import pandas as pd  # noqa: E402

import config  # noqa: E402
import position_manager  # noqa: E402
from engines import scalper_engine  # noqa: E402
from dataclasses import replace  # noqa: E402


def test_manage_is_a_no_op_when_the_engine_does_not_manage(monkeypatch):
    monkeypatch.setattr(position_manager, "bot_positions", lambda *a, **k: (_ for _ in ()).throw(AssertionError("touched MT5")))
    position_manager.manage_positions(replace(scalper_engine(), manage=False))


def test_manage_uses_engine_timeframe_and_magic(monkeypatch):
    engine = replace(scalper_engine(), name="t", magic=4242, timeframe=15, manage=True, breakeven_atr=1.0, trail_atr=1.0)
    asked, modified = [], []
    pos = SimpleNamespace(symbol="XAUUSD", ticket=9, type=0, price_open=100.0, sl=97.0, tp=110.0, volume=0.1)
    monkeypatch.setattr(position_manager, "bot_positions", lambda symbol=None, magic=None: asked.append(magic) or [pos])
    monkeypatch.setattr(position_manager.mt5, "symbol_info", lambda s: SimpleNamespace(point=0.01, digits=2, trade_stops_level=0))
    monkeypatch.setattr(position_manager.mt5, "symbol_info_tick", lambda s: SimpleNamespace(time=1, bid=105.0, ask=105.1))
    frame = pd.DataFrame({"time": pd.date_range("2026-09-07", periods=50, freq="15min"),
                          "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    monkeypatch.setattr(position_manager, "get_rates", lambda symbol, tf, n=0: asked.append(tf) or frame)
    monkeypatch.setattr(position_manager, "modify_sl", lambda p, sl, magic=None: modified.append((round(sl, 2), magic)) or True)
    monkeypatch.setattr(position_manager, "record_trade", lambda *a, **k: None)
    position_manager.manage_positions(engine)
    assert asked == [4242, 15]
    assert modified == [(103.0, 4242)]                  # ATR 2 -> trail 1 ATR behind 105
