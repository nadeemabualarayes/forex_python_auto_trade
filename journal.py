"""Rotating file log + CSV trade journal."""
import csv
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

import config

log = logging.getLogger("bot")

_JOURNAL_FIELDS = ["time", "event", "symbol", "side", "lot", "price", "sl", "tp", "pnl", "ticket", "note"]


def setup_logging(level=logging.INFO) -> logging.Logger:
    """Console (UTF-8) + rotating file handler. Safe to call more than once."""
    if log.handlers:
        return log
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    fileh = RotatingFileHandler(config.LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fileh.setFormatter(fmt)

    log.setLevel(level)
    log.addHandler(console)
    log.addHandler(fileh)
    return log


def record_trade(event: str, symbol: str, side: str = "", lot="", price="", sl="", tp="",
                 pnl="", ticket="", note="", when: datetime | None = None) -> None:
    """Append one row to the CSV journal. event: ENTRY | EXIT | SL_MOVE | REJECTED | SKIP."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(config.TRADE_JOURNAL)
    row = {
        "time": (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "event": event, "symbol": symbol, "side": side, "lot": lot, "price": price,
        "sl": sl, "tp": tp, "pnl": pnl, "ticket": ticket, "note": note,
    }
    with open(config.TRADE_JOURNAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)
