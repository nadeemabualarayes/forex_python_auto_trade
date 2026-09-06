import sys
import time
import traceback
from datetime import datetime, date
import numpy as np
import MetaTrader5 as mt5
import config
from technicals import compute_indicators
from execution import init_mt5, get_rates, calculate_dynamic_lot, send_market_order
from telegram_notifier import send_telegram

# Windows consoles default to cp1252 and choke on the emoji in alerts.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def get_daily_performance(magic: int):
    today_start = datetime.combine(date.today(), datetime.min.time())
    deals = mt5.history_deals_get(today_start, datetime.now())
    if deals is None or len(deals) == 0:
        return 0.0, 0

    daily_profit = 0.0
    consecutive_losses = 0
    bot_deals = [d for d in deals if d.magic == magic and d.entry == mt5.DEAL_ENTRY_OUT]

    for d in sorted(bot_deals, key=lambda d: d.time):
        net = d.profit + d.commission + d.swap + d.fee   # net P&L, not gross
        daily_profit += net
        consecutive_losses = consecutive_losses + 1 if net < 0 else 0

    return daily_profit, consecutive_losses


def is_spread_acceptable(symbol: str) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None or info.point == 0:
        return False
    spread = (tick.ask - tick.bid) / info.point
    return spread <= config.MAX_ALLOWED_SPREAD_POINTS


def trade_once(state: dict) -> None:
    """One pass of the strategy. state['last_signal_bar'] prevents re-trading the same candle."""
    # 1. Daily Circuit Breaker Check
    pnl, losses = get_daily_performance(config.MAGIC_NUMBER)
    if pnl <= -config.MAX_DAILY_LOSS_USD or losses >= config.MAX_CONSECUTIVE_LOSSES:
        if not state.get("breaker_alerted"):
            alert = (
                f"⛔ <b>Daily Circuit Breaker Triggered!</b>\n\n"
                f"▪ Daily Drawdown: ${abs(pnl):.2f}\n"
                f"▪ Consecutive Losses: {losses}\n"
                f"<i>Trading paused automatically until next trading day.</i>"
            )
            print(alert)
            send_telegram(alert)
            state["breaker_alerted"] = True
        time.sleep(3600)
        return
    state["breaker_alerted"] = False

    # 2. Check active positions
    positions = mt5.positions_get(symbol=config.SYMBOL)
    if positions and any(p.magic == config.MAGIC_NUMBER for p in positions):
        time.sleep(config.LOOP_SLEEP_SECONDS)
        return

    # 3. Spread filter
    if not is_spread_acceptable(config.SYMBOL):
        time.sleep(config.LOOP_SLEEP_SECONDS)
        return

    # 4. Fetch & analyze rates
    df = get_rates(config.SYMBOL, config.TIMEFRAME, n=120)
    if df is None or len(df) < 30:
        time.sleep(3)
        return

    df = compute_indicators(df)
    last = df.iloc[-2]                     # last *closed* candle
    signal_bar = last['time']
    atr = last['atr']
    tick = mt5.symbol_info_tick(config.SYMBOL)

    if np.isnan(atr) or tick is None:
        time.sleep(2)
        return

    # 5. One attempt per candle, whether it fills or is rejected
    if state.get("last_signal_bar") == signal_bar:
        time.sleep(config.LOOP_SLEEP_SECONDS)
        return

    sl_dist = atr * config.SL_ATR_MULTIPLIER
    tp_dist = atr * config.TP_ATR_MULTIPLIER

    signal = None
    if last['close'] <= last['lower_band'] and last['rsi'] < 30:
        signal = "BUY"
    elif last['close'] >= last['upper_band'] and last['rsi'] > 70:
        signal = "SELL"

    if signal:
        state["last_signal_bar"] = signal_bar
        lot = calculate_dynamic_lot(config.SYMBOL, sl_dist, config.RISK_USD_PER_TRADE)
        if lot <= 0:
            print(f"[SKIP] {signal} signal on {signal_bar} skipped: no lot fits risk budget")
        elif signal == "BUY":
            send_market_order("BUY", config.SYMBOL, lot, tick.ask, tick.ask - sl_dist, tick.ask + tp_dist)
        else:
            send_market_order("SELL", config.SYMBOL, lot, tick.bid, tick.bid + sl_dist, tick.bid - tp_dist)

    time.sleep(config.LOOP_SLEEP_SECONDS)


def run():
    if not init_mt5(config.SYMBOL):
        return

    print(f"[START] System live on {config.SYMBOL}. Risk Circuit Breakers & Alerts enabled.")
    send_telegram(f"🚀 <b>Bot started</b> on {config.SYMBOL}")
    state = {}

    try:
        while True:
            try:
                trade_once(state)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[ERROR] Loop iteration failed: {e}\n{tb}")
                send_telegram(f"⚠️ <b>Bot error</b> (still running)\n<code>{type(e).__name__}: {e}</code>")
                # If the terminal dropped, try to reconnect before the next pass
                if mt5.terminal_info() is None:
                    print("[RECONNECT] MT5 terminal not reachable, re-initializing...")
                    init_mt5(config.SYMBOL)
                time.sleep(config.ERROR_SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("[STOP] Bot terminated manually.")
        send_telegram("🛑 <b>Bot stopped</b> manually")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    run()
