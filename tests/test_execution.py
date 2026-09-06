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


# -- Startup permission guard --------------------------------------------------
from types import SimpleNamespace  # noqa: E402
from execution import trading_blockers  # noqa: E402


def _terminal(**kw):
    return SimpleNamespace(**{"connected": True, "trade_allowed": True, "tradeapi_disabled": False, **kw})


def _account(**kw):
    return SimpleNamespace(**{"trade_allowed": True, "trade_expert": True, **kw})


def test_no_blockers_when_everything_is_enabled():
    assert trading_blockers(_terminal(), _account()) == []


def test_autotrading_button_off_is_reported_with_its_retcode():
    reasons = trading_blockers(_terminal(trade_allowed=False), _account())
    assert len(reasons) == 1
    assert "AutoTrading" in reasons[0] and "10027" in reasons[0]


def test_python_api_disabled_in_terminal_options_is_reported():
    reasons = trading_blockers(_terminal(tradeapi_disabled=True), _account())
    assert len(reasons) == 1 and "Python API" in reasons[0]


def test_disconnected_terminal_is_reported():
    reasons = trading_blockers(_terminal(connected=False), _account())
    assert len(reasons) == 1 and "not connected" in reasons[0]


def test_missing_terminal_info_is_reported_once():
    reasons = trading_blockers(None, _account())
    assert len(reasons) == 1 and "terminal" in reasons[0].lower()


def test_server_side_trading_ban_is_reported_with_its_retcode():
    reasons = trading_blockers(_terminal(), _account(trade_allowed=False))
    assert len(reasons) == 1 and "10026" in reasons[0]


def test_account_without_expert_trading_is_reported():
    reasons = trading_blockers(_terminal(), _account(trade_expert=False))
    assert len(reasons) == 1 and "algorithmic" in reasons[0].lower()


def test_missing_account_info_is_reported_once():
    reasons = trading_blockers(_terminal(), None)
    assert len(reasons) == 1 and "account" in reasons[0].lower()


def test_every_blocker_is_listed():
    reasons = trading_blockers(_terminal(trade_allowed=False), _account(trade_allowed=False))
    assert len(reasons) == 2
