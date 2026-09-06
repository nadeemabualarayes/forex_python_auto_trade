"""Orchestrator: risk check -> manage positions -> per-symbol signals -> reporting."""
import time
import traceback

import MetaTrader5 as mt5

import config
from execution import init_mt5
from journal import setup_logging, log
from position_manager import manage_positions
from reporting import Reporter
from risk import ServerClock, get_daily_stats, breaker_reason
from strategy import SymbolTrader
from telegram_notifier import send_telegram


class Bot:
    def __init__(self, symbols):
        self.symbols = symbols
        self.traders = {s: SymbolTrader(s) for s in symbols}
        self.reporter = Reporter()
        self.clock = ServerClock()
        self.breaker_alerted = False
        self.no_quote_logged = False

    def tick(self) -> float:
        """One pass. Returns how long to sleep before the next one."""
        now = self.clock.now(self.symbols)
        if now is None:
            if not self.no_quote_logged:
                log.warning("no quotes for %s yet (market closed?)", self.symbols)
                self.no_quote_logged = True
            return config.LOOP_SLEEP_SECONDS
        self.no_quote_logged = False

        stats = get_daily_stats(config.MAGIC_NUMBER, now)
        self.reporter.notify_closes(stats)
        manage_positions()
        self.reporter.maybe_heartbeat(now, stats, self.symbols)
        self.reporter.maybe_daily_summary(now, stats)

        reason = breaker_reason(stats)
        if reason:
            if not self.breaker_alerted:
                msg = (f"⛔ <b>Daily circuit breaker</b>\n▪ {reason}\n"
                       f"▪ Day net: ${stats.net_pnl:.2f}\n<i>Entries paused until next server day.</i>")
                log.warning("BREAKER: %s", reason)
                send_telegram(msg)
                self.breaker_alerted = True
            return config.BREAKER_SLEEP_SECONDS
        self.breaker_alerted = False

        for trader in self.traders.values():
            trader.step(now, stats.entries)
        return config.LOOP_SLEEP_SECONDS


def run():
    setup_logging()
    symbols = init_mt5(config.SYMBOLS)
    if not symbols:
        log.error("no tradable symbols, exiting")
        return

    log.info("START symbols=%s risk=$%.2f/trade cap=%d/day trend=%s session=%s",
             symbols, config.RISK_USD_PER_TRADE, config.MAX_TRADES_PER_DAY,
             config.TREND_FILTER_ENABLED, config.SESSION_FILTER_ENABLED)
    send_telegram(f"\U0001F680 <b>Bot started</b> on {', '.join(symbols)}")
    bot = Bot(symbols)

    try:
        while True:
            try:
                time.sleep(bot.tick())
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.error("loop iteration failed: %s\n%s", e, traceback.format_exc())
                send_telegram(f"⚠️ <b>Bot error</b> (still running)\n<code>{type(e).__name__}: {e}</code>")
                if mt5.terminal_info() is None:
                    log.warning("MT5 terminal not reachable, re-initializing")
                    init_mt5(symbols)
                time.sleep(config.ERROR_SLEEP_SECONDS)
    except KeyboardInterrupt:
        log.info("STOP bot terminated manually")
        send_telegram("\U0001F6D1 <b>Bot stopped</b> manually")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    run()
