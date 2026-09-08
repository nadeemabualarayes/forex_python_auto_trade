"""Replay the live signal code over MT5 history.

    python backtest.py --symbol XAUUSD [XAGUSD ...] --days 60 [--csv out.csv] [--segments] [--telegram]

Simulates: trend + session filters, daily trade cap, daily loss / loss-streak breaker,
ATR SL/TP resolved against later highs/lows (SL wins if both hit in one bar),
one position at a time, entry at next bar open +/- half spread.
Breakeven + ATR trailing stop are applied on each bar close (config.MANAGE_POSITIONS).
Not simulated: slippage, commission, swap.
--segments adds the segmented digest (segments.py): session, direction, ATR regime, month,
news distance, Bollinger penetration and their cross-tabs, written to LOG_DIR too.
"""
import argparse
import csv
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from strategy import generate_signal, in_session
from position_manager import next_stop
from engines import scalper_levels


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
    atr: float = None            # signal-bar ATR (volatility regime)
    penetration: float = None    # signal-bar close beyond the Bollinger band, in ATR units
    r: float = None              # pnl / risk at the initial stop


# -- Pure simulation ------------------------------------------------------------
def resolve_exit(df: pd.DataFrame, start: int, side: str, sl: float, tp: float,
                 entry: float | None = None, manage: bool = False, point: float = 0.01,
                 be_atr: float | None = None, trail_atr: float | None = None):
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
                               config.BREAKEVEN_ATR if be_atr is None else be_atr,
                               config.TRAIL_ATR if trail_atr is None else trail_atr,
                               max(point * 5, atr * 0.05))
            if new_sl is not None:
                sl, moved = new_sl, True
    return None


def run_backtest(df: pd.DataFrame, symbol: str, spread_price: float, tick_size: float,
                 tick_value: float, lot_fn, signal=None, levels=None, max_trades_per_day=None,
                 max_consecutive_losses=None, manage=None, be_atr=None, trail_atr=None) -> list:
    """df must already carry indicators (and trend_ema if the filter is on).

    Entry rule and levels are callables so any engine profile can be replayed; every optional
    parameter left at None uses the scalper's config value."""
    signal = signal or generate_signal
    levels = levels or scalper_levels
    cap = config.MAX_TRADES_PER_DAY if max_trades_per_day is None else max_trades_per_day
    max_streak = config.MAX_CONSECUTIVE_LOSSES if max_consecutive_losses is None else max_consecutive_losses
    manage = config.MANAGE_POSITIONS if manage is None else manage
    be_atr = config.BREAKEVEN_ATR if be_atr is None else be_atr
    trail_atr = config.TRAIL_ATR if trail_atr is None else trail_atr
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
        if entries_today >= cap:
            continue
        if pnl_today <= -config.MAX_DAILY_LOSS_USD or streak >= max_streak:
            continue
        side = signal(bar)
        if not side:
            continue

        mid = float(rows[i]["open"])                    # bar after the signal bar
        lv = levels(side, mid + spread_price / 2, mid - spread_price / 2, bar)
        if lv is None:
            continue
        lot = lot_fn(lv.sl_dist)
        if lot <= 0:
            continue
        entries_today += 1
        res = resolve_exit(df, i, side, lv.sl, lv.tp, entry=lv.entry, manage=manage, point=tick_size,
                           be_atr=be_atr, trail_atr=trail_atr)
        if res is None:
            break                                       # still open at end of data
        j, px, reason = res
        move = (px - lv.entry) if side == "BUY" else (lv.entry - px)
        pnl = move / tick_size * tick_value * lot
        risk = lv.sl_dist / tick_size * tick_value * lot
        trades.append(SimTrade(symbol, side, t, lv.entry, lv.sl, lv.tp, lot,
                               pd.Timestamp(times[j]), px, reason, round(pnl, 2),
                               atr=float(bar["atr"]), penetration=band_penetration(side, bar),
                               r=round(pnl / risk, 3) if risk > 0 else None))
        pnl_today += pnl
        streak = streak + 1 if pnl < 0 else 0
        i = j + 1                                       # next signal bar is the closing bar
    return trades


