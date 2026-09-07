"""Pure trade analytics: deals -> closed trades -> desk metrics. No MT5 calls."""
from collections import defaultdict
from dataclasses import dataclass, asdict

import MetaTrader5 as mt5

from risk import to_server_dt

_IN = mt5.DEAL_ENTRY_IN
_OUTS = (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT)
_REASONS = {
    getattr(mt5, "DEAL_REASON_SL", 4): "SL",
    getattr(mt5, "DEAL_REASON_TP", 5): "TP",
    getattr(mt5, "DEAL_REASON_CLIENT", 0): "manual",
    getattr(mt5, "DEAL_REASON_MOBILE", 1): "manual",
    getattr(mt5, "DEAL_REASON_WEB", 2): "manual",
    getattr(mt5, "DEAL_REASON_EXPERT", 3): "bot",
    getattr(mt5, "DEAL_REASON_SO", 6): "stopout",
}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
BREAKDOWN_KEYS = ("symbol", "side", "reason", "hour", "weekday")


@dataclass
class Trade:
    position_id: int
    symbol: str
    side: str            # BUY / SELL
    volume: float
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    gross: float         # sum of deal profit
    commission: float    # commission + fee (negative)
    swap: float
    net: float
    reason: str          # TP / SL / manual / bot / stopout / other
    duration_s: int
    hour: int            # server hour of entry
    weekday: int         # 0 = Monday
    magic: int = 0


def reason_name(code: int) -> str:
    return _REASONS.get(code, "other")


def _vwap(deals) -> float:
    vol = sum(d.volume for d in deals)
    return sum(d.price * d.volume for d in deals) / vol if vol else 0.0


def pair_trades(deals, volume_tol: float = 1e-6) -> list[Trade]:
    """Group deals by position; a trade is a position whose OUT volume covers its IN volume."""
    by_pos: dict[int, list] = defaultdict(list)
    for d in deals:
        by_pos[d.position_id].append(d)
    trades = []
    for pid, ds in by_pos.items():
        ds.sort(key=lambda d: (d.time, d.ticket))
        ins = [d for d in ds if d.entry == _IN]
        outs = [d for d in ds if d.entry in _OUTS]
        if not ins or not outs:
            continue
        vin = sum(d.volume for d in ins)
        vout = sum(d.volume for d in outs)
        if vout + volume_tol < vin:
            continue                                    # partially open
        gross = sum(d.profit for d in ds)
        commission = sum(d.commission + d.fee for d in ds)
        swap = sum(d.swap for d in ds)
        entry_time, exit_time = ins[0].time, outs[-1].time
        entry_dt = to_server_dt(entry_time)
        trades.append(Trade(
            position_id=pid, symbol=ins[0].symbol,
            side="BUY" if ins[0].type == mt5.DEAL_TYPE_BUY else "SELL", volume=vin,
            entry_time=entry_time, entry_price=round(_vwap(ins), 5), exit_time=exit_time,
            exit_price=round(_vwap(outs), 5), gross=round(gross, 2), commission=round(commission, 2),
            swap=round(swap, 2), net=round(gross + commission + swap, 2),
            reason=reason_name(outs[-1].reason), duration_s=int(exit_time - entry_time),
            hour=entry_dt.hour, weekday=entry_dt.weekday(),
            magic=int(ins[0].magic),
        ))
    trades.sort(key=lambda t: (t.exit_time, t.position_id))
    return trades


# -- metrics ------------------------------------------------------------------------
def equity_curve(trades) -> list[dict]:
    cum, out = 0.0, []
    for t in trades:
        cum += t.net
        out.append({"time": t.exit_time, "cum": round(cum, 2)})
    return out


