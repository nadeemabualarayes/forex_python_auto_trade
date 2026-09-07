"""MT5 bridge: connection, rates, sizing, orders, SL modification."""
import math
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

import config
from journal import log, record_trade
from telegram_notifier import send_telegram


# -- Connection ---------------------------------------------------------------
def mt5_init_args() -> tuple:
    """(args, kwargs) for mt5.initialize() from config.MT5_*.

    Empty settings attach to the default terminal on its current account (the original behaviour).
    MT5_PATH picks a specific terminal64.exe (launched if needed); MT5_LOGIN/PASSWORD/SERVER log that
    terminal into an account; MT5_PORTABLE runs it with its data folder next to the exe."""
    args = (config.MT5_PATH,) if config.MT5_PATH else ()
    kwargs = {}
    if config.MT5_LOGIN:
        kwargs.update(login=int(config.MT5_LOGIN), password=config.MT5_PASSWORD, server=config.MT5_SERVER)
    if config.MT5_PORTABLE:
        kwargs["portable"] = True
    return args, kwargs


def account_mismatch(account, expected_login) -> str | None:
    """Why trading must not start: the connected account is not the configured one. None = fine."""
    if not expected_login:
        return None
    if account is None:
        return "account info unavailable after login"
    if int(account.login) != int(expected_login):
        return f"connected to account {account.login}, expected {expected_login}"
    return None


def init_mt5(symbols) -> list:
    """Initialize the terminal and select symbols. Returns the symbols that were selected.

    Empty when the terminal cannot be reached or is logged into the wrong account."""
    args, kwargs = mt5_init_args()
    if not mt5.initialize(*args, **kwargs):
        log.error("MT5 initialization failed: %s", mt5.last_error())
        return []
    reason = account_mismatch(mt5.account_info(), config.MT5_LOGIN)
    if reason:
        log.error("refusing to trade: %s", reason)
        mt5.shutdown()
        return []
    ok = []
    for s in symbols:
        if mt5.symbol_select(s, True):
            ok.append(s)
            if verify_tick_value(s) is None:
                log.warning("[%s] tick value could not be verified against the terminal yet (no price?); "
                            "entries wait for terminal pricing", s)
        else:
            log.error("Symbol %s not available on this server, skipping", s)
    return ok


def trading_blockers(terminal, account) -> list[str]:
    """Why order_send would be rejected right now, from terminal_info()/account_info() snapshots.

    Empty list means trading is allowed. Pure so the startup guard is testable without a terminal."""
    reasons = []
    if terminal is None:
        reasons.append("terminal info unavailable (not connected to MT5)")
    else:
        if not terminal.connected:
            reasons.append("terminal is not connected to the trade server")
        if not terminal.trade_allowed:
            reasons.append("AutoTrading button is off in the terminal (orders rejected with retcode 10027)")
        if terminal.tradeapi_disabled:
            reasons.append("'Disable algorithmic trading via external Python API' is ticked in Options > Experts")
    if account is None:
        reasons.append("account info unavailable (not logged in)")
    else:
        if not account.trade_allowed:
            reasons.append("trading is disabled for this account on the server (retcode 10026)")
        if not account.trade_expert:
            reasons.append("algorithmic trading is not allowed for this account by the broker")
    return reasons


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


KNOWN_MAGICS: set = {config.MAGIC_NUMBER}      # every engine's magic; Bot registers them at start-up


def set_known_magics(magics) -> None:
    KNOWN_MAGICS.clear()
    KNOWN_MAGICS.update(int(m) for m in magics)


def bot_positions(symbol=None, magic=None) -> list:
    """Open positions of the bot's engines. magic: int, iterable of ints, or None = every known magic."""
    if magic is None:
        wanted = set(KNOWN_MAGICS)
    elif isinstance(magic, int):
        wanted = {magic}
    else:
        wanted = set(magic)
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return [p for p in (positions or ()) if p.magic in wanted]


# -- Sizing -------------------------------------------------------------------
def lot_for_loss(loss_per_lot: float, risk_usd: float, volume_min: float, volume_max: float,
                 volume_step: float) -> float:
    """Pure sizing: largest lot (floored to step) whose loss at SL <= risk_usd, given the loss on one lot.
    0.0 if even the minimum lot risks more than the budget."""
    if loss_per_lot <= 0 or risk_usd <= 0:
        return 0.0
    step = volume_step or 0.01
    lot = math.floor((risk_usd / loss_per_lot) / step + 1e-9) * step
    lot = min(volume_max, lot)
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    lot = round(lot, decimals)
    if lot < volume_min:
        return 0.0
    return lot


