"""Breakeven + ATR trailing stop for open bot positions."""
import numpy as np
import MetaTrader5 as mt5

import config
from execution import bot_positions, get_rates, modify_sl
from journal import log, record_trade
from technicals import compute_indicators


def next_stop(side: str, entry: float, current_sl: float, price: float, atr: float,
              be_atr: float, trail_atr: float, min_move: float) -> float | None:
    """Pure rule. Returns the new SL, or None if the stop should not move.

    side: "BUY" | "SELL". price: bid for BUY, ask for SELL.
    Stops only ever tighten. Breakeven first, then trail `trail_atr` behind price.
    """
    if atr <= 0 or np.isnan(atr):
        return None
    profit = (price - entry) if side == "BUY" else (entry - price)
    if profit < be_atr * atr:
        return None
    trail = price - trail_atr * atr if side == "BUY" else price + trail_atr * atr
    candidate = max(entry, trail) if side == "BUY" else min(entry, trail)
    if side == "BUY":
        improved = current_sl == 0 or candidate > current_sl + min_move
    else:
        improved = current_sl == 0 or candidate < current_sl - min_move
    return candidate if improved else None


def manage_positions() -> None:
    if not config.MANAGE_POSITIONS:
        return
    for p in bot_positions():
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None or tick.time == 0:
            continue
        df = get_rates(p.symbol, config.TIMEFRAME, n=config.ATR_PERIOD * 3)
        if df is None or len(df) < config.ATR_PERIOD + 2:
            continue
        atr = float(compute_indicators(df).iloc[-2]["atr"])
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        price = tick.bid if side == "BUY" else tick.ask
        min_move = max(info.point * 5, atr * 0.05)     # avoid modify spam on tiny ticks
        new_sl = next_stop(side, p.price_open, p.sl, price, atr,
                           config.BREAKEVEN_ATR, config.TRAIL_ATR, min_move)
        if new_sl is None:
            continue
        # Respect broker stop level distance from current price.
        stops_dist = info.trade_stops_level * info.point
        if (side == "BUY" and price - new_sl < stops_dist) or (side == "SELL" and new_sl - price < stops_dist):
            continue
        # First move that takes the trade out of risk is BREAKEVEN, later moves are TRAIL.
        old_sl = p.sl
        at_risk = old_sl == 0 or (side == "BUY" and old_sl < p.price_open) or (side == "SELL" and old_sl > p.price_open)
        tag = "BREAKEVEN" if at_risk else "TRAIL"
        if modify_sl(p, new_sl):
            log.info("[%s] %s #%s sl %.*f -> %.*f", p.symbol, tag, p.ticket,
                     info.digits, old_sl, info.digits, new_sl)
            record_trade("SL_MOVE", p.symbol, side, p.volume, round(price, info.digits),
                         round(new_sl, info.digits), p.tp, ticket=p.ticket, note=tag)
