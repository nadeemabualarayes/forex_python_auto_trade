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
