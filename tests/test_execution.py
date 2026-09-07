import pytest
from execution import lot_for_risk

# tick_value here is the field MetaQuotes-Demo REPORTS for the metals (0.1 / 0.5). The real values are
# 1.0 / 5.0 (contract 100 oz x 0.01, 5000 oz x 0.001); these fixtures only exercise the arithmetic of
# lot_for_risk given its inputs. The live sizing path no longer trusts the field: see TestTerminalPricedSizing.
GOLD = dict(tick_size=0.01, tick_value=0.1, volume_min=0.01, volume_max=100.0, volume_step=0.01)
SILVER = dict(tick_size=0.001, tick_value=0.5, volume_min=0.01, volume_max=100.0, volume_step=0.01)
GOLD_TRUE = dict(GOLD, tick_value=1.0)
SILVER_TRUE = dict(SILVER, tick_value=5.0)


def test_gold_sizing_floors_to_step():
    # $3.00 SL on gold = 300 ticks * $0.1 = $30 per lot -> $5 budget = 0.1666 -> 0.16
    assert lot_for_risk(3.0, 5.0, **GOLD) == pytest.approx(0.16)


def test_silver_sizing():
    # 0.05 SL on silver = 50 ticks * $0.5 = $25 per lot -> 0.2 lots
    assert lot_for_risk(0.05, 5.0, **SILVER) == pytest.approx(0.20)


def test_metals_with_their_real_tick_values():
    # the 2026-09-07 trade: SL 2.634 on gold = $263.4 per lot -> $5 buys 0.0189 -> 0.01 (not 0.18)
    assert lot_for_risk(2.634, 5.0, **GOLD_TRUE) == pytest.approx(0.01)
    # evaluation profile: SL 7.8 on gold = $780 per lot -> 0.01 lot already risks $7.80 > $5 -> nothing fits
    assert lot_for_risk(7.8, 5.0, **GOLD_TRUE) == 0.0
    assert lot_for_risk(7.8, 10.0, **GOLD_TRUE) == pytest.approx(0.01)
    assert lot_for_risk(0.05, 5.0, **SILVER_TRUE) == pytest.approx(0.02)      # $250 per lot


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


# -- Terminal-priced sizing: order_calc_profit first, the tick-value field only once verified ------------
from execution import lot_for_loss, loss_per_lot, calculate_dynamic_lot, verify_tick_value  # noqa: E402


def _info(**kw):
    base = dict(trade_tick_size=0.01, trade_tick_value=0.1, volume_min=0.01, volume_max=100.0, volume_step=0.01,
                trade_contract_size=100.0, currency_profit="USD", bid=4400.0, ask=4400.3)
    return SimpleNamespace(**{**base, **kw})


def _calc(contract_size):
    """A terminal that prices moves with the real contract size, like order_calc_profit does."""
    def calc(order_type, symbol, lot, price_open, price_close):
        move = price_close - price_open if order_type == 0 else price_open - price_close
        return round(move * contract_size * lot, 2)
    return calc


def _fake_mt5(info, calc=None):
    ns = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, symbol_info=lambda s: info)
    if calc is not None:
        ns.order_calc_profit = calc
    return ns


GOLD_INFO = _info()                                                                  # field says 0.1, truth 1.0
SILVER_INFO = _info(trade_tick_size=0.001, trade_tick_value=0.5, trade_contract_size=5000.0, bid=40.0, ask=40.02)
EUR_INFO = _info(trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100000.0, bid=1.16240, ask=1.16246)
GBP_INFO = _info(trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100000.0, bid=1.35000, ask=1.35008)
gold_calc, silver_calc, fx_calc = _calc(100.0), _calc(5000.0), _calc(100000.0)


@pytest.fixture(autouse=True)
def fresh_trust(monkeypatch):
    monkeypatch.setattr(execution, "TICK_VALUE_TRUSTED", {})


class TestLotForLoss:
    def test_floors_to_step_and_caps(self):
        assert lot_for_loss(26.34, 5.0, 0.01, 100.0, 0.01) == pytest.approx(0.18)
        assert lot_for_loss(263.4, 5.0, 0.01, 100.0, 0.01) == pytest.approx(0.01)
        assert lot_for_loss(0.001, 1e6, 0.01, 100.0, 0.01) == 100.0

    def test_nothing_fits_or_bad_inputs(self):
        assert lot_for_loss(780.0, 5.0, 0.01, 100.0, 0.01) == 0.0
        assert lot_for_loss(0.0, 5.0, 0.01, 100.0, 0.01) == 0.0
        assert lot_for_loss(10.0, 0.0, 0.01, 100.0, 0.01) == 0.0

    def test_lot_for_risk_is_the_same_rule_fed_by_a_tick_value(self):
        assert lot_for_risk(3.0, 5.0, **GOLD) == lot_for_loss(3.0 / 0.01 * 0.1, 5.0, 0.01, 100.0, 0.01)


