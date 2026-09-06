"""Replay the live signal code over MT5 history.

    python backtest.py --symbol XAUUSD [XAGUSD ...] --days 60 [--csv out.csv] [--telegram]

Simulates: trend + session filters, daily trade cap, daily loss / loss-streak breaker,
ATR SL/TP resolved against later highs/lows (SL wins if both hit in one bar),
one position at a time, entry at next bar open +/- half spread.
Breakeven + ATR trailing stop are applied on each bar close (config.MANAGE_POSITIONS).
Not simulated: slippage, commission, swap.
"""
import argparse
import csv
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from strategy import generate_signal, in_session, build_levels
from technicals import compute_indicators, compute_trend, attach_trend
from position_manager import next_stop


@dataclass
class SimTrade:
    symbol: str
    side: str
    entry_time: object
    entry: float
    sl: float
    tp: float
    lot: float
    exit_time: object = None
    exit: float = 0.0
    reason: str = ""
    pnl: float = 0.0


# -- Pure simulation ------------------------------------------------------------
def resolve_exit(df: pd.DataFrame, start: int, side: str, sl: float, tp: float,
                 entry: float | None = None, manage: bool = False, point: float = 0.01):
    """Scan bars from `start`; return (idx, price, reason) or None if never closed.

    With `manage`, the live breakeven/trail rule is applied on every bar close (the
    bar's high/low are checked against the stop that was in force when the bar opened).
    """
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    atrs = df["atr"].values if manage else None
    moved = False
    for j in range(start, len(df)):
        if side == "BUY":
            if lows[j] <= sl:
                return j, sl, "TRAIL" if moved else "SL"
            if highs[j] >= tp:
                return j, tp, "TP"
        else:
            if highs[j] >= sl:
                return j, sl, "TRAIL" if moved else "SL"
            if lows[j] <= tp:
                return j, tp, "TP"
        if manage and entry is not None:
            atr = float(atrs[j])
            new_sl = next_stop(side, entry, sl, float(closes[j]), atr,
                               config.BREAKEVEN_ATR, config.TRAIL_ATR, max(point * 5, atr * 0.05))
            if new_sl is not None:
                sl, moved = new_sl, True
    return None


def run_backtest(df: pd.DataFrame, symbol: str, spread_price: float, tick_size: float,
                 tick_value: float, lot_fn) -> list:
    """df must already carry indicators (and trend_ema if the filter is on)."""
    trades = []
    rows = df.to_dict("records")                       # plain dicts: ~10x faster than df.iloc per bar
    times = df["time"].values
    day, entries_today, pnl_today, streak = None, 0, 0.0, 0
    i = 1
    while i < len(df) - 1:
        bar = rows[i]
        i += 1
        if np.isnan(bar["atr"]):
            continue
        t = bar["time"]
        if t.date() != day:
            day, entries_today, pnl_today, streak = t.date(), 0, 0.0, 0
        if not in_session(t):
            continue
        if entries_today >= config.MAX_TRADES_PER_DAY:
            continue
        if pnl_today <= -config.MAX_DAILY_LOSS_USD or streak >= config.MAX_CONSECUTIVE_LOSSES:
            continue
        side = generate_signal(bar)
        if not side:
            continue

        mid = float(rows[i]["open"])                    # bar after the signal bar
        lv = build_levels(side, mid + spread_price / 2, mid - spread_price / 2, float(bar["atr"]))
        lot = lot_fn(lv.sl_dist)
        if lot <= 0:
            continue
        entries_today += 1
        res = resolve_exit(df, i, side, lv.sl, lv.tp, entry=lv.entry,
                           manage=config.MANAGE_POSITIONS, point=tick_size)
        if res is None:
            break                                       # still open at end of data
        j, px, reason = res
        move = (px - lv.entry) if side == "BUY" else (lv.entry - px)
        pnl = move / tick_size * tick_value * lot
        trades.append(SimTrade(symbol, side, t, lv.entry, lv.sl, lv.tp, lot,
                               pd.Timestamp(times[j]), px, reason, round(pnl, 2)))
        pnl_today += pnl
        streak = streak + 1 if pnl < 0 else 0
        i = j + 1                                       # next signal bar is the closing bar
    return trades


