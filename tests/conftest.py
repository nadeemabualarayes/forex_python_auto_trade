"""Make the project importable and provide a MetaTrader5 stand-in when the package is absent."""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import MetaTrader5  # noqa: F401  (real package present: constants are usable without a terminal)
except ImportError:
    fake = types.ModuleType("MetaTrader5")
    consts = dict(
        TIMEFRAME_M5=5, TIMEFRAME_H1=16385,
        ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1,
        DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1,
        DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=2, DEAL_ENTRY_OUT_BY=3,
        DEAL_REASON_SL=7, DEAL_REASON_TP=8,
        TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6, ORDER_TIME_GTC=0,
        ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, ORDER_FILLING_RETURN=2,
        TRADE_RETCODE_DONE=10009,
    )
    fake.__dict__.update(consts)
    for fn in ("initialize", "shutdown", "symbol_select", "symbol_info", "symbol_info_tick",
               "copy_rates_from_pos", "copy_rates_range", "positions_get", "history_deals_get",
               "order_send", "last_error", "terminal_info"):
        fake.__dict__[fn] = lambda *a, **k: None
    sys.modules["MetaTrader5"] = fake

import pytest  # noqa: E402
import config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    """Never write into the real logs/ directory from tests."""
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LOG_FILE", str(tmp_path / "bot.log"))
    monkeypatch.setattr(config, "TRADE_JOURNAL", str(tmp_path / "trades.csv"))
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "")


@pytest.fixture(autouse=True)
def plain_entry_rule(monkeypatch):
    """Tests exercise the plain BB+RSI rule unless they opt into a candlestick mode themselves."""
    monkeypatch.setattr(config, "CANDLE_MODE", "off")
    monkeypatch.setattr(config, "CANDLE_PATTERNS", None)
    monkeypatch.setattr(config, "CANDLE_LOOKBACK", 3)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never fetch the economic calendar; test_news opts in with a fake fetcher."""
    monkeypatch.setattr(config, "NEWS_FILTER_ENABLED", False)
