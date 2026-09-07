"""Telegram texts are built by pure helpers so the wording is testable without MT5."""
from datetime import datetime
from types import SimpleNamespace

import MetaTrader5 as mt5

import config
import reporting
from reporting import Reporter, daily_summary_text
from risk import DailyStats


def _engine(name, cap=6):
    return SimpleNamespace(name=name, max_trades_per_day=cap)


def test_daily_summary_lists_each_engine_and_the_total():
    total = DailyStats(net_pnl=7.5, entries=3, wins=2, losses=1,
                       closed=[SimpleNamespace(profit=5.0, commission=0, swap=0, fee=0),
                               SimpleNamespace(profit=-2.5, commission=0, swap=0, fee=0)])
    text = daily_summary_text(datetime(2026, 9, 7, 23, 0), total,
                              [(_engine("scalper"), DailyStats(net_pnl=10.0, entries=2, wins=2)),
                               (_engine("london", 2), DailyStats(net_pnl=-2.5, entries=1, losses=1))])
    assert "Daily summary 2026-09-07" in text
    assert "scalper: entries 2, net $10.00" in text and "london: entries 1, net $-2.50" in text
    assert "<b>Net: $7.50</b>" in text


def test_daily_summary_without_engines_matches_single_engine_wording():
    text = daily_summary_text(datetime(2026, 9, 7, 23, 0), DailyStats(), None)
    assert text == "\U0001F4CA <b>Daily summary 2026-09-07</b>\nNo trades today."


def test_close_message_names_engine_only_with_several_engines(monkeypatch):
    sent = []
    monkeypatch.setattr(reporting, "send_telegram", sent.append)
    monkeypatch.setattr(reporting, "record_trade", lambda *a, **k: None)
    deal = SimpleNamespace(ticket=1, position_id=1, symbol="EURUSD", type=mt5.DEAL_TYPE_SELL, price=1.1,
                           volume=0.02, profit=2.0, commission=0.0, swap=0.0, fee=0.0, reason=mt5.DEAL_REASON_TP,
                           time=1_800_000_000, magic=998888)
    r = Reporter({config.MAGIC_NUMBER: "scalper", 998888: "london"})
    r.primed = True
    r.notify_closes(DailyStats(closed=[deal]))
    assert "Engine: london" in sent[0]
    single = Reporter()
    single.primed = True
    single.notify_closes(DailyStats(closed=[deal]))
    assert "Engine:" not in sent[1]