def lot_for_risk(sl_distance_price: float, risk_usd: float, tick_size: float, tick_value: float,
                 volume_min: float, volume_max: float, volume_step: float) -> float:
    """Pure sizing from a tick value: loss on one lot = ticks to the stop x tick_value."""
    if sl_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    return lot_for_loss((sl_distance_price / tick_size) * tick_value, risk_usd, volume_min, volume_max, volume_step)


# SYMBOL_TRADE_TICK_VALUE cannot be trusted blindly: MetaQuotes-Demo reports 0.1 for XAUUSD and 0.5 for
# XAGUSD while the closed deals pay $1.0 / $5.0 per tick per lot, which sized metals ten times over budget
# on 2026-09-07. The terminal's own calculator (order_calc_profit) prices a move with the real contract size
# and currency conversion, so it is the primary source. The field is used only as a fallback for symbols
# where it has been checked against the terminal (verify_tick_value); otherwise no lot is placed.
TICK_VALUE_TRUSTED: dict = {}          # symbol -> True (field agrees with the terminal) / False (it does not)
TICK_VALUE_TOLERANCE = 0.01            # relative difference tolerated between the field and the terminal


def reported_loss_per_lot(sl_distance_price: float, info) -> float:
    """Loss on one lot at the stop according to SYMBOL_TRADE_TICK_VALUE (unverified; see TICK_VALUE_TRUSTED)."""
    if info.trade_tick_size <= 0:
        return 0.0
    return (sl_distance_price / info.trade_tick_size) * info.trade_tick_value


def terminal_loss_per_lot(symbol: str, side, price, distance: float):
    """Account-currency loss on ONE lot when price moves `distance` against a `side` position, priced by
    the terminal. None when the terminal cannot price it (no calculator, no price, disconnected)."""
    calc = getattr(mt5, "order_calc_profit", None)
    if not callable(calc) or side not in ("BUY", "SELL") or not price or price <= 0 or distance <= 0:
        return None
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    stop_price = price - distance if side == "BUY" else price + distance
    try:
        value = calc(order_type, symbol, 1.0, float(price), float(stop_price))
    except Exception:
        return None
    if value is None or value >= 0:
        return None
    return -float(value)


def _record_trust(symbol: str, info, terminal_loss: float, distance: float) -> bool:
    reported = reported_loss_per_lot(distance, info)
    ok = reported > 0 and abs(terminal_loss - reported) / terminal_loss <= TICK_VALUE_TOLERANCE
    if TICK_VALUE_TRUSTED.get(symbol) != ok:
        TICK_VALUE_TRUSTED[symbol] = ok
        if ok:
            log.info("[%s] tick value %s verified against the terminal", symbol, info.trade_tick_value)
        else:
            log.warning("[%s] SYMBOL_TRADE_TICK_VALUE %s is wrong: a %.5g move costs $%.2f/lot by the field but "
                        "$%.2f/lot by the terminal; this symbol is sized from the terminal only",
                        symbol, info.trade_tick_value, distance, reported, terminal_loss)
    return ok


def verify_tick_value(symbol: str, info=None):
    """Check SYMBOL_TRADE_TICK_VALUE against the terminal over a 100-tick move at the last known price.
    Returns True / False and records it in TICK_VALUE_TRUSTED; None when the terminal cannot price it."""
    info = info if info is not None else (mt5.symbol_info(symbol) if callable(getattr(mt5, "symbol_info", None)) else None)
    if info is None or info.trade_tick_size <= 0:
        return None
    price = getattr(info, "bid", 0) or getattr(info, "ask", 0) or 0
    distance = info.trade_tick_size * 100
    loss = terminal_loss_per_lot(symbol, "BUY", price, distance)
    if loss is None:
        return None
    return _record_trust(symbol, info, loss, distance)


def loss_per_lot(symbol: str, side, price, sl_distance_price: float, info) -> tuple:
    """(loss on one lot at the stop, source). source: "terminal" (priced by the terminal), "tick_value"
    (field fallback, only for a symbol whose field was verified against the terminal), or "unavailable"
    (loss 0.0: the terminal could not price the move and the field is unverified or wrong)."""
    loss = terminal_loss_per_lot(symbol, side, price, sl_distance_price)
    if loss is not None:
        _record_trust(symbol, info, loss, sl_distance_price)
        return loss, "terminal"
    if TICK_VALUE_TRUSTED.get(symbol) is True:
        return reported_loss_per_lot(sl_distance_price, info), "tick_value"
    return 0.0, "unavailable"


