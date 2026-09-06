"""Persistent trade history: MT5 deals and equity snapshots in SQLite (logs/history.db).

The broker's deal history is the source of truth, so trades that closed while the bot was
down are still captured on the next sync. Everything downstream works on the plain `Deal`
dataclass, never on MT5 objects, so it is testable without a terminal.
"""
import os
import sqlite3
import time
from dataclasses import dataclass, astuple, fields
from datetime import datetime, timedelta, timezone
from typing import Iterable

import MetaTrader5 as mt5

import config
from journal import log


@dataclass
class Deal:
    ticket: int
    position_id: int
    symbol: str
    type: int           # DEAL_TYPE_BUY / DEAL_TYPE_SELL
    entry: int          # DEAL_ENTRY_IN / OUT / INOUT / OUT_BY
    magic: int
    reason: int         # DEAL_REASON_*
    volume: float
    price: float
    profit: float
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    time: int = 0       # server epoch
    order_id: int = 0
    comment: str = ""

    @classmethod
    def from_mt5(cls, d) -> "Deal":
        g = lambda name, default: getattr(d, name, default)      # fakes may lack optional fields
        return cls(
            ticket=int(d.ticket), position_id=int(d.position_id), symbol=str(d.symbol),
            type=int(d.type), entry=int(d.entry), magic=int(d.magic), reason=int(g("reason", 0) or 0),
            volume=float(d.volume), price=float(d.price), profit=float(d.profit),
            commission=float(g("commission", 0.0) or 0.0), swap=float(g("swap", 0.0) or 0.0),
            fee=float(g("fee", 0.0) or 0.0), time=int(d.time), order_id=int(g("order", 0) or 0),
            comment=str(g("comment", "") or ""),
        )

    @property
    def net(self) -> float:
        return self.profit + self.commission + self.swap + self.fee


_COLS = [f.name for f in fields(Deal)]
_EQUITY_COLS = ("time", "balance", "equity", "margin", "free_margin", "open_pnl")


class TradeStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config.LOG_DIR, config.HISTORY_DB)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(f"""CREATE TABLE IF NOT EXISTS deals (
            ticket INTEGER PRIMARY KEY, position_id INTEGER, symbol TEXT, type INTEGER, entry INTEGER,
            magic INTEGER, reason INTEGER, volume REAL, price REAL, profit REAL, commission REAL,
            swap REAL, fee REAL, time INTEGER, order_id INTEGER, comment TEXT)""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS deals_time ON deals(time)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS equity (
            time INTEGER PRIMARY KEY, balance REAL, equity REAL, margin REAL, free_margin REAL, open_pnl REAL)""")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- deals -------------------------------------------------------------------
    def upsert_deals(self, deals: Iterable[Deal]) -> int:
        rows = [astuple(d) for d in deals]
        if rows:
            marks = ",".join("?" * len(_COLS))
            self.conn.executemany(f"INSERT OR REPLACE INTO deals ({','.join(_COLS)}) VALUES ({marks})", rows)
            self.conn.commit()
        return len(rows)

    def last_deal_time(self) -> int | None:
        return self.conn.execute("SELECT MAX(time) FROM deals").fetchone()[0]

    def deals(self, magic: int | None = None) -> list[Deal]:
        sql = f"SELECT {','.join(_COLS)} FROM deals"
        args: tuple = ()
        if magic is not None:
            sql += " WHERE magic = ?"
            args = (magic,)
        sql += " ORDER BY time, ticket"
        return [Deal(*row) for row in self.conn.execute(sql, args)]

    # -- equity ------------------------------------------------------------------
    def record_equity(self, time: int, balance: float, equity: float, margin: float,
                      free_margin: float, open_pnl: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?)",
                          (int(time), balance, equity, margin, free_margin, open_pnl))
        self.conn.commit()

    def equity_series(self, since: int | None = None, step: int = 3600) -> list[dict]:
        """Snapshots downsampled to the last row per `step`-second bucket, oldest first."""
        sql = f"SELECT {','.join(_EQUITY_COLS)} FROM equity"
        args: tuple = ()
        if since is not None:
            sql += " WHERE time >= ?"
            args = (int(since),)
        sql += " ORDER BY time"
        out: dict[int, dict] = {}
        for row in self.conn.execute(sql, args):
            rec = dict(zip(_EQUITY_COLS, row))
            out[rec["time"] // max(1, step)] = rec           # later rows overwrite earlier in-bucket rows
        return list(out.values())


# -- MT5 sync ---------------------------------------------------------------------
def sync_deals(store: TradeStore, magic: int, include_all: bool = False) -> int:
    """Pull deals from MT5 into the store. First run = full history; later runs overlap the
    last day so amended commission/swap values are picked up. Returns rows written."""
    last = store.last_deal_time()
    if last:
        date_from = datetime.fromtimestamp(last, timezone.utc) - timedelta(days=1)
    else:
        date_from = datetime(2000, 1, 1, tzinfo=timezone.utc)
    date_to = datetime.now(timezone.utc) + timedelta(days=2)
    raw = mt5.history_deals_get(date_from, date_to)
    if raw is None:
        return 0
    deals = [Deal.from_mt5(d) for d in raw if include_all or d.magic == magic]
    n = store.upsert_deals(deals)
    if n:
        log.debug("history: synced %d deals", n)
    return n


def snapshot_equity(store: TradeStore, open_pnl: float = 0.0, now_epoch: int | None = None) -> dict | None:
    """Record balance/equity now. Returns the row (plus currency) or None when MT5 has no account."""
    info = mt5.account_info()
    if info is None:
        return None
    row = dict(time=int(now_epoch if now_epoch is not None else time.time()),
               balance=float(info.balance), equity=float(info.equity), margin=float(info.margin),
               free_margin=float(info.margin_free), open_pnl=float(open_pnl))
    store.record_equity(**row)
    return dict(row, currency=str(getattr(info, "currency", "") or ""))