def drawdown(curve, start_balance: float | None = None) -> tuple[float, float | None]:
    """Max peak-to-trough drop of the cumulative curve ($, and % of peak equity when the
    starting balance is known)."""
    peak = 0.0
    max_dd, max_pct = 0.0, None
    for p in curve:
        peak = max(peak, p["cum"])
        dd = peak - p["cum"]
        if dd > max_dd:
            max_dd = dd
        if start_balance:
            peak_eq = start_balance + peak
            pct = dd / peak_eq * 100 if peak_eq > 0 else 0.0
            max_pct = pct if max_pct is None else max(max_pct, pct)
    return round(max_dd, 2), (round(max_pct, 2) if max_pct is not None else None)


def summary(trades, start_balance: float | None = None) -> dict:
    n = len(trades)
    wins = [t.net for t in trades if t.net > 0]
    losses = [t.net for t in trades if t.net < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    net = sum(t.net for t in trades)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    win_streak = loss_streak = max_win = max_loss = 0
    for t in trades:
        if t.net > 0:
            win_streak, loss_streak = win_streak + 1, 0
        elif t.net < 0:
            loss_streak, win_streak = loss_streak + 1, 0
        else:
            win_streak = loss_streak = 0
        max_win, max_loss = max(max_win, win_streak), max(max_loss, loss_streak)
    max_dd, max_dd_pct = drawdown(equity_curve(trades), start_balance)
    return {
        "trades": n, "wins": len(wins), "losses": len(losses), "breakeven": n - len(wins) - len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "net": round(net, 2), "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(net / n, 2) if n else 0.0,
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "largest_win": round(max(wins), 2) if wins else 0.0,
        "largest_loss": round(min(losses), 2) if losses else 0.0,
        "max_win_streak": max_win, "max_loss_streak": max_loss,
        "avg_duration_s": int(sum(t.duration_s for t in trades) / n) if n else 0,
        "max_drawdown": max_dd, "max_drawdown_pct": max_dd_pct,
        "total_commission": round(sum(t.commission for t in trades), 2),
        "total_swap": round(sum(t.swap for t in trades), 2),
    }


def _group_key(t: Trade, key: str) -> str:
    if key == "weekday":
        return WEEKDAYS[t.weekday]
    return str(getattr(t, key))


def breakdown(trades, key: str, start_balance: float | None = None) -> dict[str, dict]:
    if key not in BREAKDOWN_KEYS:
        raise ValueError(f"unknown breakdown key {key!r}")
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        groups[_group_key(t, key)].append(t)
    if key == "hour":
        order = sorted(groups, key=int)
    elif key == "weekday":
        order = [w for w in WEEKDAYS if w in groups]
    else:
        order = sorted(groups)
    return {k: summary(groups[k], start_balance) for k in order}


def daily_pnl(trades) -> list[dict]:
    days: dict[str, dict] = {}
    for t in trades:
        day = to_server_dt(t.exit_time).strftime("%Y-%m-%d")
        rec = days.setdefault(day, {"date": day, "net": 0.0, "trades": 0})
        rec["net"] += t.net
        rec["trades"] += 1
    return [dict(r, net=round(r["net"], 2)) for r in (days[k] for k in sorted(days))]


def build_analytics(trades, start_balance: float | None = None, equity_snapshots=(),
                    max_daily: int = 90, max_curve: int = 1000) -> dict:
    """The `analytics` block of the dashboard snapshot."""
    return {
        "summary": summary(trades, start_balance),
        "start_balance": start_balance,
        "by_symbol": breakdown(trades, "symbol", start_balance),
        "by_side": breakdown(trades, "side"),
        "by_reason": breakdown(trades, "reason"),
        "by_hour": breakdown(trades, "hour"),
        "by_weekday": breakdown(trades, "weekday"),
        "daily": daily_pnl(trades)[-max_daily:],
        "equity_curve": equity_curve(trades)[-max_curve:],
        "equity_snapshots": list(equity_snapshots),
    }


def trade_dicts(trades, limit: int, engine_names: dict | None = None) -> list[dict]:
    """Newest first, capped, for the history table; each row is tagged with its engine name."""
    names = engine_names or {}
    out = []
    for t in reversed(trades[-limit:]):
        row = asdict(t)
        row["engine"] = names.get(t.magic, "other")
        out.append(row)
    return out
