"""Deals -> trades -> metrics, on a hand-computed set."""
import json

import pytest
import MetaTrader5 as mt5

from analytics import (Trade, pair_trades, summary, breakdown, daily_pnl, equity_curve, drawdown,
                       build_analytics)
from history import Deal

IN, OUT = mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_OUT
BUY, SELL = mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL
SL, TP, CLIENT = mt5.DEAL_REASON_SL, mt5.DEAL_REASON_TP, mt5.DEAL_REASON_CLIENT


def _d(ticket, pos, entry, typ, t, price, vol=0.1, profit=0.0, comm=-0.1, reason=0, symbol="XAUUSD"):
    return Deal(ticket=ticket, position_id=pos, symbol=symbol, type=typ, entry=entry, magic=777,
                reason=reason, volume=vol, price=price, profit=profit, commission=comm, swap=0.0,
                fee=0.0, time=t)


DEALS = [
    # A: BUY 0.1 gold, closed at TP  -> gross 10.2, commission -0.2, net +10.0, 600 s
    _d(1, 1, IN, BUY, 1000, 2400.0),
    _d(2, 1, OUT, SELL, 1600, 2410.0, profit=10.2, reason=TP),
    # B: SELL 0.2 silver, two partial closes (SL then manual) -> gross -3.6, comm -0.4, net -4.0, 600 s
    _d(3, 2, IN, SELL, 2000, 30.0, vol=0.2, comm=-0.2, symbol="XAGUSD"),
    _d(4, 2, OUT, BUY, 2500, 30.1, vol=0.1, profit=-2.0, reason=SL, symbol="XAGUSD"),
    _d(5, 2, OUT, BUY, 2600, 30.2, vol=0.1, profit=-1.6, reason=CLIENT, symbol="XAGUSD"),
    # C: BUY 0.1 gold, closed by (trailed) SL in profit -> gross 6.2, comm -0.2, net +6.0, 900 s
    _d(6, 3, IN, BUY, 3000, 2405.0),
    _d(7, 3, OUT, SELL, 3900, 2411.0, profit=6.2, reason=SL),
    # D: still open -> ignored
    _d(8, 4, IN, BUY, 4000, 2420.0),
]


@pytest.fixture
def trades():
    return pair_trades(DEALS)


def test_pairing(trades):
    assert [t.position_id for t in trades] == [1, 2, 3]            # sorted by exit time, open one dropped
    a, b, c = trades
    assert (a.side, a.volume, a.entry_price, a.exit_price, a.reason) == ("BUY", 0.1, 2400.0, 2410.0, "TP")
    assert a.net == pytest.approx(10.0) and a.gross == pytest.approx(10.2) and a.commission == pytest.approx(-0.2)
    assert b.side == "SELL" and b.volume == pytest.approx(0.2)
    assert b.exit_price == pytest.approx(30.15)                     # volume-weighted
    assert b.net == pytest.approx(-4.0) and b.reason == "manual" and b.exit_time == 2600
    assert c.reason == "SL" and c.duration_s == 900
    assert isinstance(a, Trade) and a.hour == 0 and a.weekday == 3   # 1970-01-01 00:16 server, Thursday


def test_summary_metrics(trades):
    s = summary(trades)
    assert s["trades"] == 3 and s["wins"] == 2 and s["losses"] == 1 and s["breakeven"] == 0
    assert s["win_rate"] == pytest.approx(66.7, abs=0.05)
    assert s["net"] == pytest.approx(12.0)
    assert s["gross_profit"] == pytest.approx(16.0) and s["gross_loss"] == pytest.approx(4.0)
    assert s["profit_factor"] == pytest.approx(4.0)
    assert s["expectancy"] == pytest.approx(4.0)
    assert s["avg_win"] == pytest.approx(8.0) and s["avg_loss"] == pytest.approx(4.0)
    assert s["payoff_ratio"] == pytest.approx(2.0)
    assert s["largest_win"] == pytest.approx(10.0) and s["largest_loss"] == pytest.approx(-4.0)
    assert s["max_win_streak"] == 1 and s["max_loss_streak"] == 1
    assert s["avg_duration_s"] == 700
    assert s["max_drawdown"] == pytest.approx(4.0) and s["max_drawdown_pct"] is None
    assert s["total_commission"] == pytest.approx(-0.8) and s["total_swap"] == 0.0


def test_summary_with_start_balance_and_no_losers(trades):
    assert summary(trades, start_balance=100.0)["max_drawdown_pct"] == pytest.approx(4 / 110 * 100, abs=0.01)
    winners = [t for t in trades if t.net > 0]
    s = summary(winners)
    assert s["profit_factor"] is None and s["payoff_ratio"] is None and s["max_loss_streak"] == 0
    assert summary([])["trades"] == 0 and summary([])["win_rate"] == 0.0


def test_breakdowns(trades):
    by_side = breakdown(trades, "side")
    assert set(by_side) == {"BUY", "SELL"}
    assert by_side["BUY"]["trades"] == 2 and by_side["BUY"]["net"] == pytest.approx(16.0)
    assert breakdown(trades, "symbol")["XAGUSD"]["net"] == pytest.approx(-4.0)
    assert set(breakdown(trades, "reason")) == {"TP", "SL", "manual"}
    assert list(breakdown(trades, "weekday")) == ["Thu"]
    assert list(breakdown(trades, "hour")) == ["0"]
    with pytest.raises(ValueError):
        breakdown(trades, "nope")


def test_daily_curve_and_drawdown(trades):
    assert daily_pnl(trades) == [{"date": "1970-01-01", "net": pytest.approx(12.0), "trades": 3}]
    curve = equity_curve(trades)
    assert [round(p["cum"], 2) for p in curve] == [10.0, 6.0, 12.0]
    assert drawdown(curve) == (pytest.approx(4.0), None)
    assert drawdown([]) == (0.0, None)


def test_build_analytics_is_json_serialisable(trades):
    a = build_analytics(trades, start_balance=100.0, equity_snapshots=[{"time": 1, "equity": 100.0}])
    assert set(a) >= {"summary", "by_symbol", "by_side", "by_reason", "by_hour", "by_weekday",
                      "daily", "equity_curve", "equity_snapshots"}
    assert a["summary"]["trades"] == 3 and a["equity_snapshots"][0]["equity"] == 100.0
    json.dumps(a)


from analytics import trade_dicts  # noqa: E402


def test_trades_carry_magic_and_engine_name(trades):
    assert all(t.magic == 777 for t in trades)
    rows = trade_dicts(trades, 10, {777: "scalper"})
    assert rows[0]["engine"] == "scalper"
    assert trade_dicts(trades, 10)[0]["engine"] == "other"
