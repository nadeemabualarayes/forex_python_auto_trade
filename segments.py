"""Segmented digest of replayed trades: where and when the strategy actually has an edge.

Pure functions over `backtest.SimTrade`-like objects (side, entry_time, pnl, r, atr, penetration).
Every segment reports the same metrics so sessions, directions, volatility regimes, months,
news distance and Bollinger penetration depth can be compared side by side. Nothing here
changes the strategy; it only reads what the backtester already replayed.
"""
import calendar
from collections import OrderedDict

import numpy as np

from news import blocking_event

SESSION_BUCKETS = ("00-07", "07-12", "12-17", "17-24")           # server hours
DIRECTIONS = ("LONG", "SHORT")
ATR_REGIMES = ("LOW", "NORMAL", "HIGH")
PENETRATION_BUCKETS = ("touch", "small", "medium", "deep", "n/a")   # ATR units beyond the band
NEWS_BUCKETS = ("safe", "near news", "news window", "no calendar")
CALENDAR_REACH_S = 7 * 86400                                       # a trade this far from any event has no calendar


# -- Metrics ------------------------------------------------------------------------
def metrics(trades) -> dict:
    """The per-segment scorecard. Expectancy is per trade, in $ and in R (pnl / risk at the stop)."""
    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "expectancy": 0.0, "expectancy_r": 0.0, "max_drawdown": 0.0,
                "max_consecutive_losses": 0}
    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    equity = np.concatenate([[0.0], np.cumsum(pnls)])
    drawdown = np.maximum.accumulate(equity) - equity
    gp, gl = wins.sum(), -losses.sum()
    rs = [t.r for t in trades if getattr(t, "r", None) is not None]
    streak = worst = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        worst = max(worst, streak)
    return {
        "trades": int(len(pnls)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "net": round(float(pnls.sum()), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(gp / gl), 2) if gl > 0 else float("inf"),
        "expectancy": round(float(pnls.mean()), 2),
        "expectancy_r": round(float(np.mean(rs)), 2) if rs else 0.0,
        "max_drawdown": round(float(drawdown.max()), 2),
        "max_consecutive_losses": int(worst),
    }


# -- Labelers ------------------------------------------------------------------------
def session_bucket(t) -> str:
    h = t.entry_time.hour
    return "00-07" if h < 7 else "07-12" if h < 12 else "12-17" if h < 17 else "17-24"


def direction(t) -> str:
    return "LONG" if t.side == "BUY" else "SHORT"


def month(t) -> str:
    return f"{t.entry_time.year:04d}-{t.entry_time.month:02d}"


def atr_thresholds(atrs):
    """(low, high) tercile cut-offs of a set of ATR values, or None when there are none."""
    vals = [float(a) for a in atrs if a is not None and not np.isnan(a)]
    if not vals:
        return None
    low, high = np.quantile(vals, [1 / 3, 2 / 3])
    return float(low), float(high)


def atr_regime(t, thresholds) -> str:
    if thresholds is None or getattr(t, "atr", None) is None:
        return "NORMAL"
    low, high = thresholds
    return "LOW" if t.atr < low else "HIGH" if t.atr >= high else "NORMAL"


def penetration_bucket(t) -> str:
    """How far the signal bar closed beyond its Bollinger band, in ATR units."""
    p = getattr(t, "penetration", None)
    if p is None:
        return "n/a"
    return "touch" if p < 0.1 else "small" if p < 0.3 else "medium" if p < 0.6 else "deep"


def news_distance(t, events, before_s, after_s, near_s: float = 3600, server_offset_s: float = 0) -> str:
    """Where the entry sits relative to the calendar: inside the blackout window, within `near_s` of a
    release, safe, or outside the calendar's coverage. entry_time is server time; events are UTC."""
    if not events:
        return "no calendar"
    utc = calendar.timegm(t.entry_time.timetuple()) - server_offset_s
    if all(abs(e.time_utc - utc) > CALENDAR_REACH_S for e in events):
        return "no calendar"
    if blocking_event(events, utc, before_s, after_s) is not None:
        return "news window"
    if any(abs(e.time_utc - utc) <= near_s for e in events):
        return "near news"
    return "safe"


# -- Grouping ------------------------------------------------------------------------
def segment(trades, key, order=None) -> "OrderedDict[str, dict]":
    """label -> metrics. With `order`, every listed label appears (empty ones included) in that order;
    without it, labels appear sorted and only when populated."""
    groups = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    labels = list(order) if order is not None else sorted(groups)
    if order is not None:
        labels += [k for k in sorted(groups) if k not in labels]
    return OrderedDict((label, metrics(groups.get(label, []))) for label in labels)


def cross(trades, key_a, key_b) -> "OrderedDict[tuple, dict]":
    """(label_a, label_b) -> metrics, populated cells only, sorted."""
    groups = {}
    for t in trades:
        groups.setdefault((key_a(t), key_b(t)), []).append(t)
    return OrderedDict((k, metrics(groups[k])) for k in sorted(groups))


def build_digest(trades, atr_thresholds=None, events=None, news_before_s=15 * 60, news_after_s=15 * 60,
                 server_offset_s: float = 0) -> dict:
    """Every section of the digest as plain dicts. ATR terciles default to the trades' own ATRs;
    pass the period's bar ATR terciles for a market-wide regime split."""
    trades = list(trades)
    cuts = atr_thresholds if atr_thresholds is not None else globals()["atr_thresholds"](t.atr for t in trades)

    def regime(t):
        return atr_regime(t, cuts)

    def news(t):
        return news_distance(t, events or [], news_before_s, news_after_s, server_offset_s=server_offset_s)

    return {
        "overall": metrics(trades),
        "atr_thresholds": cuts,
        "by_session": segment(trades, session_bucket, SESSION_BUCKETS) if trades else OrderedDict(),
        "by_direction": segment(trades, direction, DIRECTIONS) if trades else OrderedDict(),
        "by_atr_regime": segment(trades, regime, ATR_REGIMES) if trades else OrderedDict(),
        "by_month": segment(trades, month),
        "by_news": segment(trades, news),
        "by_penetration": segment(trades, penetration_bucket),
        "session_x_direction": cross(trades, session_bucket, direction),
        "session_x_atr": cross(trades, session_bucket, regime),
        "direction_x_atr": cross(trades, direction, regime),
    }


# -- Text report ---------------------------------------------------------------------
COLUMNS = (("trades", 7, "d"), ("wins", 6, "d"), ("losses", 7, "d"), ("win_rate", 6, ".1f"), ("net", 9, "+.2f"),
           ("profit_factor", 6, ".2f"), ("avg_win", 8, ".2f"), ("avg_loss", 8, ".2f"), ("expectancy", 7, "+.2f"),
           ("expectancy_r", 6, "+.2f"), ("max_drawdown", 8, ".2f"), ("max_consecutive_losses", 7, "d"))
HEADINGS = ("trades", "wins", "losses", "win%", "net", "PF", "avgWin", "avgLoss", "exp$", "expR", "maxDD", "streak")
LABEL_W = 22


def _row(label: str, m: dict) -> str:
    cells = []
    for (key, width, fmt), _ in zip(COLUMNS, HEADINGS):
        v = m[key]
        text = "inf" if v == float("inf") else format(v, fmt)
        cells.append(text.rjust(width))
    return f"{label:<{LABEL_W}}" + "".join(cells)


def _header() -> str:
    return " " * LABEL_W + "".join(h.rjust(w) for (_, w, _), h in zip(COLUMNS, HEADINGS))


def _section(title: str, rows: dict) -> list:
    out = [title, _header()]
    if not rows:
        out.append("  (no trades)")
    for label, m in rows.items():
        name = " x ".join(label) if isinstance(label, tuple) else str(label)
        out.append(_row(name, m))
    out.append("")
    return out


def format_digest(symbol: str, days: int, digest: dict) -> str:
    """Plain-text tree of the whole digest for the console, a file, or a <pre> block."""
    cuts = digest.get("atr_thresholds")
    atr_note = (f"ATR regime cut-offs (terciles of the period's bar ATR): LOW below {cuts[0]:.4g}, "
                f"HIGH from {cuts[1]:.4g}" if cuts else "ATR regime cut-offs: n/a")
    lines = [f"{symbol} - {days} DAYS", atr_note,
             "penetration = signal-bar close beyond the band, in ATR: touch under 0.1, small under 0.3, "
             "medium under 0.6, deep beyond", ""]
    lines += _section("OVERALL", {"all": digest["overall"]})
    lines += _section("BY SESSION (server hours)", digest["by_session"])
    lines += _section("BY DIRECTION", digest["by_direction"])
    lines += _section("BY ATR REGIME", digest["by_atr_regime"])
    lines += _section("BY MONTH", digest["by_month"])
    lines += _section("BY NEWS DISTANCE", digest["by_news"])
    lines += _section("BY BB PENETRATION", digest["by_penetration"])
    lines += _section("SESSION x DIRECTION", digest["session_x_direction"])
    lines += _section("SESSION x ATR", digest["session_x_atr"])
    lines += _section("DIRECTION x ATR", digest["direction_x_atr"])
    return "\n".join(lines).rstrip() + "\n"
