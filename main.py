"""Orchestrator: risk check -> manage positions -> per-symbol signals -> reporting."""
import calendar
import sys
import time
import traceback
from dataclasses import replace

import MetaTrader5 as mt5

import config
from analytics import pair_trades, build_analytics, trade_dicts
from engines import build_engines, engine_names
from execution import init_mt5, bot_positions, trading_blockers, set_known_magics
from history import TradeStore, sync_deals, snapshot_equity
from journal import setup_logging, log
from news import NewsFilter
from position_manager import manage_positions
from reporting import Reporter
from risk import ServerClock, daily_stats_by_magic, combine, account_breaker, engine_breaker
from publisher import PagesPublisher
from status import build_status, with_trades, chart_block, engine_block
from strategy import SymbolTrader
from telegram_notifier import send_telegram
from web import StatusServer


class Bot:
    def __init__(self, symbols, web: StatusServer | None = None, pages: PagesPublisher | None = None,
                 engines=None):
        available = list(symbols)
        self.paused: dict = {}                      # engine name -> pause reason already announced
        self.all_engines = []                        # every built engine, original symbols: registry/history/breaker
        self.engines = []                             # tradeable subset (symbols restricted): traders/chart refresh
        for e in (engines if engines is not None else build_engines()):
            self.all_engines.append(e)
            syms = tuple(s for s in e.symbols if s in available)
            if not syms:
                log.warning("engine %s disabled: none of %s is available", e.name, list(e.symbols))
                self.paused[e.name] = "no symbols available"
                continue
            self.engines.append(replace(e, symbols=syms))
        self.symbols = []
        for e in self.engines:
            for s in e.symbols:
                if s not in self.symbols:
                    self.symbols.append(s)
        set_known_magics(e.magic for e in self.all_engines)
        self.traders = [SymbolTrader(s, e) for e in self.engines for s in e.symbols]
        self.reporter = Reporter(engine_names(self.all_engines))
        self.clock = ServerClock()
        self.web = web
        self.pages = pages
        self.store = TradeStore() if config.HISTORY_ENABLED else None
        self.last_sync: float | None = None
        self.account: dict | None = None
        self.analytics: dict | None = None
        self.history: list = []
        self.charts: dict = {}
        self.last_chart_refresh: float | None = None
        self.started_at = time.monotonic()
        self.breaker_alerted = False
        self.errored: dict = {}                      # (symbol, engine) -> last error text already announced
        self.no_quote_logged = False
        self.news = NewsFilter()
        self.news_alerted: str | None = None        # blackout reason already announced on Telegram

    def _maybe_sync_history(self, now) -> None:
        """Every HISTORY_SYNC_SECONDS: pull deals from MT5, snapshot equity, recompute the
        cached analytics. Runs with or without quotes so equity keeps recording on weekends."""
        if self.store is None:
            return
        mono = time.monotonic()
        if self.last_sync is not None and mono - self.last_sync < config.HISTORY_SYNC_SECONDS:
            return
        self.last_sync = mono
        try:
            n = sync_deals(self.store, [e.magic for e in self.all_engines], config.HISTORY_INCLUDE_ALL_DEALS)
            epoch = calendar.timegm(now.timetuple()) if now else int(time.time())
            open_pnl = sum(p.profit for p in bot_positions())
            self.account = snapshot_equity(self.store, open_pnl=open_pnl, now_epoch=epoch)
            trades = pair_trades(self.store.deals())
            start_balance = None
            if self.account:
                start_balance = round(self.account["balance"] - sum(t.net for t in trades), 2)
            snapshots = self.store.equity_series(since=epoch - 30 * 86400, step=3600)
            self.analytics = build_analytics(trades, start_balance, snapshots)
            self.history = trade_dicts(trades, config.HISTORY_MAX_TRADES, engine_names(self.all_engines))
            if n:
                log.info("history: synced %d deals, %d closed trades on record", n, len(trades))
        except Exception as e:
            log.warning("history sync failed: %s", e)

    def _maybe_refresh_charts(self) -> None:
        """Every CHART_REFRESH_SECONDS: rebuild the per-symbol candle panels from each trader's frame."""
        mono = time.monotonic()
        if self.last_chart_refresh is not None and mono - self.last_chart_refresh < config.CHART_REFRESH_SECONDS:
            return
        self.last_chart_refresh = mono
        try:
            positions = bot_positions()
            charts = {}
            for trader in self.traders:
                if trader.symbol in charts:
                    continue                            # first engine listing the symbol draws it
                blk = chart_block(trader.frame(config.CHART_REFRESH_SECONDS), trader.symbol, positions)
                if blk is not None:
                    charts[trader.symbol] = blk
            self.charts = charts
        except Exception as e:
            log.warning("chart refresh failed: %s", e)

    def _publish(self, now, stats, breaker, engine_stats=None) -> None:
        """Push a snapshot to the status page and (on its interval) to GitHub Pages.
        Never allowed to break trading."""
        if self.web is None and self.pages is None:
            return
        try:
            self._maybe_refresh_charts()
            blocks = [engine_block(e, (engine_stats or {}).get(e.name), self.paused.get(e.name))
                      for e in self.all_engines]
            snap = build_status(now, stats, bot_positions(), self.traders, breaker,
                                self.symbols, self.started_at, time.monotonic(),
                                account=self.account, analytics=self.analytics, history=self.history,
                                charts=self.charts, news=self.news.snapshot(), engines=blocks)
            if self.web is not None:
                self.web.update(snap)
            if self.pages is not None:
                self.pages.maybe_publish(with_trades(snap))
        except Exception as e:
            log.warning("status update failed: %s", e)

    def tick(self) -> float:
        """One pass. Returns how long to sleep before the next one."""
        now = self.clock.now(self.symbols)
        self._maybe_sync_history(now)
        self.news.maybe_refresh()                    # cheap when not due; runs on weekends too
        if now is None:
            if not self.no_quote_logged:
                log.warning("no quotes for %s yet (market closed?)", self.symbols)
                self.no_quote_logged = True
            self._publish(None, None, None)
            return config.LOOP_SLEEP_SECONDS
        self.no_quote_logged = False

        stats_by_magic = daily_stats_by_magic([e.magic for e in self.all_engines], now)
        engine_stats = {e.name: stats_by_magic[e.magic] for e in self.all_engines}
        stats = combine(engine_stats.values())
        pairs = [(e, engine_stats[e.name]) for e in self.all_engines]
        self.reporter.notify_closes(stats)
        for e in self.engines:
            manage_positions(e)
        self.reporter.maybe_heartbeat(now, stats, self.symbols, pairs)
        self.reporter.maybe_daily_summary(now, stats, pairs)

        reason = account_breaker(stats)
        if reason:
            if not self.breaker_alerted:
                per_engine = "".join(f"▪ {e.name}: ${s.net_pnl:.2f}\n" for e, s in pairs)
                msg = (f"⛔ <b>Daily circuit breaker</b>\n▪ {reason}\n"
                       f"▪ Day net: ${stats.net_pnl:.2f}\n{per_engine}"
                       f"<i>Entries paused until next server day.</i>")
                log.warning("BREAKER: %s", reason)
                send_telegram(msg)
                self.breaker_alerted = True
            self._publish(now, stats, reason, engine_stats)
            return config.BREAKER_SLEEP_SECONDS
        self.breaker_alerted = False

        news_block = self.news.block_reason()
        if news_block and news_block != self.news_alerted:
            log.info("NEWS %s: entries paused %d min before / %d min after", news_block,
                     config.NEWS_BLOCK_BEFORE_MIN, config.NEWS_BLOCK_AFTER_MIN)
            send_telegram(f"\U0001F4F0 <b>News blackout</b>\n▪ {news_block}\n"
                          f"<i>No new entries {config.NEWS_BLOCK_BEFORE_MIN} min before / "
                          f"{config.NEWS_BLOCK_AFTER_MIN} min after.</i>")
        self.news_alerted = news_block

        for trader in self.traders:
            e = trader.engine
            es = engine_stats[e.name]
            pause = engine_breaker(e, es)
            if pause:
                if self.paused.get(e.name) != pause:
                    log.warning("[%s] engine paused: %s", e.name, pause)
                    send_telegram(f"⏸ <b>{e.name} paused</b>\n▪ {pause}\n<i>Other engines keep trading.</i>")
                    self.paused[e.name] = pause
                continue
            self.paused.pop(e.name, None)
            try:
                trader.step(now, es.entries, news_block)
                self.errored.pop((trader.symbol, e.name), None)
            except Exception as exc:
                if mt5.terminal_info() is None:
                    raise                                # terminal gone: let run() reconnect
                log.error("[%s] %s step failed: %s\n%s", trader.symbol, e.name, exc, traceback.format_exc())
                text = f"{type(exc).__name__}: {exc}"
                if self.errored.get((trader.symbol, e.name)) != text:
                    send_telegram(f"⚠️ <b>{e.name} error on {trader.symbol}</b> (bot still running)\n"
                                  f"<code>{text}</code>")
                    self.errored[(trader.symbol, e.name)] = text
        self._publish(now, stats, None, engine_stats)
        return config.LOOP_SLEEP_SECONDS