class TestTerminalPricedSizing:
    def test_xauusd_observed_trade_is_sized_from_the_terminal(self, monkeypatch):
        # 2026-09-07 13:23 server: BUY at 4400.58, SL 2.6342 away, $5 budget. The field gave 0.18 lots
        # (-$47.34 realised); the terminal prices the move at $263.42 per lot -> 0.01 lot ($2.63 at risk).
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO, gold_calc))
        loss, source = loss_per_lot("XAUUSD", "BUY", 4400.58, 2.6342, GOLD_INFO)
        assert source == "terminal" and loss == pytest.approx(263.42)
        assert calculate_dynamic_lot("XAUUSD", 2.6342, 5.0, side="BUY", price=4400.58) == pytest.approx(0.01)
        assert execution.TICK_VALUE_TRUSTED["XAUUSD"] is False

    def test_xagusd_is_sized_from_the_terminal(self, monkeypatch):
        # silver: 0.05 stop x 5,000 oz = $250 per lot -> $5 buys 0.02 (the field would have said 0.20)
        monkeypatch.setattr(execution, "mt5", _fake_mt5(SILVER_INFO, silver_calc))
        assert calculate_dynamic_lot("XAGUSD", 0.05, 5.0, side="SELL", price=40.0) == pytest.approx(0.02)
        assert lot_for_risk(0.05, 5.0, **SILVER) == pytest.approx(0.20)
        assert execution.TICK_VALUE_TRUSTED["XAGUSD"] is False

    def test_sell_side_prices_the_move_upwards(self, monkeypatch):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO, gold_calc))
        assert loss_per_lot("XAUUSD", "SELL", 4400.0, 2.0, GOLD_INFO) == (pytest.approx(200.0), "terminal")

    def test_fx_terminal_path_matches_the_field(self, monkeypatch):
        # EURUSD / GBPUSD: field 1.0 agrees with the terminal, so both paths give the same lot
        for symbol, info in (("EURUSD", EUR_INFO), ("GBPUSD", GBP_INFO)):
            monkeypatch.setattr(execution, "mt5", _fake_mt5(info, fx_calc))
            via_terminal = calculate_dynamic_lot(symbol, 0.0030, 5.0, side="BUY", price=info.ask)
            via_field = lot_for_risk(0.0030, 5.0, 0.00001, 1.0, 0.01, 100.0, 0.01)
            assert via_terminal == via_field == pytest.approx(0.01)
            assert calculate_dynamic_lot(symbol, 0.0010, 5.0, side="BUY", price=info.ask) == pytest.approx(0.05)
            assert execution.TICK_VALUE_TRUSTED[symbol] is True


class TestNoTerminalPricing:
    """The terminal cannot price the stop: only a symbol whose field was verified may fall back."""

    @pytest.mark.parametrize("symbol,info,sl", [("XAUUSD", GOLD_INFO, 2.6342), ("XAGUSD", SILVER_INFO, 0.05)])
    def test_metal_with_unverified_field_gets_no_lot(self, monkeypatch, caplog, symbol, info, sl):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(info))                     # no calculator at all
        with caplog.at_level("WARNING", logger="bot"):
            assert calculate_dynamic_lot(symbol, sl, 5.0, side="BUY", price=info.ask) == 0.0
        assert "could not price" in caplog.text and "not verified" in caplog.text and "no lot placed" in caplog.text
        monkeypatch.setattr(execution, "mt5", _fake_mt5(info, lambda *a: None))    # calculator answers None
        assert calculate_dynamic_lot(symbol, sl, 5.0, side="BUY", price=info.ask) == 0.0
        assert calculate_dynamic_lot(symbol, sl, 5.0) == 0.0                        # no side/price either

    @pytest.mark.parametrize("symbol,info,sl,calc", [("XAUUSD", GOLD_INFO, 2.6342, gold_calc),
                                                     ("XAGUSD", SILVER_INFO, 0.05, silver_calc)])
    def test_metal_with_a_field_known_wrong_gets_no_lot(self, monkeypatch, caplog, symbol, info, sl, calc):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(info, calc))
        assert verify_tick_value(symbol, info) is False                               # start-up check found it wrong
        monkeypatch.setattr(execution, "mt5", _fake_mt5(info))                      # then the terminal goes away
        with caplog.at_level("WARNING", logger="bot"):
            assert calculate_dynamic_lot(symbol, sl, 5.0, side="BUY", price=info.ask) == 0.0
        assert "SYMBOL_TRADE_TICK_VALUE is wrong" in caplog.text and "no lot placed" in caplog.text

    def test_fx_with_a_verified_field_still_falls_back(self, monkeypatch):
        for symbol, info in (("EURUSD", EUR_INFO), ("GBPUSD", GBP_INFO)):
            monkeypatch.setattr(execution, "mt5", _fake_mt5(info, fx_calc))
            assert verify_tick_value(symbol, info) is True
            monkeypatch.setattr(execution, "mt5", _fake_mt5(info))                  # calculator unavailable
            loss, source = loss_per_lot(symbol, "BUY", info.ask, 0.0030, info)
            assert source == "tick_value" and loss == pytest.approx(300.0)
            assert calculate_dynamic_lot(symbol, 0.0030, 5.0, side="BUY", price=info.ask) == pytest.approx(0.01)
            assert calculate_dynamic_lot(symbol, 0.0030, 5.0) == pytest.approx(0.01)

    def test_fx_never_verified_does_not_fall_back(self, monkeypatch):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(EUR_INFO))
        assert calculate_dynamic_lot("EURUSD", 0.0030, 5.0, side="BUY", price=EUR_INFO.ask) == 0.0


