"""Account-level daily statistics and circuit breaker, all in MT5 server time."""
import calendar
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import config


def to_server_dt(epoch: int) -> datetime:
    """MT5 epoch -> naive datetime showing the server wall clock."""
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def server_now(symbols):
    """Freshest tick time across symbols, as server wall-clock. None if no symbol has a quote."""
    latest = 0
    for s in symbols:
        tick = mt5.symbol_info_tick(s)
        if tick is not None and tick.time > latest:
            latest = tick.time
    return to_server_dt(latest) if latest else None


class ServerClock:
    """Estimates MT5 server wall-clock time, even between ticks (weekends).

    While ticks are flowing the offset (server epoch - local epoch) is refreshed; when
    they stop, local time + last offset keeps the clock moving so heartbeats and the
    daily summary still fire. Before any fresh tick is seen, the last tick time is used.
    """

    def __init__(self):
        self.offset = None
        self._last_msc = {}

    def now(self, symbols):
        latest, fresh = 0, False
        for s in symbols:
            t = mt5.symbol_info_tick(s)
            if t is None or t.time == 0:
                continue
            prev = self._last_msc.get(s)
            if prev is not None and prev != t.time_msc:
                fresh = True
            self._last_msc[s] = t.time_msc
            latest = max(latest, t.time)
        if fresh:
            self.offset = latest - time.time()
        if self.offset is not None:
            return to_server_dt(time.time() + self.offset)
        return to_server_dt(latest) if latest else None


def day_start_epoch(server_dt: datetime) -> int:
    return calendar.timegm(server_dt.date().timetuple())


@dataclass
class DailyStats:
    net_pnl: float = 0.0
    consecutive_losses: int = 0
    entries: int = 0
    wins: int = 0
    losses: int = 0
    closed: list = field(default_factory=list)      # OUT deals, chronological

    @property
    def closed_count(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return (self.wins / self.closed_count * 100) if self.closed_count else 0.0


def deal_net(d) -> float:
    return d.profit + d.commission + d.swap + d.fee


def stats_from_deals(deals, magic: int, start_epoch: int) -> DailyStats:
    """Pure aggregation, testable without MT5."""
    s = DailyStats()
    bot = sorted((d for d in deals if d.magic == magic and d.time >= start_epoch),
                 key=lambda d: (d.time, d.ticket))
    exit_kinds = (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT)
    for d in bot:
        net = deal_net(d)
        s.net_pnl += net
        if d.entry == mt5.DEAL_ENTRY_IN:
            s.entries += 1
        elif d.entry in exit_kinds:
            s.closed.append(d)
            if net < 0:
                s.losses += 1
                s.consecutive_losses += 1
            else:
                s.wins += 1
                s.consecutive_losses = 0
    return s


def get_daily_stats(magic: int, server_dt: datetime) -> DailyStats:
    start = day_start_epoch(server_dt)
    date_from = datetime.fromtimestamp(start, timezone.utc) - timedelta(days=1)
    date_to = datetime.now(timezone.utc) + timedelta(days=2)
    deals = mt5.history_deals_get(date_from, date_to) or ()
    return stats_from_deals(deals, magic, start)


def breaker_reason(stats: DailyStats):
    if stats.net_pnl <= -config.MAX_DAILY_LOSS_USD:
        return f"daily loss ${abs(stats.net_pnl):.2f} >= limit ${config.MAX_DAILY_LOSS_USD:.2f}"
    if stats.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        return f"{stats.consecutive_losses} consecutive losses"
    return None