def band_penetration(side: str, bar) -> float | None:
    """How far the signal bar closed beyond its Bollinger band, in ATR units (None without bands)."""
    atr = bar.get("atr")
    band = bar.get("lower_band" if side == "BUY" else "upper_band")
    if atr is None or band is None or not atr or np.isnan(atr) or np.isnan(band):
        return None
    beyond = (band - bar["close"]) if side == "BUY" else (bar["close"] - band)
    return round(max(0.0, float(beyond) / float(atr)), 3)


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


def format_report(days: int, per_symbol: dict, engine_name: str = "scalper", engine=None) -> str:
    """Telegram (HTML) digest of one or more symbol backtests: {symbol: summarize(...)}."""
    name = engine.name if engine is not None else engine_name
    if engine is not None:
        candles = f" candles={config.CANDLE_MODE}" if engine.name == "scalper" else ""
        settings = (f"trend={engine.trend_filter} manage={engine.manage} "
                   f"risk ${engine.risk_usd:g}/trade{candles}")
    else:
        settings = (f"trend={config.TREND_FILTER_ENABLED} session={config.SESSION_FILTER_ENABLED} "
                   f"candles={config.CANDLE_MODE} manage={config.MANAGE_POSITIONS} "
                   f"risk ${config.RISK_USD_PER_TRADE:g}/trade")
    lines = [f"<b>BACKTEST {name}</b> last {days} days (to {datetime.now():%Y-%m-%d})", settings]
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


def run_spread(df: pd.DataFrame, fallback_points: float, point: float, override_points: float = None) -> float:
    """history_spread, unless override_points is given: then charge exactly that many points."""
    if override_points is not None:
        return override_points * point
    return history_spread(df, fallback_points, point)


# -- Data + CLI ------------------------------------------------------------------
def load_history(symbol: str, days: int, engine=None, spread_points: float = None):
    import MetaTrader5 as mt5
    from execution import get_rates_range, lot_for_risk, terminal_loss_per_lot
    if engine is None:
        from engines import scalper_engine
        engine = scalper_engine()

    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        raise SystemExit(f"unknown symbol {symbol}")
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    df = get_rates_range(symbol, engine.timeframe, start, end)
    htf = get_rates_range(symbol, config.TREND_TIMEFRAME, start - timedelta(days=45), end) if engine.trend_filter else None
    if df is None or len(df) < 100:
        raise SystemExit("not enough signal-TF history (check Max bars in chart in MT5 options)")
    if engine.trend_filter and (htf is None or len(htf) < config.TREND_EMA_PERIOD):
        raise SystemExit("not enough higher-TF history for the trend EMA")
    tick = mt5.symbol_info_tick(symbol)
    server_offset_s = (tick.time - time.time()) if tick is not None and tick.time else 0.0
    # Price one tick through the terminal: the SYMBOL_TRADE_TICK_VALUE field is 10x too low for the metals
    # on this broker, which would make the replay's lots (not its $ P&L per budget) ten times too large.
    price = tick.ask if tick is not None and tick.ask else (tick.bid if tick is not None else 0)
    one_tick = terminal_loss_per_lot(symbol, "BUY", price, info.trade_tick_size)
    tick_value = one_tick if one_tick else info.trade_tick_value
    if one_tick and abs(one_tick - info.trade_tick_value) > 0.01 * one_tick:
        print(f"{symbol}: tick value {info.trade_tick_value} reported, {one_tick:g} by the terminal; using the terminal")
    mt5.shutdown()
    df = engine.analyse(df, htf, info)
    spread_price = run_spread(df, info.spread, info.point, spread_points)

    def lot_fn(sl_dist):
        return lot_for_risk(sl_dist, engine.risk_usd, info.trade_tick_size,
                            tick_value, info.volume_min, info.volume_max, info.volume_step)

    return df, spread_price, info.trade_tick_size, tick_value, lot_fn, server_offset_s


