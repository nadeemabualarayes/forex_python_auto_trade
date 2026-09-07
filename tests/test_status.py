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
                               "sl": 2395.0, "tp": 2410.0, "profit": 1.5, "ticket": 123, "engine": "other"}]
    assert s["traders"] == [{"symbol": "XAUUSD", "state": "position open", "last_signal_bar": None, "engine": "scalper"},
                            {"symbol": "XAGUSD", "state": "watching", "last_signal_bar": "2026-09-07 14:25", "engine": "scalper"}]
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


def _chart_df():
    import numpy as np
    import pandas as pd
    return pd.DataFrame({
        "time": pd.to_datetime([1_800_000_000 + i * 300 for i in range(5)], unit="s"),
        "open": [10.0, 10.2, 10.1, 10.4, 10.3], "high": [10.3, 10.4, 10.5, 10.6, 10.5],
        "low": [9.8, 10.0, 10.0, 10.2, 10.2], "close": [10.2, 10.1, 10.4, 10.3, 10.4],
        "upper_band": [np.nan, 10.6, 10.7, 10.8, 10.8], "sma": [np.nan, 10.2, 10.3, 10.4, 10.4],
        "lower_band": [np.nan, 9.8, 9.9, 10.0, 10.0], "rsi": [np.nan, 28.0, 45.0, 72.0, 50.0],
        "buy_setup": [False, True, False, False, False], "sell_setup": [False, False, False, True, False],
        "bull_pattern": ["", "hammer", "", "doji", ""], "bear_pattern": ["", "", "", "doji", ""],
        "trend_ema": [np.nan, 10.0, 10.0, 10.5, 10.5],
    })


def test_chart_block_uses_closed_bars_and_marks_patterns(monkeypatch):
    from status import chart_block
    monkeypatch.setattr(config, "CANDLE_PATTERNS", ("hammer",))
    monkeypatch.setattr(config, "CANDLE_MODE", "confirm")
    pos = [SimpleNamespace(symbol="XAUUSD", type=0, volume=0.1, price_open=10.15, sl=9.9, tp=10.7, profit=0.5, ticket=1)]
    blk = chart_block(_chart_df(), "XAUUSD", pos, n=3)
    assert blk["timeframe"] == "M5" and blk["mode"] == "confirm" and blk["accepted"] == ["hammer"]
    assert [b["t"] for b in blk["bars"]] == ["2027-01-15 08:05", "2027-01-15 08:10", "2027-01-15 08:15"]  # forming bar dropped, last n
    b1 = blk["bars"][0]
    assert (b1["o"], b1["h"], b1["l"], b1["c"]) == (10.2, 10.4, 10.0, 10.1)
    assert b1["bb_u"] == 10.6 and b1["rsi"] == 28.0 and b1["bull"] == "hammer" and b1["bear"] == "" and b1["setup"] == "BUY"
    assert blk["bars"][2]["bear"] == "doji" and blk["bars"][2]["setup"] == "SELL"
    assert blk["trend_ema"] == 10.5 and blk["trend"] == "down"            # last closed close 10.3 < ema 10.5
    assert blk["position"] == {"side": "BUY", "entry": 10.15, "sl": 9.9, "tp": 10.7}
    assert blk["patterns"] == [
        {"t": "2027-01-15 08:15", "name": "doji", "dir": "neutral", "setup": True, "accepted": False},
        {"t": "2027-01-15 08:05", "name": "hammer", "dir": "bull", "setup": True, "accepted": True},
    ]
    import json
    json.dumps(blk)


def test_chart_block_handles_nan_and_missing_columns():
    from status import chart_block
    df = _chart_df().drop(columns=["trend_ema"])
    blk = chart_block(df, "XAGUSD", [], n=10)
    assert blk["bars"][0]["bb_u"] is None and blk["bars"][0]["rsi"] is None
    assert blk["trend_ema"] is None and blk["trend"] is None and blk["position"] is None
    assert chart_block(None, "XAGUSD", [], n=10) is None


def test_build_status_carries_news_block(monkeypatch):
    snap = {"enabled": True, "blocked": "news blackout: CPI m/m (USD) at 2026-09-11 12:30 UTC",
            "next": {"title": "CPI m/m", "currency": "USD", "time": "2026-09-11 12:30 UTC", "minutes_until": 10},
            "upcoming": [], "window_minutes": [15, 15], "last_ok": None, "stale": False, "error": None}
    s = build_status(now=None, stats=None, positions=[], traders=[], breaker=None, symbols=[],
                     started_at=0.0, now_mono=0.0, news=snap)
    assert s["news"]["blocked"].startswith("news blackout")
    assert s["news"]["next"]["title"] == "CPI m/m"
    s2 = build_status(now=None, stats=None, positions=[], traders=[], breaker=None, symbols=[],
                      started_at=0.0, now_mono=0.0)
    assert s2["news"]["enabled"] is False and s2["news"]["blocked"] is None


from types import SimpleNamespace as _NS  # noqa: E402

from status import engine_block  # noqa: E402


def test_engine_block_and_tags():
    eng = _NS(name="london", magic=998888, symbols=("EURUSD", "GBPUSD"), max_trades_per_day=2, max_consecutive_losses=4)
    blk = engine_block(eng, DailyStats(net_pnl=-3.0, consecutive_losses=1, entries=1, wins=0, losses=1), paused=None)
    assert blk == {"name": "london", "magic": 998888, "symbols": ["EURUSD", "GBPUSD"], "entries": 1, "max_entries": 2,
                   "net_pnl": -3.0, "wins": 0, "losses": 1, "consecutive_losses": 1, "max_consecutive_losses": 4,
                   "paused": None}
    pos = _pos()
    pos.magic = 998888
    trader = _trader("EURUSD")
    trader.engine = _NS(name="london")
    s = build_status(now=datetime(2026, 9, 7, 14, 30), stats=DailyStats(), positions=[pos, _pos()],
                     traders=[trader, _trader("XAUUSD")], breaker=None, symbols=["EURUSD", "XAUUSD"],
                     started_at=0.0, now_mono=1.0, engines=[blk])
    assert s["engines"] == [blk]
    assert [p["engine"] for p in s["positions"]] == ["london", "other"]
    assert [t["engine"] for t in s["traders"]] == ["london", "scalper"]
