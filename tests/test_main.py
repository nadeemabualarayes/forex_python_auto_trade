"""Startup exit codes: Task Scheduler only restarts on a non-zero exit."""
import pytest

import execution
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


# -- Multi-engine loop ----------------------------------------------------------
from dataclasses import replace  # noqa: E402
from datetime import datetime  # noqa: E402

import config  # noqa: E402
from engines import scalper_engine  # noqa: E402
from risk import DailyStats  # noqa: E402


class _Trader:
    def __init__(self, symbol, engine):
        self.symbol, self.engine, self.steps = symbol, engine, []
        self.last_skip_reason = None
        self.last_signal_bar = None

    def step(self, now, entries, news_block=None):
        self.steps.append(entries)

    def frame(self, max_age=0):
        return None


def _two_engine_bot(monkeypatch, stats_by_magic):
    scalper = scalper_engine()
    london = replace(scalper, name="london", magic=998888, symbols=("EURUSD",), max_consecutive_losses=2)
    monkeypatch.setattr(main, "SymbolTrader", _Trader)
    monkeypatch.setattr(main, "daily_stats_by_magic",
                        lambda magics, now: {m: stats_by_magic[m] for m in magics})
    monkeypatch.setattr(main, "manage_positions", lambda engine=None: None)
    monkeypatch.setattr(main, "bot_positions", lambda *a, **k: [])
    monkeypatch.setattr(main.config, "HISTORY_ENABLED", False)
    monkeypatch.setattr(main.config, "WEB_ENABLED", False)
    monkeypatch.setattr(execution, "KNOWN_MAGICS", set(execution.KNOWN_MAGICS))
    sent = []
    monkeypatch.setattr(main, "send_telegram", sent.append)
    bot = main.Bot(["XAUUSD", "XAGUSD", "EURUSD"], engines=[scalper, london])
    bot.clock.now = lambda symbols: datetime(2026, 9, 7, 12, 0)
    bot.news.maybe_refresh = lambda *a, **k: False
    bot.news.block_reason = lambda *a, **k: None
    bot.reporter.maybe_heartbeat = lambda *a, **k: None
    bot.reporter.maybe_daily_summary = lambda *a, **k: None
    return bot, sent


def test_bot_builds_one_trader_per_engine_symbol_and_drops_unavailable(monkeypatch):
    scalper = scalper_engine()
    london = replace(scalper, name="london", magic=998888, symbols=("EURUSD", "GBPUSD"))
    monkeypatch.setattr(main, "SymbolTrader", _Trader)
    monkeypatch.setattr(main.config, "HISTORY_ENABLED", False)
    monkeypatch.setattr(execution, "KNOWN_MAGICS", set(execution.KNOWN_MAGICS))
    bot = main.Bot(["XAUUSD", "XAGUSD", "EURUSD"], engines=[scalper, london])
    assert [(t.symbol, t.engine.name) for t in bot.traders] == [("XAUUSD", "scalper"), ("XAGUSD", "scalper"), ("EURUSD", "london")]
    assert bot.symbols == ["XAUUSD", "XAGUSD", "EURUSD"]
    assert bot.engines[1].symbols == ("EURUSD",)
    assert execution.KNOWN_MAGICS == {config.MAGIC_NUMBER, 998888}


def test_engine_streak_pauses_only_that_engine(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(entries=1),
                                              998888: DailyStats(consecutive_losses=2, entries=2)})
    bot.tick()
    steps = {(t.symbol, t.engine.name): t.steps for t in bot.traders}
    assert steps[("XAUUSD", "scalper")] == [1] and steps[("EURUSD", "london")] == []
    assert bot.paused == {"london": "2 consecutive losses"}
    assert len(sent) == 1 and "london" in sent[0]
    bot.tick()
    assert len(sent) == 1                                  # announced once


def test_account_loss_pauses_every_engine(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 30.0)
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(net_pnl=-20.0),
                                              998888: DailyStats(net_pnl=-11.0)})
    assert bot.tick() == config.BREAKER_SLEEP_SECONDS
    assert all(t.steps == [] for t in bot.traders)
    assert "circuit breaker" in sent[0] and "scalper" in sent[0] and "london" in sent[0]


