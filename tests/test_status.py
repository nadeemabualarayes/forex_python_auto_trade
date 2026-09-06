"""build_status / recent_trades are pure so the dashboard payload is testable without MT5."""
import csv
from datetime import datetime
from types import SimpleNamespace

import config
from risk import DailyStats
from status import build_status, recent_trades


def _pos(symbol="XAUUSD", ptype=0, profit=1.5):
    return SimpleNamespace(symbol=symbol, type=ptype, volume=0.05, price_open=2400.1,
                           sl=2395.0, tp=2410.0, profit=profit, ticket=123, time=1_800_000_000)


def _trader(symbol, reason=None, bar=None):
    return SimpleNamespace(symbol=symbol, last_skip_reason=reason, last_signal_bar=bar)


def test_build_status_open_market():
    stats = DailyStats(net_pnl=12.5, consecutive_losses=1, entries=3, wins=2, losses=1)
    s = build_status(
        now=datetime(2026, 9, 7, 14, 30), stats=stats, positions=[_pos()],
        traders=[_trader("XAUUSD", "position open"), _trader("XAGUSD", None, "2026-09-07 14:25")],
        breaker=None, symbols=["XAUUSD", "XAGUSD"], started_at=100.0, now_mono=160.0,
    )
    assert s["market_open"] is True
    assert s["server_time"] == "2026-09-07 14:30:00"
    assert s["uptime_seconds"] == 60
    assert s["breaker"] is None
    assert s["day"] == {"net_pnl": 12.5, "wins": 2, "losses": 1, "win_rate": 66.7, "entries": 3,
                        "max_entries": config.MAX_TRADES_PER_DAY, "consecutive_losses": 1,
                        "max_consecutive_losses": config.MAX_CONSECUTIVE_LOSSES,
                        "max_daily_loss": config.MAX_DAILY_LOSS_USD}
    assert s["positions"] == [{"symbol": "XAUUSD", "side": "BUY", "volume": 0.05, "price_open": 2400.1,
                               "sl": 2395.0, "tp": 2410.0, "profit": 1.5, "ticket": 123}]
    assert s["traders"] == [{"symbol": "XAUUSD", "state": "position open", "last_signal_bar": None},
                            {"symbol": "XAGUSD", "state": "watching", "last_signal_bar": "2026-09-07 14:25"}]
    assert s["open_pnl"] == 1.5


def test_build_status_market_closed_has_no_stats():
    s = build_status(now=None, stats=None, positions=[], traders=[], breaker=None,
                     symbols=["XAUUSD"], started_at=0.0, now_mono=5.0)
    assert s["market_open"] is False
    assert s["server_time"] is None
    assert s["day"]["net_pnl"] == 0.0 and s["day"]["entries"] == 0
    assert s["positions"] == [] and s["open_pnl"] == 0.0


def test_build_status_reports_breaker():
    s = build_status(now=datetime(2026, 9, 7), stats=DailyStats(), positions=[], traders=[],
                     breaker="daily loss limit hit", symbols=[], started_at=0.0, now_mono=0.0)
    assert s["breaker"] == "daily loss limit hit"


def test_recent_trades_newest_first_and_capped(tmp_path):
    path = tmp_path / "trades.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "symbol", "side", "lot", "price", "sl", "tp", "pnl", "ticket", "note"])
        for i in range(5):
            w.writerow([f"2026-09-07 10:0{i}:00", "ENTRY", "XAUUSD", "BUY", 0.01, 2400 + i, "", "", "", i, ""])
    rows = recent_trades(str(path), 3)
    assert [r["ticket"] for r in rows] == ["4", "3", "2"]
    assert rows[0]["price"] == "2404"


def test_recent_trades_missing_file(tmp_path):
    assert recent_trades(str(tmp_path / "nope.csv"), 10) == []


def test_build_status_embeds_account_analytics_history():
    import json
    s = build_status(now=None, stats=None, positions=[], traders=[], breaker=None, symbols=[],
                     started_at=0.0, now_mono=0.0,
                     account={"balance": 1000.0, "equity": 1001.5, "currency": "USD"},
                     analytics={"summary": {"trades": 1}}, history=[{"net": 1.5}])
    assert s["account"]["equity"] == 1001.5
    assert s["analytics"]["summary"]["trades"] == 1
    assert s["history"] == [{"net": 1.5}]
    json.dumps(s)


def test_build_status_defaults_without_history():
    s = build_status(now=None, stats=None, positions=[], traders=[], breaker=None, symbols=[],
                     started_at=0.0, now_mono=0.0)
    assert s["account"] is None and s["analytics"] is None and s["history"] == []