def summarize(trades: list) -> dict:
    if not trades:
        return {"trades": 0}
    pnls = np.array([t.pnl for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    equity = np.cumsum(pnls)
    drawdown = np.maximum.accumulate(np.concatenate([[0.0], equity])) - np.concatenate([[0.0], equity])
    gp, gl = wins.sum(), -losses.sum()
    return {
        "trades": len(trades),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "net": round(pnls.sum(), 2),
        "avg_win": round(wins.mean(), 2) if len(wins) else 0.0,
        "avg_loss": round(losses.mean(), 2) if len(losses) else 0.0,
        "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf"),
        "max_drawdown": round(drawdown.max(), 2),
        "tp_exits": sum(t.reason == "TP" for t in trades),
        "sl_exits": sum(t.reason == "SL" for t in trades),
        "trail_exits": sum(t.reason == "TRAIL" for t in trades),
    }


def format_report(days: int, per_symbol: dict) -> str:
    """Telegram (HTML) digest of one or more symbol backtests: {symbol: summarize(...)}."""
    lines = [f"<b>BACKTEST</b> last {days} days (to {datetime.now():%Y-%m-%d})",
             f"trend={config.TREND_FILTER_ENABLED} session={config.SESSION_FILTER_ENABLED} "
             f"candles={config.CANDLE_MODE} manage={config.MANAGE_POSITIONS} "
             f"risk ${config.RISK_USD_PER_TRADE:g}/trade"]
    total = 0.0
    for symbol, s in per_symbol.items():
        if not s.get("trades"):
            lines.append(f"<b>{symbol}</b>: no trades")
            continue
        total += s["net"]
        lines.append(f"<b>{symbol}</b>: {s['trades']} trades, {s['win_rate']}% win, "
                     f"net {s['net']:+.2f}, PF {s['profit_factor']}, maxDD {s['max_drawdown']:.2f} "
                     f"(TP {s['tp_exits']} / SL {s['sl_exits']} / trail {s['trail_exits']})")
    lines.append(f"<b>Total</b> net {total:+.2f}")
    lines.append("<i>Not simulated: news blackout, slippage, commission, swap.</i>")
    return "\n".join(lines)


def history_spread(df: pd.DataFrame, fallback_points: float, point: float) -> float:
    """Median bar spread in price units; brokers that store 0 in history fall back to the live spread."""
    median = float(df["spread"].median()) if "spread" in df else 0.0
    return (median if median > 0 else float(fallback_points)) * point


# -- Data + CLI ------------------------------------------------------------------
def load_history(symbol: str, days: int):
    import MetaTrader5 as mt5
    from execution import get_rates_range, lot_for_risk

    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        raise SystemExit(f"unknown symbol {symbol}")
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    df = get_rates_range(symbol, config.TIMEFRAME, start, end)
    htf = get_rates_range(symbol, config.TREND_TIMEFRAME, start - timedelta(days=45), end)
    mt5.shutdown()
    if df is None or len(df) < 100:
        raise SystemExit("not enough signal-TF history (check Max bars in chart in MT5 options)")
    df = compute_indicators(df)
    if config.TREND_FILTER_ENABLED:
        if htf is None or len(htf) < config.TREND_EMA_PERIOD:
            raise SystemExit("not enough higher-TF history for the trend EMA")
        df = attach_trend(df, compute_trend(htf))
    spread_price = history_spread(df, info.spread, info.point)

    def lot_fn(sl_dist):
        return lot_for_risk(sl_dist, config.RISK_USD_PER_TRADE, info.trade_tick_size,
                            info.trade_tick_value, info.volume_min, info.volume_max, info.volume_step)

    return df, spread_price, info.trade_tick_size, info.trade_tick_value, lot_fn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", nargs="+", default=[config.SYMBOLS[0]],
                    help="one or more symbols (default: first of config.SYMBOLS)")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--csv", help="write trade list to this CSV file")
    ap.add_argument("--no-trend", action="store_true", help="disable the trend filter")
    ap.add_argument("--no-session", action="store_true", help="disable the session filter")
    ap.add_argument("--telegram", action="store_true", help="send the summary to the Telegram chat")
    args = ap.parse_args()
    if args.no_trend:
        config.TREND_FILTER_ENABLED = False
    if args.no_session:
        config.SESSION_FILTER_ENABLED = False

    all_trades, per_symbol = [], {}
    for symbol in args.symbol:
        df, spread, tick_size, tick_value, lot_fn = load_history(symbol, args.days)
        print(f"{symbol}: {len(df)} bars {df['time'].iloc[0]} -> {df['time'].iloc[-1]}, "
              f"median spread {spread:.5g}, trend={config.TREND_FILTER_ENABLED} session={config.SESSION_FILTER_ENABLED}")
        trades = run_backtest(df, symbol, spread, tick_size, tick_value, lot_fn)
        per_symbol[symbol] = summarize(trades)
        for k, v in per_symbol[symbol].items():
            print(f"{k:>14}: {v}")
        all_trades.extend(trades)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(all_trades[0]).keys()) if all_trades else ["symbol"])
            w.writeheader()
            for t in all_trades:
                w.writerow(asdict(t))
        print(f"wrote {len(all_trades)} trades to {args.csv}")
    if args.telegram:
        from telegram_notifier import send_telegram
        send_telegram(format_report(args.days, per_symbol))
        print("summary sent to Telegram")


if __name__ == "__main__":
    main()
