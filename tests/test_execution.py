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


# -- Engine-aware positions, orders and SL modify ------------------------------
from types import SimpleNamespace  # noqa: E402

import MetaTrader5 as mt5  # noqa: E402

import config  # noqa: E402
import execution  # noqa: E402
from engines import Engine, scalper_analyse, scalper_levels  # noqa: E402
from strategy import generate_signal  # noqa: E402


def _engine(name="london", magic=998888, comment="LDN", risk=4.0):
    return Engine(name=name, magic=magic, comment=comment, symbols=("EURUSD",), timeframe=5, lookback=300,
                  trend_filter=True, analyse=scalper_analyse, signal=generate_signal, levels=scalper_levels,
                  risk_usd=risk, max_trades_per_day=2, max_consecutive_losses=4,
                  manage=False, breakeven_atr=1.0, trail_atr=2.0)


def _pos(magic, symbol="XAUUSD"):
    return SimpleNamespace(magic=magic, symbol=symbol, ticket=magic)


class TestBotPositions:
    def test_default_filters_on_every_known_magic(self, monkeypatch):
        monkeypatch.setattr(execution, "KNOWN_MAGICS", {config.MAGIC_NUMBER, 998888})
        monkeypatch.setattr(execution.mt5, "positions_get",
                            lambda symbol=None: (_pos(config.MAGIC_NUMBER), _pos(998888), _pos(1)))
        assert [p.magic for p in execution.bot_positions()] == [config.MAGIC_NUMBER, 998888]

    def test_single_magic_and_iterable(self, monkeypatch):
        monkeypatch.setattr(execution.mt5, "positions_get",
                            lambda symbol=None: (_pos(config.MAGIC_NUMBER), _pos(998888), _pos(1)))
        assert [p.magic for p in execution.bot_positions(magic=998888)] == [998888]
        assert [p.magic for p in execution.bot_positions(magic=[1, 998888])] == [998888, 1]

    def test_none_result_is_empty(self, monkeypatch):
        monkeypatch.setattr(execution.mt5, "positions_get", lambda symbol=None: None)
        assert execution.bot_positions() == []

    def test_set_known_magics(self, monkeypatch):
        monkeypatch.setattr(execution, "KNOWN_MAGICS", {config.MAGIC_NUMBER})
        execution.set_known_magics([998888, config.MAGIC_NUMBER])
        assert execution.KNOWN_MAGICS == {config.MAGIC_NUMBER, 998888}


class TestOrderRequest:
    @pytest.fixture
    def capture(self, monkeypatch):
        sent, msgs, journal = [], [], []
        info = SimpleNamespace(digits=5, filling_mode=1)
        monkeypatch.setattr(execution.mt5, "symbol_info", lambda s: info)
        monkeypatch.setattr(execution.mt5, "order_send",
                            lambda req: sent.append(req) or SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=42))
        monkeypatch.setattr(execution, "send_telegram", msgs.append)
        monkeypatch.setattr(execution, "record_trade", lambda *a, **k: journal.append((a, k)))
        return sent, msgs, journal

    def test_engine_stamps_magic_comment_and_risk(self, capture):
        sent, msgs, journal = capture
        assert execution.send_market_order("BUY", "EURUSD", 0.02, 1.1, 1.09, 1.12, engine=_engine())
        assert sent[0]["magic"] == 998888 and sent[0]["comment"] == "LDN-EURUSD"
        assert "Engine:</b> london" in msgs[0] and "$4.00" in msgs[0]
        assert journal[0][1].get("note", "").startswith("[london]")

    def test_without_engine_behaviour_is_unchanged(self, capture):
        sent, msgs, journal = capture
        assert execution.send_market_order("SELL", "XAUUSD", 0.05, 2400.0, 2405.0, 2390.0)
        assert sent[0]["magic"] == config.MAGIC_NUMBER and sent[0]["comment"] == "AlgoBot-XAUUSD"
        assert "Engine:" not in msgs[0] and f"${config.RISK_USD_PER_TRADE:.2f}" in msgs[0]
        assert journal[0][1].get("note", "") == ""

    def test_modify_sl_uses_given_magic(self, monkeypatch):
        sent = []
        monkeypatch.setattr(execution.mt5, "symbol_info", lambda s: SimpleNamespace(digits=2))
        monkeypatch.setattr(execution.mt5, "order_send",
                            lambda req: sent.append(req) or SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE))
        pos = SimpleNamespace(ticket=7, symbol="XAUUSD", tp=2410.0)
        assert execution.modify_sl(pos, 2401.0, magic=998888)
        assert sent[0]["magic"] == 998888
        assert execution.modify_sl(pos, 2401.0)
        assert sent[1]["magic"] == config.MAGIC_NUMBER


