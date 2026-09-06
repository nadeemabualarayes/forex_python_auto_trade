"""Startup exit codes: Task Scheduler only restarts on a non-zero exit."""
import main


def test_run_returns_failure_code_when_mt5_init_fails(monkeypatch):
    monkeypatch.setattr(main, "init_mt5", lambda symbols: [])
    monkeypatch.setattr(main, "send_telegram", lambda *a, **k: None)
    assert main.run() == 1


# -- Startup permission guard --------------------------------------------------
from types import SimpleNamespace  # noqa: E402


def _fake_terminal(monkeypatch, **terminal):
    t = {"connected": True, "trade_allowed": True, "tradeapi_disabled": False, **terminal}
    monkeypatch.setattr(main.mt5, "terminal_info", lambda: SimpleNamespace(**t))
    monkeypatch.setattr(main.mt5, "account_info", lambda: SimpleNamespace(trade_allowed=True, trade_expert=True))


def test_guard_sends_telegram_warning_when_autotrading_is_off(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "send_telegram", sent.append)
    _fake_terminal(monkeypatch, trade_allowed=False)
    reasons = main.warn_if_trading_blocked()
    assert reasons
    assert len(sent) == 1 and "Trading blocked" in sent[0] and "AutoTrading" in sent[0]


def test_guard_is_silent_when_trading_is_allowed(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "send_telegram", sent.append)
    _fake_terminal(monkeypatch)
    assert main.warn_if_trading_blocked() == []
    assert sent == []


class _StopImmediately:
    """Stand-in Bot whose first tick stops the loop, so run() exits cleanly."""
    store = None

    def __init__(self, *a, **k):
        pass

    def tick(self):
        raise KeyboardInterrupt


def test_run_checks_permissions_right_after_connecting(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "init_mt5", lambda symbols: list(symbols))
    monkeypatch.setattr(main, "send_telegram", lambda *a, **k: None)
    monkeypatch.setattr(main, "warn_if_trading_blocked", lambda: calls.append("checked") or [])
    monkeypatch.setattr(main, "Bot", _StopImmediately)
    monkeypatch.setattr(main.config, "WEB_ENABLED", False)
    monkeypatch.setattr(main.config, "PAGES_PUBLISH_ENABLED", False)
    assert main.run() == 0
    assert calls == ["checked"]
