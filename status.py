"""Dashboard payload: pure builders so the web page's data is testable without a terminal."""
import csv
import os
from collections import deque
from datetime import datetime

import config


def _side(ptype) -> str:
    return "BUY" if ptype == 0 else "SELL"           # POSITION_TYPE_BUY == 0


def build_status(now: datetime | None, stats, positions, traders, breaker, symbols,
                 started_at: float, now_mono: float) -> dict:
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
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S") if now else None,
        "market_open": now is not None,
        "uptime_seconds": int(max(0.0, now_mono - started_at)),
        "symbols": list(symbols),
        "breaker": breaker,
        "day": day,
        "positions": pos,
        "open_pnl": round(sum(p["profit"] for p in pos), 2),
        "traders": trd,
        "settings": {
            "risk_usd_per_trade": config.RISK_USD_PER_TRADE,
            "trend_filter": config.TREND_FILTER_ENABLED,
            "session_filter": config.SESSION_FILTER_ENABLED,
            "manage_positions": config.MANAGE_POSITIONS,
        },
    }


def recent_trades(path: str, n: int) -> list[dict]:
    """Last n rows of the CSV journal, newest first. [] when the journal does not exist yet."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        tail = deque(csv.DictReader(f), maxlen=n)
    return list(reversed(tail))
