from types import SimpleNamespace
from datetime import datetime

import MetaTrader5 as mt5
import pytest

import config
import risk
from risk import stats_from_deals, day_start_epoch, DailyStats

MAGIC = config.MAGIC_NUMBER
DAY = day_start_epoch(datetime(2026, 9, 4))


def deal(t, entry, profit, magic=MAGIC, ticket=None, commission=0.0, swap=0.0, fee=0.0):
    return SimpleNamespace(time=DAY + t, entry=entry, profit=profit, magic=magic,
                           ticket=ticket or t, commission=commission, swap=swap, fee=fee)


def test_counts_entries_and_exits_net_of_costs():
    deals = [
        deal(10, mt5.DEAL_ENTRY_IN, 0.0, commission=-0.1),
        deal(20, mt5.DEAL_ENTRY_OUT, 5.0, commission=-0.1),
        deal(30, mt5.DEAL_ENTRY_IN, 0.0),
        deal(40, mt5.DEAL_ENTRY_OUT, -3.0, swap=-0.2),
    ]
    s = stats_from_deals(deals, MAGIC, DAY)
    assert s.entries == 2
    assert s.wins == 1 and s.losses == 1
    assert s.net_pnl == pytest.approx(5.0 - 0.2 - 3.0 - 0.2)
    assert s.consecutive_losses == 1
    assert s.win_rate == 50.0


def test_streak_resets_on_win_and_ignores_other_magic_and_old_deals():
    deals = [
        deal(-100, mt5.DEAL_ENTRY_OUT, -50.0),          # yesterday
        deal(5, mt5.DEAL_ENTRY_OUT, -1.0),
        deal(6, mt5.DEAL_ENTRY_OUT, -1.0),
        deal(7, mt5.DEAL_ENTRY_OUT, 2.0),
        deal(8, mt5.DEAL_ENTRY_OUT, -1.0, magic=1),     # another EA
    ]
    s = stats_from_deals(deals, MAGIC, DAY)
    assert s.consecutive_losses == 0
    assert s.losses == 2 and s.wins == 1
    assert s.net_pnl == pytest.approx(0.0)


from types import SimpleNamespace as _NS  # noqa: E402

from risk import combine, account_breaker, engine_breaker  # noqa: E402


def test_combine_sums_and_merges_closed_deals_in_time_order():
    a = DailyStats(net_pnl=5.0, consecutive_losses=2, entries=2, wins=1, losses=1,
                   closed=[deal(30, mt5.DEAL_ENTRY_OUT, -1.0, ticket=3)])
    b = DailyStats(net_pnl=-2.0, consecutive_losses=0, entries=1, wins=0, losses=1,
                   closed=[deal(10, mt5.DEAL_ENTRY_OUT, -2.0, ticket=1), deal(40, mt5.DEAL_ENTRY_OUT, 4.0, ticket=4)])
    c = combine([a, b])
    assert c.net_pnl == pytest.approx(3.0) and c.entries == 3 and c.wins == 1 and c.losses == 2
    assert [d.ticket for d in c.closed] == [1, 3, 4]
    assert c.consecutive_losses == 0
    assert combine([]) == DailyStats()


def test_account_breaker_only_looks_at_daily_loss(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 30.0)
    assert account_breaker(DailyStats(net_pnl=-30.0)) == "daily loss $30.00 >= limit $30.00"
    assert account_breaker(DailyStats(net_pnl=-29.99, consecutive_losses=99)) is None


def test_engine_breaker_uses_the_engine_limit():
    engine = _NS(name="london", max_consecutive_losses=4)
    assert engine_breaker(engine, DailyStats(consecutive_losses=4)) == "4 consecutive losses"
    assert engine_breaker(engine, DailyStats(consecutive_losses=3, net_pnl=-1000)) is None


def test_daily_stats_by_magic_fetches_deals_once_for_every_magic(monkeypatch):
    calls = []

    def fake_history_deals_get(date_from, date_to):
        calls.append((date_from, date_to))
        return [
            deal(10, mt5.DEAL_ENTRY_OUT, 5.0, magic=MAGIC),
            deal(20, mt5.DEAL_ENTRY_OUT, -3.0, magic=998888),
            deal(30, mt5.DEAL_ENTRY_OUT, -1.0, magic=998888),
        ]

    monkeypatch.setattr(risk.mt5, "history_deals_get", fake_history_deals_get)
    out = risk.daily_stats_by_magic([MAGIC, 998888], datetime(2026, 9, 4, 12, 0))
    assert len(calls) == 1
    assert out[MAGIC].net_pnl == pytest.approx(5.0) and out[MAGIC].wins == 1
    assert out[998888].net_pnl == pytest.approx(-4.0) and out[998888].losses == 2


def test_get_daily_stats_is_a_thin_wrapper_over_daily_stats_by_magic(monkeypatch):
    calls = []

    def fake_history_deals_get(date_from, date_to):
        calls.append((date_from, date_to))
        return [deal(10, mt5.DEAL_ENTRY_OUT, 5.0, magic=MAGIC)]

    monkeypatch.setattr(risk.mt5, "history_deals_get", fake_history_deals_get)
    s = risk.get_daily_stats(MAGIC, datetime(2026, 9, 4, 12, 0))
    assert len(calls) == 1
    assert s.net_pnl == pytest.approx(5.0)