class TestVerifyTickValue:
    def test_verdicts(self, monkeypatch):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO, gold_calc))
        assert verify_tick_value("XAUUSD", GOLD_INFO) is False
        monkeypatch.setattr(execution, "mt5", _fake_mt5(EUR_INFO, fx_calc))
        assert verify_tick_value("EURUSD", EUR_INFO) is True
        assert verify_tick_value("EURUSD", _info(**{**vars(EUR_INFO), "bid": 0, "ask": 0})) is None   # no price
        monkeypatch.setattr(execution, "mt5", _fake_mt5(EUR_INFO))
        assert verify_tick_value("EURUSD", EUR_INFO) is None                          # no calculator
        assert execution.TICK_VALUE_TRUSTED == {"XAUUSD": False, "EURUSD": True}

    def test_wrong_field_is_warned_once_and_skips_are_warned_every_time(self, monkeypatch, caplog):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO, gold_calc))
        with caplog.at_level("WARNING", logger="bot"):
            calculate_dynamic_lot("XAUUSD", 2.0, 5.0, side="BUY", price=4400.0)
            calculate_dynamic_lot("XAUUSD", 2.0, 5.0, side="BUY", price=4400.0)
        assert caplog.text.count("sized from the terminal only") == 1
        caplog.clear()
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO))
        with caplog.at_level("WARNING", logger="bot"):
            calculate_dynamic_lot("XAUUSD", 2.0, 5.0, side="BUY", price=4400.0)
            calculate_dynamic_lot("XAUUSD", 2.0, 5.0, side="BUY", price=4400.0)
        assert caplog.text.count("no lot placed") == 2

    def test_min_lot_over_budget_gives_zero_and_logs(self, monkeypatch, caplog):
        monkeypatch.setattr(execution, "mt5", _fake_mt5(GOLD_INFO, gold_calc))
        with caplog.at_level("INFO", logger="bot"):
            assert calculate_dynamic_lot("XAUUSD", 7.8, 5.0, side="BUY", price=4400.0) == 0.0
        assert "min lot 0.01 would risk $7.80 > budget $5.00" in caplog.text

    def test_init_mt5_verifies_every_selected_symbol(self, monkeypatch, caplog):
        infos = {"XAUUSD": GOLD_INFO, "EURUSD": EUR_INFO}

        def calc(order_type, symbol, lot, po, pc):
            return (gold_calc if symbol == "XAUUSD" else fx_calc)(order_type, symbol, lot, po, pc)

        fake = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, initialize=lambda *a, **k: True,
                               account_info=lambda: SimpleNamespace(login=1), symbol_select=lambda s, f: True,
                               symbol_info=lambda s: infos[s], order_calc_profit=calc, shutdown=lambda: None,
                               last_error=lambda: (0, ""))
        monkeypatch.setattr(execution, "mt5", fake)
        monkeypatch.setattr(config, "MT5_PATH", "")
        monkeypatch.setattr(config, "MT5_LOGIN", "")
        with caplog.at_level("INFO", logger="bot"):
            assert init_mt5(["XAUUSD", "EURUSD"]) == ["XAUUSD", "EURUSD"]
        assert execution.TICK_VALUE_TRUSTED == {"XAUUSD": False, "EURUSD": True}
        assert "[XAUUSD] SYMBOL_TRADE_TICK_VALUE 0.1 is wrong" in caplog.text
        assert "[EURUSD] tick value 1.0 verified" in caplog.text