def calculate_dynamic_lot(symbol: str, sl_distance_price: float, risk_usd: float,
                          side: str | None = None, price: float | None = None) -> float:
    """Lot for the risk budget at this stop distance. `side` and `price` let the terminal price the move;
    a symbol whose tick value is unverified or wrong gets no lot when the terminal cannot price it."""
    info = mt5.symbol_info(symbol)
    if info is None or sl_distance_price <= 0:
        return 0.0
    loss, source = loss_per_lot(symbol, side, price, sl_distance_price, info)
    if source == "unavailable":
        verdict = "wrong" if TICK_VALUE_TRUSTED.get(symbol) is False else "not verified"
        log.warning("[%s] SKIP: the terminal could not price a %.5g stop (side=%s price=%s) and SYMBOL_TRADE_TICK_VALUE "
                    "is %s for this symbol; no lot placed. Check the terminal connection and quote.",
                    symbol, sl_distance_price, side, price, verdict)
        return 0.0
    if loss <= 0:
        return 0.0
    lot = lot_for_loss(loss, risk_usd, info.volume_min, info.volume_max, info.volume_step)
    if lot == 0.0:
        log.info("[%s] SKIP: min lot %s would risk $%.2f > budget $%.2f",
                 symbol, info.volume_min, info.volume_min * loss, risk_usd)
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


def send_market_order(action_type: str, symbol: str, lot: float, price: float, sl: float, tp: float,
                      engine=None) -> bool:
    """Send a market order. Returns True on fill. Never raises on MT5 None returns."""
    info = mt5.symbol_info(symbol)
    if info is None:
        log.error("[%s] symbol_info returned None; order not sent", symbol)
        send_telegram(f"<b>Order not sent</b>\nsymbol_info({symbol}) returned None")
        return False

    digits = info.digits
    magic = engine.magic if engine is not None else config.MAGIC_NUMBER
    comment_prefix = engine.comment if engine is not None else "AlgoBot"
    risk_usd = engine.risk_usd if engine is not None else config.RISK_USD_PER_TRADE
    tag = f"[{engine.name}] " if engine is not None and engine.name != "scalper" else ""
    engine_line = f"▪ <b>Engine:</b> {engine.name}\n" if tag else ""
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
        "magic": magic,
        "comment": f"{comment_prefix}-{symbol}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(info),
    }

    res = mt5.order_send(request)
    if res is None:
        err = mt5.last_error()
        log.error("[%s] order_send returned None (terminal disconnected?) last_error=%s", symbol, err)
        record_trade("REJECTED", symbol, action_type, lot, price, sl, tp, note=f"{tag}order_send None {err}")
        send_telegram(f"\U0001F534 <b>Order failed: {action_type} {symbol}</b>\norder_send returned None: {err}")
        return False

    if res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("[%s] EXECUTED %s lot=%s entry=%.*f sl=%.*f tp=%.*f ticket=%s",
                 symbol, action_type, lot, digits, price, digits, sl, digits, tp, res.order)
        record_trade("ENTRY", symbol, action_type, lot, round(price, digits), round(sl, digits),
                     round(tp, digits), ticket=res.order, note=tag)
        send_telegram(
            f"\U0001F7E2 <b>Trade Opened: {action_type}</b>\n\n"
            f"{engine_line}"
            f"▪ <b>Asset:</b> {symbol}\n"
            f"▪ <b>Lot:</b> {lot}\n"
            f"▪ <b>Entry:</b> {price:.{digits}f}\n"
            f"▪ <b>SL:</b> {sl:.{digits}f}\n"
            f"▪ <b>TP:</b> {tp:.{digits}f}\n"
            f"▪ <b>Risk Budget:</b> ${risk_usd:.2f}"
        )
        return True

    log.warning("[%s] REJECTED %s lot=%s retcode=%s %s", symbol, action_type, lot, res.retcode, res.comment)
    record_trade("REJECTED", symbol, action_type, lot, price, sl, tp, note=f"{tag}{res.retcode} {res.comment}")
    send_telegram(f"\U0001F534 <b>Order rejected: {action_type} {symbol}</b>\n▪ retcode {res.retcode}\n▪ {res.comment}")
    return False


def modify_sl(position, new_sl: float, magic=None) -> bool:
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
        "magic": config.MAGIC_NUMBER if magic is None else magic,
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning("[%s] SL modify failed for #%s: %s", position.symbol,
                    position.ticket, getattr(res, "comment", mt5.last_error()))
        return False
    return True
