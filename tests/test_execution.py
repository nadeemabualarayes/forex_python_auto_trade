import pytest
from execution import lot_for_risk

GOLD = dict(tick_size=0.01, tick_value=0.1, volume_min=0.01, volume_max=100.0, volume_step=0.01)
SILVER = dict(tick_size=0.001, tick_value=0.5, volume_min=0.01, volume_max=100.0, volume_step=0.01)


def test_gold_sizing_floors_to_step():
    # $3.00 SL on gold = 300 ticks * $0.1 = $30 per lot -> $5 budget = 0.1666 -> 0.16
    assert lot_for_risk(3.0, 5.0, **GOLD) == pytest.approx(0.16)


def test_silver_sizing():
    # 0.05 SL on silver = 50 ticks * $0.5 = $25 per lot -> 0.2 lots
    assert lot_for_risk(0.05, 5.0, **SILVER) == pytest.approx(0.20)


def test_returns_zero_when_min_lot_exceeds_budget():
    assert lot_for_risk(60.0, 5.0, **GOLD) == 0.0           # $600/lot -> 0.008 < 0.01


def test_caps_at_volume_max():
    assert lot_for_risk(0.01, 1e6, **GOLD) == 100.0


def test_guards_bad_inputs():
    assert lot_for_risk(0.0, 5.0, **GOLD) == 0.0
    assert lot_for_risk(-1.0, 5.0, **GOLD) == 0.0
