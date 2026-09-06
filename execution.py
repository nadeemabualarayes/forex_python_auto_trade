import math
import MetaTrader5 as mt5
import pandas as pd
import config
from telegram_notifier import send_telegram


def init_mt5(symbol: str) -> bool:
    if not mt5.initialize():
        print(f"[ERROR] MT5 Initialization failed: {mt5.last_error()}")
        return False
    if not mt5.symbol_select(symbol, True):
        print(f"[ERROR] Symbol '{symbol}' not supported.")
        return False
    return True


def get_rates(symbol: str, timeframe, n: int = 120):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def calculate_dynamic_lot(symbol: str, sl_distance_price: float, risk_usd: float) -> float:
    """Return a lot size whose loss at SL does not exceed risk_usd.

    Returns 0.0 when no valid lot exists (missing symbol info, or the broker's
    minimum lot would already risk more than the budget).
    """
    info = mt5.symbol_info(symbol)
    if info is None or sl_distance_price <= 0:
        return 0.0

    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value
    if tick_size == 0 or tick_value == 0:
        return 0.0

    ticks_at_risk = sl_distance_price / tick_size
    loss_per_lot = ticks_at_risk * tick_value
    if loss_per_lot <= 0:
        return 0.0

    step = info.volume_step or 0.01
    raw_lot = risk_usd / loss_per_lot
    lot = math.floor(raw_lot / step) * step          # floor, never round up
    lot = min(info.volume_max, lot)

    # Round to the precision implied by volume_step (0.01 -> 2 dp, 0.001 -> 3 dp)
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    lot = round(lot, decimals)

    if lot < info.volume_min:
        min_lot_risk = info.volume_min * loss_per_lot
        print(f"[SKIP] Min lot {info.volume_min} would risk ${min_lot_risk:.2f} > budget ${risk_usd:.2f}")
        return 0.0
    return lot


def _pick_filling_mode(info) -> int:
    """Choose a filling mode the broker actually supports for this symbol."""
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
    """Send a market order. Returns True on fill, False otherwise. Never raises on MT5 None returns."""
    info = mt5.symbol_info(symbol)
    if info is None:
        msg = f"[ERROR] symbol_info({symbol}) returned None; order not sent"
        print(msg)
        send_telegram(f"⚠️ <b>Order not sent</b>\n{msg}")
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
        msg = f"[REJECTED] order_send returned None (terminal disconnected?) last_error={err}"
        print(msg)
        send_telegram(f"🔴 <b>Order failed: {action_type} {symbol}</b>\n{msg}")
        return False

    if res.retcode == mt5.TRADE_RETCODE_DONE:
        msg = (
            f"🟢 <b>Trade Opened: {action_type}!</b>\n\n"
            f"▪ <b>Asset:</b> {symbol}\n"
            f"▪ <b>Lot:</b> {lot}\n"
            f"▪ <b>Entry:</b> {price:.{digits}f}\n"
            f"▪ <b>SL:</b> {sl:.{digits}f}\n"
            f"▪ <b>TP:</b> {tp:.{digits}f}\n"
            f"▪ <b>Risk Budget:</b> ${config.RISK_USD_PER_TRADE:.2f}"
        )
        print(f"[EXECUTED] {action_type} on {symbol} (Lot: {lot})")
        send_telegram(msg)
        return True

    msg = f"[REJECTED] {action_type} {symbol} lot={lot} retcode={res.retcode} {res.comment}"
    print(msg)
    send_telegram(f"🔴 <b>Order rejected: {action_type} {symbol}</b>\n▪ retcode {res.retcode}\n▪ {res.comment}")
    return False
