"""Dashboard payload: pure builders so the web page's data is testable without a terminal."""
import csv
import math
import os
import time
from collections import deque
from datetime import datetime

import MetaTrader5 as mt5

import config

_TF_NAMES = {getattr(mt5, f"TIMEFRAME_{k}", None): k for k in ("M1", "M5", "M15", "M30", "H1", "H4", "D1")}


def _side(ptype) -> str:
    return "BUY" if ptype == 0 else "SELL"           # POSITION_TYPE_BUY == 0


def build_status(now: datetime | None, stats, positions, traders, breaker, symbols,
                 started_at: float, now_mono: float, account: dict | None = None,
                 analytics: dict | None = None, history: list | None = None,
                 charts: dict | None = None, news: dict | None = None) -> dict:
    """JSON-serialisable snapshot of one tick.

    now=None means no live quote (market closed); stats is then ignored."""
    day = {
        "net_pnl": round(stats.net_pnl, 2) if stats else 0.0,
        "wins": stats.wins if stats else 0,
        "losses": stats.losses if stats else 0,
        "win_rate": round(stats.win_rate, 1) if stats else 0.0,
        "entries": stats.entries if stats else 0,
        "max_entries": config.MAX_TRADES_PER_DAY,
        "consecutive_losses": stats.consecutive_losses if stats else 0,
        "max_consecutive_losses": config.MAX_CONSECUTIVE_LOSSES,
        "max_daily_loss": config.MAX_DAILY_LOSS_USD,
    }
    pos = [{
        "symbol": p.symbol, "side": _side(p.type), "volume": p.volume, "price_open": p.price_open,
        "sl": p.sl, "tp": p.tp, "profit": round(p.profit, 2), "ticket": p.ticket,
    } for p in positions]
    trd = [{
        "symbol": t.symbol,
        "state": t.last_skip_reason or "watching",
        "last_signal_bar": str(t.last_signal_bar) if t.last_signal_bar is not None else None,
    } for t in traders]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generated_epoch": time.time(),
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S") if now else None,
        "market_open": now is not None,
        "uptime_seconds": int(max(0.0, now_mono - started_at)),
        "symbols": list(symbols),
        "breaker": breaker,
        "day": day,
        "positions": pos,
        "open_pnl": round(sum(p["profit"] for p in pos), 2),
        "traders": trd,
        "account": account,
        "analytics": analytics,
        "history": history or [],
        "charts": charts or {},
        "news": news or {"enabled": False, "blocked": None, "next": None, "upcoming": []},
        "settings": {
            "risk_usd_per_trade": config.RISK_USD_PER_TRADE,
            "trend_filter": config.TREND_FILTER_ENABLED,
            "session_filter": config.SESSION_FILTER_ENABLED,
            "manage_positions": config.MANAGE_POSITIONS,
            "news_filter": config.NEWS_FILTER_ENABLED,
        },
    }


def _num(v):
    """float or None (NaN / missing -> None), rounded to 5 dp."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else round(f, 5)


def chart_block(df, symbol: str, positions, n: int | None = None) -> dict | None:
    """Closed signal-timeframe candles with bands, RSI, setup flags and candlestick patterns,
    plus the open position levels, for the dashboard's candle panel. None without data."""
    if df is None or len(df) < 2:
        return None
    n = n or config.CHART_BARS
    closed = df.iloc[:-1].tail(n)                     # last row is the forming bar
    cols = set(closed.columns)
    col = lambda r, c: _num(r[c]) if c in cols else None
    bars = []
    for _, r in closed.iterrows():
        bars.append({
            "t": r["time"].strftime("%Y-%m-%d %H:%M"),
            "o": _num(r["open"]), "h": _num(r["high"]), "l": _num(r["low"]), "c": _num(r["close"]),
            "bb_u": col(r, "upper_band"), "bb_m": col(r, "sma"), "bb_l": col(r, "lower_band"),
            "rsi": col(r, "rsi"),
            "bull": str(r["bull_pattern"]) if "bull_pattern" in cols and r["bull_pattern"] else "",
            "bear": str(r["bear_pattern"]) if "bear_pattern" in cols and r["bear_pattern"] else "",
            "setup": "BUY" if "buy_setup" in cols and bool(r["buy_setup"]) else
                     "SELL" if "sell_setup" in cols and bool(r["sell_setup"]) else "",
        })
    last = closed.iloc[-1]
    ema = col(last, "trend_ema")
    trend = None if ema is None else ("up" if float(last["close"]) >= ema else "down")
    pos = next((p for p in positions if p.symbol == symbol), None)
    position = None
    if pos is not None:
        position = {"side": _side(pos.type), "entry": _num(pos.price_open),
                    "sl": _num(pos.sl) or None, "tp": _num(pos.tp) or None}
    accepted = list(config.CANDLE_PATTERNS) if config.CANDLE_PATTERNS is not None else None
    patterns = []
    for b in reversed(bars):
        both = b["bull"] and b["bull"] == b["bear"]
        for name, d in ((b["bull"], "neutral" if both else "bull"), ("" if both else b["bear"], "bear")):
            if name:
                patterns.append({"t": b["t"], "name": name, "dir": d, "setup": bool(b["setup"]),
                                 "accepted": accepted is None or name in accepted})
        if len(patterns) >= 15:
            break
    return {
        "timeframe": _TF_NAMES.get(config.TIMEFRAME, str(config.TIMEFRAME)),
        "mode": config.CANDLE_MODE, "accepted": accepted,
        "bars": bars, "trend_ema": ema, "trend": trend, "position": position, "patterns": patterns,
    }


def with_trades(status: dict) -> dict:
    """Copy of the snapshot with the recent journal rows attached (what the page consumes)."""
    data = dict(status)
    data["trades"] = recent_trades(config.TRADE_JOURNAL, config.WEB_RECENT_TRADES)
    return data


def recent_trades(path: str, n: int) -> list[dict]:
    """Last n rows of the CSV journal, newest first. [] when the journal does not exist yet."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        tail = deque(csv.DictReader(f), maxlen=n)
    return list(reversed(tail))