def test_one_failing_trader_does_not_stop_the_others(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(), 998888: DailyStats()})
    monkeypatch.setattr(main.mt5, "terminal_info", lambda: object())
    def boom(now, entries, news_block=None):
        raise RuntimeError("bad tick")
    bot.traders[0].step = boom
    bot.tick()
    assert bot.traders[1].steps == [0] and bot.traders[2].steps == [0]
    assert any("bad tick" in m for m in sent)


def test_trader_error_alert_is_deduped_until_the_text_changes(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(), 998888: DailyStats()})
    monkeypatch.setattr(main.mt5, "terminal_info", lambda: object())
    def boom(now, entries, news_block=None):
        raise RuntimeError("bad tick")
    bot.traders[0].step = boom
    bot.tick()
    bot.tick()
    bot.tick()
    assert sum("bad tick" in m for m in sent) == 1

    def worse(now, entries, news_block=None):
        raise RuntimeError("worse tick")
    bot.traders[0].step = worse
    bot.tick()
    assert sum("worse tick" in m for m in sent) == 1

    bot.traders[0].step = lambda now, entries, news_block=None: bot.traders[0].steps.append(entries)
    bot.tick()
    assert bot.errored == {}


def test_engine_with_no_available_symbols_stays_in_the_magic_registry_and_breaker(monkeypatch):
    scalper = scalper_engine()
    london = replace(scalper, name="london", magic=998888, symbols=("GBPUSD",), max_consecutive_losses=2)
    monkeypatch.setattr(main, "SymbolTrader", _Trader)
    stats_by_magic = {config.MAGIC_NUMBER: DailyStats(net_pnl=0.0), 998888: DailyStats(net_pnl=-40.0)}
    calls = []
    def fake_daily_stats_by_magic(magics, now):
        calls.append(list(magics))
        return {m: stats_by_magic[m] for m in magics}
    monkeypatch.setattr(main, "daily_stats_by_magic", fake_daily_stats_by_magic)
    monkeypatch.setattr(main, "manage_positions", lambda engine=None: None)
    monkeypatch.setattr(main, "bot_positions", lambda *a, **k: [])
    monkeypatch.setattr(main.config, "HISTORY_ENABLED", False)
    monkeypatch.setattr(main.config, "WEB_ENABLED", False)
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 30.0)
    monkeypatch.setattr(execution, "KNOWN_MAGICS", set(execution.KNOWN_MAGICS))
    sent = []
    monkeypatch.setattr(main, "send_telegram", sent.append)

    # No symbol GBPUSD is available: london is disabled but must not vanish from bookkeeping.
    bot = main.Bot(["XAUUSD", "XAGUSD"], engines=[scalper, london])
    bot.clock.now = lambda symbols: datetime(2026, 9, 7, 12, 0)
    bot.news.maybe_refresh = lambda *a, **k: False
    bot.news.block_reason = lambda *a, **k: None
    bot.reporter.maybe_heartbeat = lambda *a, **k: None
    bot.reporter.maybe_daily_summary = lambda *a, **k: None

    assert execution.KNOWN_MAGICS == {config.MAGIC_NUMBER, 998888}
    assert bot.paused["london"] == "no symbols available"

    result = bot.tick()
    assert any(998888 in magics for magics in calls)
    assert result == config.BREAKER_SLEEP_SECONDS


def test_terminal_gone_reraises_the_original_error_and_sends_no_telegram(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(), 998888: DailyStats()})
    monkeypatch.setattr(main.mt5, "terminal_info", lambda: None)
    boom = RuntimeError("terminal gone mid-tick")

    def raiser(now, entries, news_block=None):
        raise boom
    bot.traders[0].step = raiser

    with pytest.raises(RuntimeError) as exc_info:
        bot.tick()
    assert exc_info.value is boom
    assert sent == []