# -- Connection settings (MT5_* in config / .env) ------------------------------------
import execution  # noqa: E402
from execution import mt5_init_args, account_mismatch, init_mt5  # noqa: E402
import config  # noqa: E402


def test_default_connection_attaches_to_the_default_terminal(monkeypatch):
    for key in ("MT5_PATH", "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.setattr(config, key, "")
    monkeypatch.setattr(config, "MT5_PORTABLE", False)
    assert mt5_init_args() == ((), {})


def test_explicit_terminal_and_account_are_passed_to_initialize(monkeypatch):
    monkeypatch.setattr(config, "MT5_PATH", "C:/mt5_scalp/terminal64.exe")
    monkeypatch.setattr(config, "MT5_LOGIN", "5055596110")
    monkeypatch.setattr(config, "MT5_PASSWORD", "pw")
    monkeypatch.setattr(config, "MT5_SERVER", "MetaQuotes-Demo")
    monkeypatch.setattr(config, "MT5_PORTABLE", True)
    args, kwargs = mt5_init_args()
    assert args == ("C:/mt5_scalp/terminal64.exe",)
    assert kwargs == {"login": 5055596110, "password": "pw", "server": "MetaQuotes-Demo", "portable": True}


def test_account_mismatch_only_checks_when_a_login_is_configured():
    assert account_mismatch(SimpleNamespace(login=1), "") is None
    assert account_mismatch(SimpleNamespace(login=5055596110), "5055596110") is None
    assert "unavailable" in account_mismatch(None, "5055596110")
    reason = account_mismatch(SimpleNamespace(login=123), "5055596110")
    assert "123" in reason and "5055596110" in reason


def test_init_mt5_refuses_the_wrong_account(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        initialize=lambda *a, **k: calls.append(("initialize", a, k)) or True,
        account_info=lambda: SimpleNamespace(login=123),
        symbol_select=lambda s, flag: True,
        shutdown=lambda: calls.append(("shutdown",)),
        last_error=lambda: (0, ""),
    )
    monkeypatch.setattr(execution, "mt5", fake)
    monkeypatch.setattr(config, "MT5_PATH", "C:/mt5_scalp/terminal64.exe")
    monkeypatch.setattr(config, "MT5_LOGIN", "5055596110")
    monkeypatch.setattr(config, "MT5_PASSWORD", "pw")
    monkeypatch.setattr(config, "MT5_SERVER", "MetaQuotes-Demo")
    monkeypatch.setattr(config, "MT5_PORTABLE", True)
    assert init_mt5(["XAUUSD"]) == []
    assert calls[0][0] == "initialize" and calls[0][2]["login"] == 5055596110
    assert ("shutdown",) in calls


def test_init_mt5_selects_symbols_on_the_right_account(monkeypatch):
    fake = SimpleNamespace(
        initialize=lambda *a, **k: True,
        account_info=lambda: SimpleNamespace(login=5055596110),
        symbol_select=lambda s, flag: s == "XAUUSD",
        shutdown=lambda: None,
        last_error=lambda: (0, ""),
    )
    monkeypatch.setattr(execution, "mt5", fake)
    monkeypatch.setattr(config, "MT5_PATH", "")
    monkeypatch.setattr(config, "MT5_LOGIN", "5055596110")
    assert init_mt5(["XAUUSD", "XAGUSD"]) == ["XAUUSD"]