def cached_calendar() -> list:
    """High-impact events from the news cache in LOG_DIR (usually only the current week)."""
    try:
        from news import NewsFilter
        return list(NewsFilter().events)
    except Exception:
        return []


def segment_report(symbol: str, days: int, trades: list, df: pd.DataFrame, engine, server_offset_s: float) -> str:
    """Build, print and save the segmented digest; returns its text."""
    from segments import build_digest, format_digest, atr_thresholds
    digest = build_digest(trades, atr_thresholds=atr_thresholds(df["atr"]), events=cached_calendar(),
                          news_before_s=config.NEWS_BLOCK_BEFORE_MIN * 60, news_after_s=config.NEWS_BLOCK_AFTER_MIN * 60,
                          server_offset_s=server_offset_s)
    text = format_digest(symbol, days, digest)
    print(text)
    os.makedirs(config.LOG_DIR, exist_ok=True)
    path = os.path.join(config.LOG_DIR, f"backtest_{engine.name}_{symbol}_{days}d_segments.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"digest written to {path}")
    return text


def telegram_chunks(text: str, limit: int = 3800) -> list:
    """Split a digest on blank lines into pieces that fit one Telegram message."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) > limit and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def main():
    from engines import scalper_engine
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["scalper", "london"], default="scalper")
    ap.add_argument("--symbol", nargs="+", help="one or more symbols (default: the engine's symbols)")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--csv", help="write trade list to this CSV file")
    ap.add_argument("--no-trend", action="store_true", help="disable the trend filter")
    ap.add_argument("--no-session", action="store_true", help="disable the session filter")
    ap.add_argument("--spread-points", type=float,
                    help="charge this spread in points instead of the history/live spread")
    ap.add_argument("--segments", action="store_true",
                    help="segmented digest (session/direction/ATR/month/news/penetration), also written to LOG_DIR")
    ap.add_argument("--telegram", action="store_true", help="send the summary (and digest) to the Telegram chat")
    args = ap.parse_args()
    if args.no_trend:
        config.TREND_FILTER_ENABLED = False
        config.LDN_TREND_FILTER = False
    if args.no_session:
        config.SESSION_FILTER_ENABLED = False
    if args.engine == "london":
        from engines import london_engine
        engine = london_engine()
    else:
        engine = scalper_engine()
    symbols = args.symbol or list(engine.symbols)

    all_trades, per_symbol, digests = [], {}, {}
    for symbol in symbols:
        df, spread, tick_size, tick_value, lot_fn, offset = load_history(symbol, args.days, engine, args.spread_points)
        source = "override" if args.spread_points is not None else "history"
        print(f"{engine.name} {symbol}: {len(df)} bars {df['time'].iloc[0]} -> {df['time'].iloc[-1]}, "
              f"spread {spread:.5g} ({source}), trend={engine.trend_filter} session={config.SESSION_FILTER_ENABLED}")
        trades = run_backtest(df, symbol, spread, tick_size, tick_value, lot_fn,
                              signal=engine.signal, levels=engine.levels,
                              max_trades_per_day=engine.max_trades_per_day,
                              max_consecutive_losses=engine.max_consecutive_losses,
                              manage=engine.manage, be_atr=engine.breakeven_atr, trail_atr=engine.trail_atr)
        per_symbol[symbol] = summarize(trades)
        for k, v in per_symbol[symbol].items():
            print(f"{k:>14}: {v}")
        if args.segments:
            digests[symbol] = segment_report(symbol, args.days, trades, df, engine, offset)
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
        send_telegram(format_report(args.days, per_symbol, engine=engine))
        for symbol, text in digests.items():
            for chunk in telegram_chunks(text):
                send_telegram(f"<pre>{chunk}</pre>")
        print("summary sent to Telegram")


if __name__ == "__main__":
    main()