def warn_if_trading_blocked() -> list[str]:
    """Startup guard: say *now* why orders would be rejected instead of waiting for the first retcode 10027."""
    reasons = trading_blockers(mt5.terminal_info(), mt5.account_info())
    if reasons:
        log.warning("TRADING BLOCKED: %s", "; ".join(reasons))
        send_telegram("⚠️ <b>Trading blocked</b> (bot running, entries will be rejected)\n"
                      + "\n".join(f"▪ {r}" for r in reasons))
    return reasons


def run() -> int:
    """Returns the process exit code: 0 on manual stop, 1 when MT5 is unusable at startup.

    A non-zero code matters because Task Scheduler only restarts a task that *failed*."""
    setup_logging()
    engines = build_engines()
    wanted = []
    for e in engines:
        for s in e.symbols:
            if s not in wanted:
                wanted.append(s)
    symbols = init_mt5(wanted)
    if not symbols:
        log.error("no tradable symbols, exiting with code 1 so the scheduler restarts us")
        return 1

    for e in engines:
        log.info("START engine=%s magic=%s symbols=%s risk=$%.2f/trade cap=%d/day trend=%s",
                 e.name, e.magic, [s for s in e.symbols if s in symbols], e.risk_usd, e.max_trades_per_day, e.trend_filter)
    log.info("START session=%s news=%s", config.SESSION_FILTER_ENABLED, config.NEWS_FILTER_ENABLED)
    send_telegram("\U0001F680 <b>Bot started</b>\n" + "\n".join(
        f"▪ {e.name}: {', '.join(s for s in e.symbols if s in symbols) or 'no symbols'}" for e in engines))
    warn_if_trading_blocked()
    web = StatusServer() if config.WEB_ENABLED else None
    if web and not web.start():
        web = None
    pages = PagesPublisher() if config.PAGES_PUBLISH_ENABLED else None
    if pages and not pages.remote:
        log.warning("pages publishing disabled: no git remote found")
        pages = None
    bot = Bot(symbols, web, pages, engines)

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
        if pages:
            pages.join(10)
        if web:
            web.stop()
        if bot.store:
            bot.store.close()
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(run())
