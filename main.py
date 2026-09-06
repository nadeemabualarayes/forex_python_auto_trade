"""Orchestrator: risk check -> manage positions -> per-symbol signals -> reporting."""
import sys
import time
import traceback

import MetaTrader5 as mt5

import config
from execution import init_mt5, bot_positions
from journal import setup_logging, log
from position_manager import manage_positions
from reporting import Reporter
from risk import ServerClock, get_daily_stats, breaker_reason
from status import build_status
from strategy import SymbolTrader
from telegram_notifier import send_telegram
from web import StatusServer


class Bot:
    def __init__(self, symbols, web: StatusServer | None = None):
        self.symbols = symbols
        self.traders = {s: SymbolTrader(s) for s in symbols}
        self.reporter = Reporter()
        self.clock = ServerClock()
        self.web = web
        self.started_at = time.monotonic()
        self.breaker_alerted = False
        self.no_quote_logged = False

    def _publish(self, now, stats, breaker) -> None:
        """Push a snapshot to the status page. Never allowed to break trading."""
        if self.web is None:
            return
        try:
            self.web.update(build_status(now, stats, bot_positions(), self.traders.values(), breaker,
                                         self.symbols, self.started_at, time.monotonic()))
        except Exception as e:
            log.warning("status update failed: %s", e)

    def tick(self) -> float:
        """One pass. Returns how long to sleep before the next one."""
        now = self.clock.now(self.symbols)
        if now is None:
            if not self.no_quote_logged:
                log.warning("no quotes for %s yet (market closed?)", self.symbols)
                self.no_quote_logged = True
            self._publish(None, None, None)
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
            self._publish(now, stats, reason)
            return config.BREAKER_SLEEP_SECONDS
        self.breaker_alerted = False

        for trader in self.traders.values():
            trader.step(now, stats.entries)
        self._publish(now, stats, None)
        return config.LOOP_SLEEP_SECONDS


def run() -> int:
    """Returns the process exit code: 0 on manual stop, 1 when MT5 is unusable at startup.

    A non-zero code matters because Task Scheduler only restarts a task that *failed*."""
    setup_logging()
    symbols = init_mt5(config.SYMBOLS)
    if not symbols:
        log.error("no tradable symbols, exiting with code 1 so the scheduler restarts us")
        return 1

    log.info("START symbols=%s risk=$%.2f/trade cap=%d/day trend=%s session=%s",
             symbols, config.RISK_USD_PER_TRADE, config.MAX_TRADES_PER_DAY,
             config.TREND_FILTER_ENABLED, config.SESSION_FILTER_ENABLED)
    send_telegram(f"\U0001F680 <b>Bot started</b> on {', '.join(symbols)}")
    web = StatusServer() if config.WEB_ENABLED else None
    if web and not web.start():
        web = None
    bot = Bot(symbols, web)

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
        if web:
            web.stop()
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(run())
