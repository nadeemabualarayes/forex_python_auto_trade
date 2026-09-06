"""Close notifications, heartbeat and end-of-day summary."""
import time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

import config
from execution import bot_positions
from journal import log, record_trade
from risk import DailyStats, deal_net, to_server_dt
from telegram_notifier import send_telegram


class Reporter:
    def __init__(self):
        self.seen_exit_tickets: set = set()
        self.last_heartbeat: float | None = None      # time.monotonic()
        self.last_summary_date = None
        self.primed = False

    # -- exits ----------------------------------------------------------------
    def notify_closes(self, stats: DailyStats) -> None:
        """Telegram + journal for every OUT deal we have not reported yet."""
        for d in stats.closed:
            if d.ticket in self.seen_exit_tickets:
                continue
            self.seen_exit_tickets.add(d.ticket)
            if not self.primed:
                continue                                # exits that happened before start-up
            net = deal_net(d)
            side = "SELL" if d.type == mt5.DEAL_TYPE_SELL else "BUY"     # closing deal side
            opened = "BUY" if side == "SELL" else "SELL"
            reason = {mt5.DEAL_REASON_SL: "SL", mt5.DEAL_REASON_TP: "TP"}.get(d.reason, "manual/other")
            record_trade("EXIT", d.symbol, opened, d.volume, d.price, pnl=round(net, 2),
                         ticket=d.position_id, note=f"{reason} @ {to_server_dt(d.time):%Y-%m-%d %H:%M} server")
            emoji = "✅" if net >= 0 else "❌"
            log.info("[%s] CLOSED %s #%s net=%.2f (%s)", d.symbol, opened, d.position_id, net, reason)
            send_telegram(
                f"{emoji} <b>Trade Closed: {opened} {d.symbol}</b>\n"
                f"▪ Exit: {d.price}\n▪ Net: ${net:.2f} ({reason})\n"
                f"▪ Day: ${stats.net_pnl:.2f} | {stats.wins}W/{stats.losses}L"
            )
        self.primed = True

    # -- heartbeat --------------------------------------------------------------
    def maybe_heartbeat(self, server_dt: datetime, stats: DailyStats, symbols) -> None:
        mono = time.monotonic()
        if self.last_heartbeat is not None and mono - self.last_heartbeat < config.HEARTBEAT_HOURS * 3600:
            return
        self.last_heartbeat = mono
        pos = bot_positions()
        lines = [f"▪ {p.symbol} {'BUY' if p.type == mt5.POSITION_TYPE_BUY else 'SELL'} {p.volume} "
                 f"@ {p.price_open} P/L ${p.profit:.2f}" for p in pos] or ["▪ none"]
        send_telegram(
            f"\U0001F493 <b>Heartbeat</b> {server_dt:%Y-%m-%d %H:%M} server\n"
            f"▪ Symbols: {', '.join(symbols)}\n"
            f"▪ Day net: ${stats.net_pnl:.2f} | entries {stats.entries}/{config.MAX_TRADES_PER_DAY}\n"
            f"<b>Open positions</b>\n" + "\n".join(lines)
        )
        log.info("heartbeat sent")

    # -- daily summary ----------------------------------------------------------
    def maybe_daily_summary(self, server_dt: datetime, stats: DailyStats) -> None:
        if server_dt.hour < config.DAILY_SUMMARY_HOUR or self.last_summary_date == server_dt.date():
            return
        self.last_summary_date = server_dt.date()
        if stats.entries == 0 and stats.closed_count == 0:
            send_telegram(f"\U0001F4CA <b>Daily summary {server_dt:%Y-%m-%d}</b>\nNo trades today.")
            return
        best = max((deal_net(d) for d in stats.closed), default=0.0)
        worst = min((deal_net(d) for d in stats.closed), default=0.0)
        send_telegram(
            f"\U0001F4CA <b>Daily summary {server_dt:%Y-%m-%d}</b>\n"
            f"▪ Entries: {stats.entries}\n"
            f"▪ Closed: {stats.closed_count} ({stats.wins}W / {stats.losses}L, {stats.win_rate:.0f}%)\n"
            f"▪ Best: ${best:.2f} | Worst: ${worst:.2f}\n"
            f"▪ <b>Net: ${stats.net_pnl:.2f}</b>"
        )
        log.info("daily summary sent: net=%.2f closed=%d", stats.net_pnl, stats.closed_count)
