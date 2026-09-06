"""MT5 bridge: connection, rates, sizing, orders, SL modification."""
import math
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

import config
from journal import log, record_trade
from telegram_notifier import send_telegram


# -- Connection ---------------------------------------------------------------
def init_mt5(symbols) -> list:
    """Initialize the terminal and select symbols. Returns the symbols that were selected."""
    if not mt5.initialize():
        log.error("MT5 initialization failed: %s", mt5.last_error())
        return []
    ok = []
    for s in symbols:
        if mt5.symbol_select(s, True):
            ok.append(s)
        else:
            log.error("Symbol %s not available on this server, skipping", s)
    return ok


# -- Data ---------------------------------------------------------------------
def _to_df(rates):
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_rates(symbol: str, timeframe, n: int = 120):
    return _to_df(mt5.copy_rates_from_pos(symbol, timeframe, 0, n))


def get_rates_range(symbol: str, timeframe, date_from: datetime, date_to: datetime):
    return _to_df(mt5.copy_rates_range(symbol, timeframe, date_from, date_to))


def spread_points(symbol: str):
    """Current spread in points, or None if there is no live quote."""
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None or info.point == 0 or tick.time == 0:
        return None
    return (tick.ask - tick.bid) / info.point


def bot_positions(symbol=None) -> list:
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return [p for p in (positions or ()) if p.magic == config.MAGIC_NUMBER]


# -- Sizing -------------------------------------------------------------------
def lot_for_risk(sl_distance_price: float, risk_usd: float, tick_size: float, tick_value: float,
                 volume_min: float, volume_max: float, volume_step: float) -> float:
    """Pure sizing: largest lot (floored to step) whose loss at SL <= risk_usd. 0.0 if none fits."""
    if sl_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    loss_per_lot = (sl_distance_price / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0
    step = volume_step or 0.01
    lot = math.floor((risk_usd / loss_per_lot) / step + 1e-9) * step
    lot = min(volume_max, lot)
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    lot = round(lot, decimals)
    if lot < volume_min:
        return 0.0
    return lot


def calculate_dynamic_lot(symbol: str, sl_distance_price: float, risk_usd: float) -> float:
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    lot = lot_for_risk(sl_distance_price, risk_usd, info.trade_tick_size, info.trade_tick_value,
                       info.volume_min, info.volume_max, info.volume_step)
    if lot == 0.0 and info.trade_tick_size > 0:
        min_risk = info.volume_min * (sl_distance_price / info.trade_tick_size) * info.trade_tick_value
        log.info("[%s] SKIP: min lot %s would risk $%.2f > budget $%.2f",
                 symbol, info.volume_min, min_risk, risk_usd)
    return lot


# -- Orders -------------------------------------------------------------------
def _pick_filling_mode(info) -> int:
    # symbol_info().filling_mode is a bitmask: 1 = FOK, 2 = IOC (MQL5 SYMBOL_FILLING_*).
    # The Python package does not expose these constants, so they are spelled out here.
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    flags = info.filling_mode
    if flags & SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if flags & SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def send_market_order(action_type: str, symbol: str, lot: float, price: float, sl: float, tp: float) -> bool:
    """Send a market order. Returns True on fill. Never raises on MT5 None returns."""
    info = mt5.symbol_info(symbol)
    if info is None:
        log.error("[%s] symbol_info returned None; order not sent", symbol)
        send_telegram(f"<b>Order not sent</b>\nsymbol_info({symbol}) returned None")
        return False

    digits = info.digits
    order_type = mt5.ORDER_TYPE_BUY if action_type == "BUY" else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": round(price, digits),
        "sl": round(sl, digits),
        "tp": round(tp, digits),
        "deviation": 10,
        "magic": config.MAGIC_NUMBER,
        "comment": f"AlgoBot-{symbol}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(info),
    }

    res = mt5.order_send(request)
    if res is None:
        err = mt5.last_error()
        log.error("[%s] order_send returned None (terminal disconnected?) last_error=%s", symbol, err)
        record_trade("REJECTED", symbol, action_type, lot, price, sl, tp, note=f"order_send None {err}")
        send_telegram(f"\U0001F534 <b>Order failed: {action_type} {symbol}</b>\norder_send returned None: {err}")
        return False

    if res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("[%s] EXECUTED %s lot=%s entry=%.*f sl=%.*f tp=%.*f ticket=%s",
                 symbol, action_type, lot, digits, price, digits, sl, digits, tp, res.order)
        record_trade("ENTRY", symbol, action_type, lot, round(price, digits), round(sl, digits),
                     round(tp, digits), ticket=res.order)
        send_telegram(
            f"\U0001F7E2 <b>Trade Opened: {action_type}</b>\n\n"
            f"▪ <b>Asset:</b> {symbol}\n"
            f"▪ <b>Lot:</b> {lot}\n"
            f"▪ <b>Entry:</b> {price:.{digits}f}\n"
            f"▪ <b>SL:</b> {sl:.{digits}f}\n"
            f"▪ <b>TP:</b> {tp:.{digits}f}\n"
            f"▪ <b>Risk Budget:</b> ${config.RISK_USD_PER_TRADE:.2f}"
        )
        return True

    log.warning("[%s] REJECTED %s lot=%s retcode=%s %s", symbol, action_type, lot, res.retcode, res.comment)
    record_trade("REJECTED", symbol, action_type, lot, price, sl, tp, note=f"{res.retcode} {res.comment}")
    send_telegram(f"\U0001F534 <b>Order rejected: {action_type} {symbol}</b>\n▪ retcode {res.retcode}\n▪ {res.comment}")
    return False


def modify_sl(position, new_sl: float) -> bool:
    """Move the stop loss of an open position (TP unchanged)."""
    info = mt5.symbol_info(position.symbol)
    if info is None:
        return False
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": round(new_sl, info.digits),
        "tp": position.tp,
        "magic": config.MAGIC_NUMBER,
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning("[%s] SL modify failed for #%s: %s", position.symbol,
                    position.ticket, getattr(res, "comment", mt5.last_error()))
        return False
    return True
